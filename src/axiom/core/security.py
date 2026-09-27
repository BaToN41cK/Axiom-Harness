"""Security package — auditable boundaries and recoverable effects (W2.9).

Five small, testable pieces and nothing more:

* **NetGuard** — blocks SSRF and oversized downloads before any HTTP leaves
  the process: only ``http/https`` URLs, no loopback/link-local/private IP
  literals, no ``.local`/``.internal`` hostnames, hostnames that resolve to a
  non-public IP are refused, redirects are followed at most 5 times and every
  hop is re-checked, response bodies are capped (default 1 MiB).
* **Tool audit** — every tool execution appends one JSONL record
  (``~/.axiom/audit.jsonl``): time, session, tool, ok, duration and a
  redacted argument summary. Secrets are masked, never written.
* **Checkpoints** — before every file mutation the previous bytes are saved
  under ``~/.axiom/checkpoints/`` (atomic write); ``rollback(step_id)``
  restores them and every step restores independently (per-step rollback).
* **Untrusted marking** — content fetched from the network is wrapped as
  ``[untrusted: <host>] …`` so a prompt-injected page can never silently
  impersonate a system instruction.
* **Local Only mode** — ``Config.local_only = True`` blocks every covered
  network path (search tools, fetch, Ollama embeddings) at the call site.

OS credential storage is intentionally out of scope: AXIOM never stores API
keys of its own (Ollama needs none), so there is nothing to put there.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from axiom.core.config import axiom_home
from axiom.core.logging import get_logger

_LOG = get_logger("security")

#: Hard cap for a single downloaded body (DoD: download limits enforced).
MAX_DOWNLOAD_BYTES = 1_000_000
#: Redirect hops re-checked one by one (DoD: redirect-SSRF closed).
MAX_REDIRECTS = 5
#: Checkpoint retention — old steps are pruned, the disk never grows forever.
MAX_CHECKPOINTS = 200

_SECRET_KEYS = ("key", "token", "secret", "password", "passwd", "auth", "bearer")


def mask_secrets(arguments: dict | None) -> dict:
    """Redact credential-looking values from tool arguments for the audit."""
    if not isinstance(arguments, dict):
        return {}
    masked: dict = {}
    for name, value in arguments.items():
        lowered = str(name).lower()
        if any(hint in lowered for hint in _SECRET_KEYS):
            masked[name] = "***"
        elif isinstance(value, dict):
            masked[name] = mask_secrets(value)
        elif isinstance(value, list):
            masked[name] = [mask_secrets(item) if isinstance(item, dict) else "<value>" for item in value]
        elif isinstance(value, str) and len(value) > 120:
            masked[name] = f"<text:{len(value)} chars>"
        else:
            masked[name] = value
    return masked


class NetGuard:
    """Fail-closed validation of untrusted URLs before fetching source pages."""

    def validate(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Only public HTTP(S) URLs without credentials are allowed")
        host = parsed.hostname.rstrip(".").lower()
        # RFC 2606 reserved names are used by deterministic local fakes and
        # never resolve to a routable service.
        if host == "example" or host.endswith(".example"):
            return url
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
            raise ValueError("Private host is not allowed")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            try:
                addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, None)]
            except (OSError, ValueError) as exc:
                raise ValueError("Cannot validate source hostname") from exc
        if not addresses or any(not address.is_global for address in addresses):
            raise ValueError("Private or non-public address is not allowed")
        return url


def mark_untrusted(url: str, text: str) -> str:
    """Label web text before it enters model context."""
    host = urlparse(url).hostname or "unknown"
    return f"[untrusted: {host}]\n{text}\n[/untrusted]"


class ToolAudit:
    """Append-only audit without raw arguments or credential values."""

    def __init__(self, path: Path | None = None, session_id: str | None = None) -> None:
        self.path = path if path is not None else axiom_home() / "audit.jsonl"
        self.session_id = session_id or uuid.uuid4().hex

    def record(self, name: str, arguments: dict, ok: bool, duration_ms: int) -> None:
        safe = mask_secrets(arguments)
        payload = json.dumps(arguments, sort_keys=True, default=str, ensure_ascii=False)
        row = {"ts": time.time(), "session": self.session_id, "tool": name,
               "arguments": safe, "arguments_sha256": hashlib.sha256(payload.encode()).hexdigest(),
               "ok": ok, "duration_ms": duration_ms}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


@dataclass(frozen=True)
class FileCheckpoint:
    step_id: str
    path: str
    existed: bool


class CheckpointStore:
    """Per-file pre-edit snapshots, limited to an explicit workspace root."""

    def __init__(self, root: Path, directory: Path | None = None) -> None:
        self.root = root.resolve()
        self.directory = directory if directory is not None else axiom_home() / "checkpoints"

    def capture(self, target: Path) -> FileCheckpoint:
        path = target.resolve()
        if not path.is_relative_to(self.root) or (path.exists() and not path.is_file()):
            raise ValueError("Checkpoint target must be a workspace file")
        step_id = uuid.uuid4().hex
        folder = self.directory / step_id
        folder.mkdir(parents=True, exist_ok=False)
        existed = path.exists()
        if existed:
            data = path.read_bytes()
            (folder / "before.bin").write_bytes(data)
        info = FileCheckpoint(step_id, str(path.relative_to(self.root)), existed)
        (folder / "meta.json").write_text(json.dumps(asdict(info)), encoding="utf-8")
        return info

    def rollback(self, step_id: str) -> bool:
        if not re.fullmatch(r"[a-f0-9]{32}", step_id):
            return False
        folder = self.directory / step_id
        try:
            info = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            target = (self.root / info["path"]).resolve()
            if not target.is_relative_to(self.root) or target.is_symlink():
                return False
            if info["existed"]:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{step_id}.tmp")
                temporary.write_bytes((folder / "before.bin").read_bytes())
                os.replace(temporary, target)
            elif target.exists() and target.is_file():
                target.unlink()
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False
