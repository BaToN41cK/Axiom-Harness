"""AXIOM built-in plugin: text statistics, transforms and encodings."""

from __future__ import annotations

import base64
import binascii
import html
import re
import unicodedata
import urllib.parse

from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult

MAX_TEXT_CHARS = 20000
MAX_ENCODE_CHARS = 8000


def _slug(text: str) -> str:
    value = unicodedata.normalize("NFKD", text)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or ""


TOOLS = [
    ToolDefinition(
        name="text_stats",
        description="Count characters, words, lines and bytes of a piece of text.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to analyze."},
            },
            "required": ["text"],
        },
        permission=ToolPermission.ALWAYS,
        max_output=400,
    ),
    ToolDefinition(
        name="text_transform",
        description=(
            "Apply a transformation to text. Operations: lower, upper, title, "
            "capitalize, slug (url-friendly), reverse, strip, collapse (collapse "
            "whitespace)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Input text."},
                "operation": {
                    "type": "string",
                    "description": "One of: lower, upper, title, capitalize, slug, reverse, strip, collapse.",
                },
            },
            "required": ["text", "operation"],
        },
        permission=ToolPermission.ALWAYS,
        max_output=MAX_TEXT_CHARS,
    ),
    ToolDefinition(
        name="encode_text",
        description=(
            "Encode or decode text. Codecs: base64, base64url, hex, url, html. "
            "Prefix with 'decode:' to decode instead, e.g. 'decode:base64' or "
            "'decode:url'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to encode (or encoded text to decode)."},
                "codec": {
                    "type": "string",
                    "description": (
                        "Codec name, optionally prefixed with 'decode:'. "
                        "e.g. 'base64', 'hex', 'url', 'html', 'decode:base64'."
                    ),
                },
            },
            "required": ["text", "codec"],
        },
        permission=ToolPermission.ALWAYS,
        max_output=MAX_ENCODE_CHARS * 2,
    ),
]


async def text_stats(text: str) -> ToolResult:
    if not text:
        return ToolResult(name="text_stats", ok=False, error="text is required")
    words = len(re.findall(r"\S+", text))
    lines = text.count("\n") + 1 if text else 0
    return ToolResult(
        name="text_stats",
        ok=True,
        content=(
            f"Characters: {len(text)}\n"
            f"Words: {words}\n"
            f"Lines: {lines}\n"
            f"Bytes (UTF-8): {len(text.encode('utf-8'))}"
        ),
    )


async def text_transform(text: str, operation: str) -> ToolResult:
    if not text:
        return ToolResult(name="text_transform", ok=False, error="text is required")
    operation = (operation or "").strip().lower()
    transforms = {
        "lower": lambda value: value.lower(),
        "upper": lambda value: value.upper(),
        "title": lambda value: value.title(),
        "capitalize": lambda value: value.capitalize(),
        "slug": _slug,
        "reverse": lambda value: value[::-1],
        "strip": lambda value: value.strip(),
        "collapse": lambda value: re.sub(r"\s+", " ", value).strip(),
    }
    if operation not in transforms:
        allowed = ", ".join(sorted(transforms))
        return ToolResult(name="text_transform", ok=False, error=f"unknown operation; use one of: {allowed}")
    return ToolResult(name="text_transform", ok=True, content=transforms[operation](text))


async def encode_text(text: str, codec: str) -> ToolResult:
    if text is None or not isinstance(text, str):
        return ToolResult(name="encode_text", ok=False, error="text is required")
    if len(text) > MAX_ENCODE_CHARS:
        return ToolResult(
            name="encode_text",
            ok=False,
            error=f"text is too long (max {MAX_ENCODE_CHARS} chars)",
        )
    codec = (codec or "").strip()
    decode = codec.startswith("decode:")
    codec = codec.split(":", 1)[1] if ":" in codec else codec
    try:
        if decode:
            if codec == "base64":
                output = base64.b64decode(text, validate=True).decode("utf-8")
            elif codec == "base64url":
                output = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("utf-8")
            elif codec == "hex":
                output = bytes.fromhex(text).decode("utf-8")
            elif codec == "url":
                output = urllib.parse.unquote(text)
            elif codec == "html":
                output = html.unescape(text)
            else:
                return ToolResult(name="encode_text", ok=False, error=f"unknown codec: {codec}")
        else:
            if codec == "base64":
                output = base64.b64encode(text.encode("utf-8")).decode("ascii")
            elif codec == "base64url":
                output = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")
            elif codec == "hex":
                output = text.encode("utf-8").hex()
            elif codec == "url":
                output = urllib.parse.quote(text)
            elif codec == "html":
                output = html.escape(text)
            else:
                return ToolResult(name="encode_text", ok=False, error=f"unknown codec: {codec}")
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        return ToolResult(name="encode_text", ok=False, error=f"cannot decode: {exc}")
    return ToolResult(name="encode_text", ok=True, content=output)


HANDLERS = {"text_stats": text_stats, "text_transform": text_transform, "encode_text": encode_text}
