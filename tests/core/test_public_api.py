"""Public API contract of the core (§1.4 of TODO.md).

These tests pin the signatures frontends and scripts rely on. Breaking them
must fail CI — that is the whole point of the compatibility test.
"""

from __future__ import annotations

import inspect

from axiom.core.chat import ChatSession, StartupReport
from axiom.core.config import Config
from axiom.core.history import HistoryStore
from axiom.shared import theme

# ---------------------------------------------------------------- ChatSession

SESSION_METHODS = {
    "startup": ("ollama_available", "version", "models", "selected"),
    "send": ("text",),
    "cancel": (),
    "switch_model": ("name",),
    "new_conversation": (),
    "load_conversation": ("conversation_id",),
    "refresh_models": (),
    "reconnect": ("ollama_url",),
}


def test_chat_session_public_api_is_stable() -> None:
    for method, _ in SESSION_METHODS.items():
        assert callable(getattr(ChatSession, method)), f"missing ChatSession.{method}"
    # startup() must be async and parameterless, send() an async generator.
    assert inspect.iscoroutinefunction(ChatSession.startup)
    assert inspect.isasyncgenfunction(ChatSession.send)
    assert "self" in inspect.signature(ChatSession.switch_model).parameters
    assert inspect.signature(ChatSession.switch_model).parameters["name"].kind is not inspect.Parameter.VAR_KEYWORD


def test_startup_report_fields_are_stable() -> None:
    fields = getattr(StartupReport, "__dataclass_fields__", None)
    assert fields is not None, "StartupReport must remain a dataclass"
    for name in SESSION_METHODS["startup"]:
        assert name in fields, f"StartupReport lost field {name!r}"


# -------------------------------------------------------------------- Config


def test_config_load_and_save_round_trip(tmp_path) -> None:
    config = Config()
    config.temperature = 0.5
    config.system_prompt = "be terse"
    config.search_timeout = 42.0
    config.history_limit = 7
    config.accent = "teal"
    config.panel_hover = False
    config.save()
    reloaded = Config.load()
    assert reloaded.temperature == 0.5
    assert reloaded.system_prompt == "be terse"
    assert reloaded.search_timeout == 42.0
    assert reloaded.history_limit == 7
    assert reloaded.accent == "teal"
    assert reloaded.panel_hover is False


def test_accent_theme_payloads_cover_every_configured_preset() -> None:
    for name, colors in theme.ACCENT_PRESETS.items():
        payload = theme.theme_colors(name)
        assert payload["accent"] == colors["accent"]
        assert payload["variables"]["accent-deep"] == colors["fill"]


def test_config_script_entry_points_exist() -> None:
    """Scripts are documented to use Config.load() / path()."""
    assert callable(Config.load)
    assert callable(Config.save)
    assert Config.path().name == "config.json"


# ----------------------------------------------------------------- HistoryStore


def test_history_store_script_triad(tmp_path) -> None:
    """The documented script trio: list / show / delete."""
    store = HistoryStore(directory=tmp_path / "history")
    conv = None
    from axiom.core.history import Conversation

    conv = Conversation(title="s1")
    store.save(conv)
    listed = store.list()
    assert [c.id for c in listed] == [conv.id]
    raw = store.show(conv.id)
    assert raw is not None and conv.id in raw
    assert store.show("no-such-id") is None
    assert store.delete(conv.id) is True
    assert store.list() == []
