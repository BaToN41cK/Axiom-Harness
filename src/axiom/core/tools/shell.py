"""Persistent interactive shell session for the GUI terminal panel.

One long-lived process per session (``cmd``/``powershell`` on Windows, ``sh``
elsewhere) with real pipes: ``cd`` and environment changes survive between
writes, background jobs keep running — the opposite of the one-shot
``run_command`` tool. Output is pumped by a reader thread into a bounded
buffer; the frontend polls ``read()`` and renders whatever is new.

This is NOT a PTY (no TTY negotiation, no colors from TTY-aware tools) — it is
the honest portable subset: line-oriented stdin, streamed stdout+stderr.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

#: Cap the retained transcript so a runaway process cannot eat memory.
MAX_BUFFER_CHARS = 512_000


def default_shell_argv() -> list[str]:
    if os.name == "nt":
        override = os.environ.get("AXIOM_SHELL")
        if override:
            return override.split()
        # /Q: no echo — the GUI renders typed lines itself.
        return [os.environ.get("COMSPEC", "cmd.exe"), "/Q"]
    override = os.environ.get("AXIOM_SHELL")
    if override:
        return override.split()
    return [os.environ.get("SHELL", "/bin/sh")]


class ShellSession:
    """A single interactive shell process with a polled output buffer."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root
        self._proc: subprocess.Popen[str] | None = None
        self._buffer: list[str] = []
        self._size = 0
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None

    # ------------------------------------------------------------- lifecycle

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """Spawn the shell (idempotent: a live session is returned as-is)."""
        if self.running:
            return
        argv = default_shell_argv()
        self._proc = subprocess.Popen(
            argv,
            cwd=str(self._root) if self._root else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW
            if os.name == "nt" else 0,
        )
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        # First prompt/banner lines arrive immediately — give them a moment.
        time.sleep(0.05)

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=3)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                pass
        with self._lock:
            self._buffer.clear()
            self._size = 0

    # ------------------------------------------------------------------- I/O

    def write(self, line: str) -> bool:
        """Send one command line; ``False`` when the session is dead."""
        proc = self._proc
        if proc is None or proc.poll() is not None or proc.stdin is None:
            return False
        try:
            proc.stdin.write(line.rstrip("\n") + "\n")
            proc.stdin.flush()
        except (OSError, ValueError):
            return False
        return True

    def read(self) -> str:
        """Drain everything buffered since the previous ``read()`` call.

        The whole transcript is returned (the frontend keeps its own view);
        callers that want "new only" should track offsets themselves — GUI
        polls at ~4Hz on a bounded buffer, so the volume is trivial.
        """
        with self._lock:
            return "".join(self._buffer)

    def _pump(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for chunk in proc.stdout:
            with self._lock:
                self._buffer.append(chunk)
                self._size += len(chunk)
                while self._size > MAX_BUFFER_CHARS and self._buffer:
                    self._size -= len(self._buffer[0])
                    self._buffer.pop(0)
