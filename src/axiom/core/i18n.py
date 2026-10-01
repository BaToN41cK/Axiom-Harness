"""Localization primitives (W3.8).

A small, deterministic catalog of the strings the *core* emits — task states,
permission outcomes and autonomy labels — so both frontends can render the same
surface in English or Russian. ``translate`` falls back to the key itself for
anything not yet catalogued, so an untranslated string degrades to an identifier
instead of crashing or silently switching language.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class Locale(str, Enum):
    EN = "en"
    RU = "ru"


DEFAULT_LOCALE = Locale.EN

TRANSLATIONS: dict[str, dict[str, str]] = {
    # Task states (W4.1)
    "task.pending": {"en": "Pending", "ru": "Ожидает"},
    "task.analyzing": {"en": "Analyzing", "ru": "Анализ"},
    "task.planning": {"en": "Planning", "ru": "Планирование"},
    "task.executing": {"en": "Executing", "ru": "Выполнение"},
    "task.verifying": {"en": "Verifying", "ru": "Проверка"},
    "task.completed": {"en": "Completed", "ru": "Завершено"},
    "task.failed": {"en": "Failed", "ru": "Ошибка"},
    "task.cancelled": {"en": "Cancelled", "ru": "Отменено"},
    "task.waiting_for_user": {"en": "Waiting for user", "ru": "Ожидание пользователя"},
    # Permission outcomes (W2.4)
    "permission.allow_once": {"en": "Allow once", "ru": "Разрешить один раз"},
    "permission.allow_always": {"en": "Always allow", "ru": "Всегда разрешать"},
    "permission.deny": {"en": "Deny", "ru": "Запретить"},
    # Autonomy presets (W4.9)
    "autonomy.plan": {"en": "Plan", "ru": "План"},
    "autonomy.edit": {"en": "Edit", "ru": "Правка"},
    "autonomy.auto": {"en": "Auto", "ru": "Авто"},
    "autonomy.full": {"en": "Full", "ru": "Полный"},
}


def locales() -> list[str]:
    return [locale.value for locale in Locale]


def translate(key: str, locale: Locale | str = DEFAULT_LOCALE, **kwargs: Any) -> str:
    """Return the localized string for ``key``, falling back to the key itself."""
    locale_value = locale.value if isinstance(locale, Locale) else str(locale)
    entry = TRANSLATIONS.get(key)
    template = key
    if entry is not None:
        template = entry.get(locale_value) or entry.get("en") or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


__all__ = ["DEFAULT_LOCALE", "TRANSLATIONS", "Locale", "locales", "translate"]
