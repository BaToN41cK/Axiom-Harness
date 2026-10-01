"""Structured event stream exchanged between the AXIOM core and frontends.

The core never touches a UI; it yields instances of these events and accepts
plain method calls. Every frontend (TUI / CLI / future GUI) consumes exactly
this vocabulary.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from axiom.core.state import GenerationState


class Event(BaseModel):
    """Base class for all AXIOM events."""

    type: str = "event"


class Message(BaseModel):
    """A chat message (role: user / assistant / system / tool)."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str = ""
    thinking: str | None = None
    name: str | None = None
    created_at: float | None = None
    #: Base64-encoded images attached to this message (Ollama vision models)
    images: list[str] = Field(default_factory=list)
    #: Validated structured artifacts attached to this message (W3.4). Stored as
    #: raw dicts so history persistence stays decoupled from artifact validation.
    artifacts: list[dict] = Field(default_factory=list)


class ReasoningChunk(BaseModel):
    """A delta of real model reasoning (only emitted when model provides it)."""

    type: Literal["reasoning"] = "reasoning"
    text: str


class ContentChunk(BaseModel):
    """A delta of the real model answer."""

    type: Literal["content"] = "content"
    text: str


class ToolCallEvent(BaseModel):
    """The model requested a tool execution."""

    type: Literal["tool_call"] = "tool_call"
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultEvent(BaseModel):
    """Result of a real tool execution."""

    type: Literal["tool_result"] = "tool_result"
    name: str
    ok: bool
    content: str
    error: str | None = None
    duration_ms: int = 0


class SourceItem(BaseModel):
    """One web search source."""

    index: int
    title: str
    url: str
    snippet: str = ""


class SearchResultEvent(BaseModel):
    """Structured results of a real web search."""

    type: Literal["search_result"] = "search_result"
    query: str
    sources: list[SourceItem] = Field(default_factory=list)


class StatusChange(BaseModel):
    """Generation state changed — a projection of the real backend state."""

    type: Literal["status"] = "status"
    state: GenerationState
    detail: str | None = None


class ErrorEvent(BaseModel):
    """A user-presentable error occurred."""

    type: Literal["error"] = "error"
    message: str
    kind: str = "error"
    hint: str | None = None


class Done(BaseModel):
    """Generation finished. Carries real metrics from the Ollama response."""

    type: Literal["done"] = "done"
    state: GenerationState
    duration_ms: int = 0
    tokens_out: int | None = None
    tokens_in: int | None = None
    tokens_per_second: float | None = None
    #: Real time to the first streamed token (measured by the agent).
    ttft_ms: int | None = None
    #: Real model load time reported by Ollama for this generation (ms).
    load_ms: int | None = None
    stop_reason: str | None = None


ChatEvent = (
    ReasoningChunk
    | ContentChunk
    | ToolCallEvent
    | ToolResultEvent
    | SearchResultEvent
    | StatusChange
    | ErrorEvent
    | Done
)
