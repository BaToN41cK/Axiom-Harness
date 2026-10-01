"""Conversation export (W3.9): real messages/metrics to Markdown and JSON.

The export is built only from a stored :class:`~axiom.core.history.Conversation`
— every heading, message body and metadata is actual recorded data, never a
placeholder. Markdown is the portable format; PDF is produced by the desktop's
browser print from the same Markdown.
"""
from __future__ import annotations

import time
from typing import Any

from axiom.core.history import Conversation

_ROLE_LABEL = {
    "user": "Пользователь",
    "assistant": "Ассистент",
    "system": "Система",
    "tool": "Инструмент",
}


def export_conversation_json(conversation: Conversation) -> dict[str, Any]:
    """A machine-readable export: metadata + every message (real content)."""
    return {
        "id": conversation.id,
        "title": conversation.title,
        "model": conversation.model,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "pinned": conversation.pinned,
        "folder": conversation.folder,
        "message_count": len(conversation.messages),
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "thinking": message.thinking,
                "name": message.name,
                "created_at": message.created_at,
                "artifact_count": len(message.artifacts),
                "image_count": len(message.images),
            }
            for message in conversation.messages
        ],
    }


def _ts(value: float | None) -> str:
    if not value:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def export_conversation_markdown(conversation: Conversation) -> str:
    """A readable Markdown export with a metadata header and full messages."""
    lines = [
        f"# {conversation.title}",
        "",
        "| | |",
        "|---|---|",
        f"| Модель | {conversation.model or '—'} |",
        f"| Сообщений | {len(conversation.messages)} |",
        f"| Создан | {_ts(conversation.created_at)} |",
        f"| Обновлён | {_ts(conversation.updated_at)} |",
        "",
        "---",
        "",
    ]
    for message in conversation.messages:
        label = _ROLE_LABEL.get(message.role, message.role)
        if message.role == "tool" and message.name:
            label = f"Инструмент · {message.name}"
        lines.append(f"## {label}")
        if message.created_at:
            lines.append(f"<small>{_ts(message.created_at)}</small>")
        lines.append("")
        if message.content.strip():
            lines.append(message.content.strip())
            lines.append("")
        if message.thinking and message.thinking.strip():
            lines.append("<details><summary>Рассуждение</summary>")
            lines.append("")
            lines.append(message.thinking.strip())
            lines.append("")
            lines.append("</details>")
            lines.append("")
        if message.artifacts:
            lines.append(f"<small>Вложения-артефакты: {len(message.artifacts)}</small>")
            lines.append("")
        if message.images:
            lines.append(f"<small>Изображения: {len(message.images)}</small>")
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_conversation(conversation: Conversation) -> dict[str, Any]:
    """Both forms in one call, for the bridge."""
    return {
        "markdown": export_conversation_markdown(conversation),
        "json": export_conversation_json(conversation),
    }
