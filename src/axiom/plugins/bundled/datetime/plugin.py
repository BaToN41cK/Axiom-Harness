"""AXIOM built-in plugin: current time, time zones and date arithmetic."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult

WEEKDAYS = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")


def _zone(name: str):
    if not name or name in {"local", "utc", "gmt", "z"}:
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return None


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if value.lower() in {"today", "сегодня", "now", "сейчас"}:
        return datetime.now().astimezone().date()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


TOOLS = [
    ToolDefinition(
        name="current_time",
        description=(
            "Get the current date, time, weekday and unix timestamp. "
            "Optionally pass an IANA time zone name like 'Europe/Moscow' or "
            "'Asia/Tokyo' to get the local time there."
        ),
        parameters={
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA time zone name (e.g. 'Europe/Moscow'), 'utc' or leave empty for local time.",
                },
            },
            "required": [],
        },
        permission=ToolPermission.ALWAYS,
        max_output=800,
    ),
    ToolDefinition(
        name="date_diff",
        description=(
            "Compute the number of days between two dates (ISO format YYYY-MM-DD, "
            "or 'today'). Positive result means 'b' is after 'a'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "Start date, ISO YYYY-MM-DD or 'today'."},
                "b": {"type": "string", "description": "End date, ISO YYYY-MM-DD or 'today'."},
            },
            "required": ["a", "b"],
        },
        permission=ToolPermission.ALWAYS,
        max_output=400,
    ),
]


async def current_time(timezone: str = "") -> ToolResult:
    zone = _zone((timezone or "").strip())
    try:
        now = datetime.now(zone) if zone is not None else datetime.now().astimezone()
        local_now = datetime.now().astimezone()
        tz_name = zone.key if zone is not None else "local"
    except Exception as exc:
        return ToolResult(name="current_time", ok=False, error=str(exc))
    utc_now = datetime.now(UTC)
    weekday = WEEKDAYS[now.weekday()]
    lines = [
        f"Date: {now:%Y-%m-%d} ({weekday})",
        f"Time: {now:%H:%M:%S}",
        f"Zone: {tz_name} (UTC offset {now:%z})",
        f"Unix time: {int(utc_now.timestamp())}",
    ]
    if zone is not None:
        lines.append(f"Local time here: {local_now:%Y-%m-%d %H:%M:%S}")
    return ToolResult(name="current_time", ok=True, content="\n".join(lines))


async def date_diff(a: str, b: str) -> ToolResult:
    start = _parse_date(a)
    end = _parse_date(b)
    if start is None or end is None:
        return ToolResult(
            name="date_diff",
            ok=False,
            error="dates must be ISO YYYY-MM-DD or 'today'",
        )
    days = (end - start).days
    return ToolResult(
        name="date_diff",
        ok=True,
        content=f"{start} → {end}: {days} day(s) ({end - start})",
    )


HANDLERS = {"current_time": current_time, "date_diff": date_diff}
