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
