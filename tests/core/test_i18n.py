"""W3.8: localization catalogs and translation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from axiom.core.config import Config
from axiom.core.i18n import DEFAULT_LOCALE, Locale, locales, translate


def test_locales_list() -> None:
    assert locales() == ["en", "ru"]
    assert DEFAULT_LOCALE is Locale.EN


def test_translate_both_locales() -> None:
    assert translate("task.completed", Locale.EN) == "Completed"
    assert translate("task.completed", Locale.RU) == "Завершено"
    assert translate("task.completed", "ru") == "Завершено"
    assert translate("permission.deny", Locale.RU) == "Запретить"


def test_translate_falls_back_to_key() -> None:
    assert translate("does.not.exist", Locale.EN) == "does.not.exist"
    assert translate("does.not.exist", Locale.RU) == "does.not.exist"


def test_translate_formats_kwargs() -> None:
    # A key is not required to carry placeholders, but format() must be safe.
    assert translate("task.completed", Locale.EN, name="x") == "Completed"


def test_config_locale_is_validated() -> None:
    assert Config().locale == "en"
    assert Config(locale="ru").locale == "ru"
    with pytest.raises(ValidationError):
        Config(locale="fr")


def test_navigation_tabs_have_both_locales() -> None:
    # W3.8 slice: App side-tabs + topbar render from the core catalog.
    assert translate("ui.tabs.files", "en") == "Files"
    assert translate("ui.tabs.files", "ru") == "Файлы"
    assert translate("ui.tabs.terminal", "ru") == "Терминал"
    assert translate("ui.tabs.tasks", "ru") == "Задачи"
    assert translate("ui.tabs.documents", "ru") == "Документы"
    assert translate("ui.topbar.no_model", "en") == "no model selected"
    assert translate("ui.topbar.no_model", "ru") == "модель не выбрана"
    assert translate("ui.topbar.tools_on", "ru") == "Tools включены"
    assert translate("ui.topbar.tools_off", "ru") == "Только текст"
    assert translate("ui.panel.resize", "en") == "Resize panel"
    assert translate("ui.sidebar.toggle", "ru") == "Панель показать, скрыть L (Ctrl+B)"


def test_frontend_snapshot_matches_core_catalog() -> None:
    # The Desktop `FALLBACK_STRINGS` snapshot must stay identical to the core
    # catalog for this slice — no drift between the two render paths.
    from pathlib import Path

    from axiom.core.i18n import TRANSLATIONS

    ts_path = Path(__file__).resolve().parents[2] / "desktop" / "src" / "lib" / "i18n.ts"
    text = ts_path.read_text(encoding="utf-8")
    for key, entry in TRANSLATIONS.items():
        if not key.startswith("ui."):
            continue
        assert entry.get("en"), f"missing en for {key}"
        assert entry.get("ru"), f"missing ru for {key}"
        assert f'"{key}"' in text, f"frontend snapshot misses {key}"
        assert entry["en"] in text, f"frontend snapshot drifts on {key} (en)"
        assert entry["ru"] in text, f"frontend snapshot drifts on {key} (ru)"
