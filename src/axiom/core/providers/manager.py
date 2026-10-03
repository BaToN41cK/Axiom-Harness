"""ProviderManager: ключи, статусы, discovery. Без .env вручную."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from axiom.core.config import axiom_home
from axiom.core.providers.anthropic import AnthropicProvider
from axiom.core.providers.base import ModelProfile, Provider, ProviderStatus
from axiom.core.providers.known import KNOWN_PROVIDERS, find_known
from axiom.core.providers.ollama_provider import OllamaProvider
from axiom.core.providers.openai_compat import OpenAICompatibleProvider
from axiom.core.secrets import SecretsError, protect, secure_file, unprotect


@dataclass
class ProviderConfig:
    id: str
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True
    status: str = "not_configured"

class ProviderManager:
    def __init__(self) -> None:
        self._configs: dict[str, ProviderConfig] = {}
        self._providers: dict[str, Provider] = {}
        self._load()

    def _path(self):
        return axiom_home() / "providers.json"

    def _load(self) -> None:
        try:
            raw = json.loads(self._path().read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for pid, item in raw.items():
                    if isinstance(item, dict):
                        try:
                            key = unprotect(str(item.get("api_key") or ""))
                        except SecretsError:
                            # Corrupt/foreign blob: treat as missing, user re-enters.
                            key = ""
                        self._configs[str(pid)] = ProviderConfig(
                            id=str(pid), api_key=key,
                            base_url=str(item.get("base_url") or ""),
                            enabled=bool(item.get("enabled", True)),
                            status=str(item.get("status") or "not_configured"))
        except Exception:
            pass

    def save(self) -> None:
        # Fail closed: protection runs before any byte hits the disk, so a
        # SecretsError aborts the whole save instead of writing plaintext.
        payload = {}
        for pid, cfg in self._configs.items():
            entry = vars(cfg).copy()
            entry["api_key"] = protect(cfg.api_key)
            payload[pid] = entry
        try:
            p = self._path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(p)
            secure_file(p)
        except OSError:
            pass

    def _env_key(self, pid: str) -> str:
        known = find_known(pid)
        if known:
            for env in known.api_key_env:
                if os.environ.get(env):
                    return os.environ[env]
        return ""

    def _base_url(self, pid: str) -> str:
        cfg = self._configs.get(pid)
        if cfg and cfg.base_url:
            return cfg.base_url
        known = find_known(pid)
        if known:
            return known.base_url
        return ""

    def set_provider(self, pid: str, *, api_key: str | None = None,
                     base_url: str | None = None, enabled: bool | None = None) -> ProviderConfig:
        cfg = self._configs.get(pid) or ProviderConfig(id=pid)
        if api_key is not None:
            cfg.api_key = api_key
        if base_url is not None:
            cfg.base_url = base_url
        if enabled is not None:
            cfg.enabled = enabled
        self._configs[pid] = cfg
        self._providers.pop(pid, None)
        self.save()
        return cfg

    def set_key(self, pid: str, api_key: str) -> ProviderConfig:
        """Store a provider API key locally (never logged, never shown back)."""
        return self.set_provider(pid, api_key=(api_key or "").strip())

    def has_key(self, pid: str) -> bool:
        """Whether a real key is known for this provider (config or env)."""
        if pid == "ollama":
            return True
        cfg = self._configs.get(pid)
        return bool((cfg and cfg.api_key) or self._env_key(pid))

    async def model_rows(self, pid: str) -> list[dict]:
        """Discovered provider models as UI rows (real capabilities only)."""
        provider = self.get_provider(pid)
        models = await provider.list_models()
        rows: list[dict] = []
        for model in models:
            caps = [
                name
                for name in ("coding", "reasoning", "tool_calling", "long_context", "vision")
                if getattr(model, name, False)
            ]
            rows.append({
                "id": f"{pid}/{model.id}",
                "model": model.id,
                "provider_id": pid,
                "label": model.label(),
                "capabilities": caps,
                "context_length": model.context_length,
            })
        return rows

    def get_provider(self, pid: str) -> Provider:
        if pid in self._providers:
            return self._providers[pid]
        key = (self._configs.get(pid).api_key if pid in self._configs else "") or self._env_key(pid)
        url = self._base_url(pid)
        if pid == "ollama":
            prov: Provider = OllamaProvider(url or "http://127.0.0.1:11434")
        elif pid == "anthropic":
            prov = AnthropicProvider(key, base_url=url or "https://api.anthropic.com")
        else:
            known = find_known(pid)
            prov = OpenAICompatibleProvider(
                pid, known.label if known else pid,
                url or ("" if pid == "openai_compatible" else "https://api.openai.com/v1"),
                key,
            )
        self._providers[pid] = prov
        return prov

    def configured_ids(self) -> list[str]:
        out = []
        for known in KNOWN_PROVIDERS:
            cfg = self._configs.get(known.id)
            if (cfg and cfg.api_key) or self._env_key(known.id) or known.id == "ollama":
                out.append(known.id)
        for pid in self._configs:
            if pid not in out:
                out.append(pid)
        return out

    def providers(self) -> list[Provider]:
        return [self.get_provider(pid) for pid in self.configured_ids()]

    async def test_provider(self, pid: str) -> str:
        prov = self.get_provider(pid)
        try:
            status = await prov.authenticate()
        except Exception:
            status = ProviderStatus.ERROR
        cfg = self._configs.get(pid) or ProviderConfig(id=pid)
        cfg.status = status.value
        self._configs[pid] = cfg
        self.save()
        return status.value

    async def discover_models(self, pid: str | None = None) -> list[ModelProfile]:
        ids = [pid] if pid else self.configured_ids()
        out: list[ModelProfile] = []
        for i in ids:
            try:
                out.extend(await self.get_provider(i).list_models())
            except Exception:
                continue
        return out

    def status_rows(self) -> list[dict]:
        """Строки для UI «Providers» (п.2): честные статусы без сети."""
        rows: list[dict] = []
        seen: set[str] = set()
        for known in KNOWN_PROVIDERS:
            cfg = self._configs.get(known.id)
            configured = bool(
                (cfg and cfg.api_key) or self._env_key(known.id) or known.id == "ollama"
            )
            if not configured:
                status = "not_configured"
            elif cfg and cfg.status in ("connected", "error"):
                status = cfg.status
            elif known.id == "ollama":
                status = cfg.status if cfg and cfg.status != "not_configured" else "unknown"
            else:
                status = "configured"
            rows.append({
                "id": known.id,
                "label": known.label,
                "base_url": self._base_url(known.id) or known.base_url,
                "configured": configured,
                "status": status,
            })
            seen.add(known.id)
        for pid, cfg in self._configs.items():
            if pid in seen:
                continue
            rows.append({
                "id": pid,
                "label": pid,
                "base_url": cfg.base_url,
                "configured": bool(cfg.api_key),
                "status": cfg.status if cfg.api_key else "not_configured",
            })
        return rows
