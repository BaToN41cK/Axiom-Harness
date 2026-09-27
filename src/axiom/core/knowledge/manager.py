"""Knowledge manager — named collections, persisted in ``~/.axiom/knowledge.json``.

The manager owns the collection registry and the optional shared embedder;
it never duplicates store logic. A corrupt registry file never crashes the app.
"""

from __future__ import annotations

import json
from pathlib import Path

from axiom.core.config import axiom_home
from axiom.core.knowledge.store import Embedder, KnowledgeStore
from axiom.core.logging import get_logger

_LOG = get_logger("knowledge")


class KnowledgeManager:
    """Registry of knowledge collections plus the shared Ollama embedder."""

    def __init__(self, *, local_only: bool = False) -> None:
        self.local_only = local_only
        self._collections: dict[str, str] = {}  # name -> root path
        self._stores: dict[str, KnowledgeStore] = {}
        self.embed_model: str | None = None
        self._embedder: Embedder | None = None
        self._load()

    # ------------------------------------------------------------- registry

    def _path(self) -> Path:
        return axiom_home() / "knowledge.json"

    def _load(self) -> None:
        path = self._path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                collections = raw.get("collections")
                if isinstance(collections, dict):
                    self._collections = {
                        str(k): str(v) for k, v in collections.items()
                        if isinstance(k, str) and isinstance(v, str)
                    }
                model = raw.get("embed_model")
                self.embed_model = str(model) if isinstance(model, str) and model else None
        except (OSError, json.JSONDecodeError) as exc:
            _LOG.warning("Could not load knowledge registry: %s", exc)

    def _save(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        payload = {"collections": self._collections, "embed_model": self.embed_model}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ----------------------------------------------------------- collections

    def add(self, name: str, path: str) -> str | None:
        """Register a collection. Returns the error message or None on success."""
        root = Path(path).expanduser()
        if not root.exists():
            return f"Path does not exist: {path}"
        cleaned = name.strip() or root.name or "default"
        self._collections[cleaned] = str(root.resolve())
        self._save()
        return None

    def remove(self, name: str) -> bool:
        if name not in self._collections:
            return False
        store = self._stores.pop(name, None)
        if store is not None:
            store.close()
        del self._collections[name]
        self._save()
        return True

    def names(self) -> list[str]:
        return sorted(self._collections)

    def get(self, name: str) -> KnowledgeStore | None:
        if name not in self._collections:
            return None
        store = self._stores.get(name)
        if store is None:
            store = KnowledgeStore(name, self._collections[name])
            store._query_embedder = self._embedder
            self._stores[name] = store
        return store

    # ------------------------------------------------------------ embeddings

    def configure_embedder(self, base_url: str, model: str | None) -> None:
        """Wire the real Ollama embeddings endpoint (None disables it)."""
        if model and not self.local_only:
            self.embed_model = model
            self._embedder = Embedder(base_url, model)
        else:
            self.embed_model = None
            self._embedder = None
        for store in self._stores.values():
            store._query_embedder = self._embedder
        self._save()

    @property
    def embedder(self) -> Embedder | None:
        return self._embedder
