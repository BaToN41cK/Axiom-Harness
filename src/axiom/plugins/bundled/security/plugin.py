"""AXIOM built-in plugin: UUIDs, checksums and strong passwords (secrets-based)."""

from __future__ import annotations

import hashlib
import secrets
import string
import uuid

from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult

MAX_HASH_CHARS = 20000


TOOLS = [
    ToolDefinition(
        name="generate_uuid",
        description="Generate one or more random UUID v4 identifiers.",
        parameters={
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "How many UUIDs to generate (1-10).",
                },
            },
            "required": [],
        },
        permission=ToolPermission.ALWAYS,
        max_output=600,
    ),
    ToolDefinition(
        name="hash_text",
        description=(
            "Compute a checksum of a piece of text. Algorithms: md5, sha1, "
            "sha256, sha512 (default sha256)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to hash."},
                "algo": {"type": "string", "description": "One of: md5, sha1, sha256, sha512."},
            },
            "required": ["text"],
        },
        permission=ToolPermission.ALWAYS,
        max_output=400,
    ),
    ToolDefinition(
        name="generate_password",
        description=(
            "Generate a cryptographically strong random password using the "
            "secrets module. Optional symbols and custom length (8-128)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "length": {"type": "integer", "description": "Password length (8-128, default 16)."},
                "symbols": {"type": "boolean", "description": "Include punctuation symbols (default true)."},
            },
            "required": [],
        },
        permission=ToolPermission.ALWAYS,
        max_output=200,
    ),
]


async def generate_uuid(count: int = 1) -> ToolResult:
    try:
        count = int(count) if count is not None else 1
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(count, 10))
    values = [str(uuid.uuid4()) for _ in range(count)]
    return ToolResult(name="generate_uuid", ok=True, content="\n".join(values))


async def hash_text(text: str, algo: str = "sha256") -> ToolResult:
    if not text:
        return ToolResult(name="hash_text", ok=False, error="text is required")
    if len(text) > MAX_HASH_CHARS:
        return ToolResult(name="hash_text", ok=False, error=f"text is too long (max {MAX_HASH_CHARS} chars)")
    algo = (algo or "sha256").strip().lower()
    algorithms = {
        "md5": hashlib.md5,
        "sha1": hashlib.sha1,
        "sha256": hashlib.sha256,
        "sha512": hashlib.sha512,
    }
    if algo not in algorithms:
        allowed = ", ".join(sorted(algorithms))
        return ToolResult(name="hash_text", ok=False, error=f"unknown algorithm; use one of: {allowed}")
    digest = algorithms[algo](text.encode("utf-8")).hexdigest()
    return ToolResult(name="hash_text", ok=True, content=digest)


async def generate_password(length: int = 16, symbols: bool = True) -> ToolResult:
    try:
        length = int(length) if length is not None else 16
    except (TypeError, ValueError):
        length = 16
    length = max(8, min(length, 128))
    alphabet = string.ascii_letters + string.digits
    if symbols is not False:
        alphabet += "!@#$%^&*()-_=+[]{}"
    # Guarantee at least one letter and one digit for policies that require it.
    password = [secrets.choice(string.ascii_letters), secrets.choice(string.digits)]
    password += [secrets.choice(alphabet) for _ in range(length - 2)]
    secrets.SystemRandom().shuffle(password)
    return ToolResult(name="generate_password", ok=True, content="".join(password))


HANDLERS = {"generate_uuid": generate_uuid, "hash_text": hash_text, "generate_password": generate_password}
