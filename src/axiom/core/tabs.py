"""Chat tabs — project/model/context-isolated conversation slots (W3.3).

A tab is a lightweight descriptor of one open chat: the conversation it points
at, the workspace (project) it belongs to, and the model it last used. The
:class:`~axiom.core.chat.ChatSession` stays the single runtime core — tabs never
duplicate chat/stream/tool logic. Activating a tab reuses the existing
``set_workspace``/``clear_workspace``/``load_conversation``/``switch_model``
paths, so each tab keeps its own project, model and context (history) while
background tasks keep running independently in the task registry.

The registry persists to ``<axiom_home>/tabs.json`` so open tabs survive a
restart. A corrupt file never crashes the app — it is ignored and rebuilt.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from axiom.core.config import axiom_home
from axiom.core.logging import get_logger

_LOG = get_logger("tabs")

#: Hard cap on simultaneously open tabs. Keeps the registry (and the UI strip)
#: bounded; opening past the cap is rejected rather than silently dropping one.
MAX_TABS = 24

#: Sentinel distinguishing "leave unchanged" from an explicit ``None`` (clear).
_UNSET = object()


class ChatTab(BaseModel):
    """One open chat tab (W3.3).

    ``conversation_id`` is ``None`` until the tab's chat is first saved to
    history; ``workspace`` is ``None`` for a Global Chat tab (no project).
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "New chat"
    conversation_id: str | None = None
    #: Absolute workspace path, or None for Global Chat (no project tools).
    workspace: str | None = None
    model: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()


class TabManager:
    """Ordered registry of open chat tabs with one active tab.

    Pure state + persistence only. The ChatSession orchestrates the real
    workspace/model/conversation switches when a tab is activated, so this
    class never imports or drives chat/stream logic.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (axiom_home() / "tabs.json")
        self._tabs: list[ChatTab] = []
        self._active_id: str | None = None
        self._load()

    # --------------------------------------------------------------- persistence

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _LOG.warning("Could not load tabs registry: %s", exc)
            return
        if not isinstance(raw, dict):
            return
        tabs: list[ChatTab] = []
        for item in raw.get("tabs", []) or []:
            if not isinstance(item, dict):
                continue
            try:
                tabs.append(ChatTab.model_validate(item))
            except Exception:  # one bad entry never discards the rest
                continue
        self._tabs = tabs[:MAX_TABS]
        active = raw.get("active_id")
        self._active_id = active if any(t.id == active for t in self._tabs) else None

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "tabs": [t.model_dump(mode="json") for t in self._tabs],
                "active_id": self._active_id,
            }
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            _LOG.warning("Could not save tabs registry: %s", exc)

    # ------------------------------------------------------------------- queries

    def list(self) -> list[ChatTab]:
        return list(self._tabs)

    def get(self, tab_id: str) -> ChatTab | None:
        return next((t for t in self._tabs if t.id == tab_id), None)

    @property
    def active_id(self) -> str | None:
        return self._active_id

    def active(self) -> ChatTab | None:
        return self.get(self._active_id) if self._active_id else None

    # -------------------------------------------------------------- mutations

    def open(self, *, title: str = "New chat", workspace: str | None = None,
             model: str | None = None, conversation_id: str | None = None,
             activate: bool = True) -> ChatTab:
        """Add a new tab. Raises ``ValueError`` past :data:`MAX_TABS`."""
        if len(self._tabs) >= MAX_TABS:
            raise ValueError(f"Too many open tabs (max {MAX_TABS})")
        tab = ChatTab(
            title=title.strip() or "New chat",
            workspace=workspace,
            model=model,
            conversation_id=conversation_id,
        )
        self._tabs.append(tab)
        if activate or self._active_id is None:
            self._active_id = tab.id
        self._save()
        return tab

    def close(self, tab_id: str) -> ChatTab | None:
        """Remove a tab; returns the next tab to activate (or None if empty).

        Closing the active tab moves activation to the neighbour on its right,
        then its left, mirroring how editors behave.
        """
        index = next((i for i, t in enumerate(self._tabs) if t.id == tab_id), None)
        if index is None:
            return self.active()
        self._tabs.pop(index)
        if self._active_id == tab_id:
            if not self._tabs:
                self._active_id = None
            else:
                nxt = self._tabs[index] if index < len(self._tabs) else self._tabs[-1]
                self._active_id = nxt.id
        self._save()
        return self.active()

    def activate(self, tab_id: str) -> ChatTab | None:
        tab = self.get(tab_id)
        if tab is None:
            return None
        self._active_id = tab_id
        tab.touch()
        self._save()
        return tab

    def update(self, tab_id: str, *, title: str | None = None,
               conversation_id: object = _UNSET, workspace: object = _UNSET,
               model: str | None = None) -> ChatTab | None:
        """Patch an existing tab's descriptor.

        ``workspace``/``conversation_id`` accept an explicit ``None`` to clear
        them (Global Chat / unsaved chat); omitting the argument leaves the
        field unchanged (the ``_UNSET`` sentinel).
        """
        tab = self.get(tab_id)
        if tab is None:
            return None
        if title is not None:
            tab.title = title.strip() or tab.title
        if conversation_id is not _UNSET:
            tab.conversation_id = conversation_id  # type: ignore[assignment]
        if workspace is not _UNSET:
            tab.workspace = workspace  # type: ignore[assignment]
        if model is not None:
            tab.model = model
        tab.touch()
        self._save()
        return tab

    def rows(self) -> list[dict]:
        """UI projection: ordered tab descriptors + which one is active."""
        return [
            {**t.model_dump(mode="json"), "active": t.id == self._active_id}
            for t in self._tabs
        ]
