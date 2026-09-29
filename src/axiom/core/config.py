"""AXIOM configuration — loading, validation and persistence.

First run must work with zero manual setup: defaults point at a local Ollama
instance and the model is auto-discovered by :mod:`axiom.core.models`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


def axiom_home() -> Path:
    """Root of AXIOM's local data (``AXIOM_HOME`` overrides the default)."""
    override = os.environ.get("AXIOM_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".axiom"


class Config(BaseModel):
    """Persisted user configuration."""

    ollama_url: str = DEFAULT_OLLAMA_URL
    model: str | None = None
    #: None = automatic (follow model capability), True/False = explicit request,
    #: "low"/"medium"/"high"/"max" = explicit reasoning level (new Ollama API).
    think: bool | Literal["low", "medium", "high", "max"] | None = None
    #: How the agent picks reasoning depth when ``think`` is None:
    #: auto = per-request heuristic, fast/normal/deep = fixed level presets.
    thinking_mode: Literal["auto", "fast", "normal", "deep"] = "auto"
    #: How long Ollama keeps the model in memory (warm-up pays off then)
    keep_alive: str = "30m"
    #: Load the active model into memory in the background right after boot
    warmup_model: bool = True
    #: Real Ollama context window override (None = model default)
    num_ctx: int | None = Field(default=None, ge=512, le=131072)
    #: Real Ollama generation cap (None = model default)
    num_predict: int | None = Field(default=None, ge=16, le=131072)
    #: How many previous messages are sent back to the model
    context_messages: int = Field(default=20, ge=4, le=200)
    #: Maximum repair attempts after a failing task verification.
    max_retries: int = Field(default=3, ge=0, le=10)
    #: Enable the web-search capability (search still only runs when needed)
    web_search_enabled: bool = True
    #: Give the model real filesystem tools inside the workspace
    workspace_tools_enabled: bool = True
    #: Root directory the model may read/edit (None = launch directory)
    workspace_root: str | None = None
    #: AI access level: read_only < workspace < full (outside workspace too)
    access_mode: Literal["read_only", "workspace", "full"] = "workspace"
    #: Allow the model (and the terminal panel) to run shell commands
    terminal_enabled: bool = True
    #: How many search sources to keep / how many pages to actually read
    search_max_sources: int = Field(default=5, ge=1, le=10)
    search_read_sources: int = Field(default=3, ge=0, le=10)
    #: Per-request timeout for search engines and page reading (seconds)
    search_timeout: float = Field(default=20.0, gt=0.0, le=300.0)
    #: Search backend used by web search. ``auto`` keeps the resilient
    #: Brave → DuckDuckGo → SearXNG → Wikipedia chain; a specific id pins a
    #: single engine (useful when a network blocks part of the chain).
    search_provider: Literal["auto", "brave", "duckduckgo", "searxng", "wikipedia"] = "auto"
    #: Maximum number of stored conversations (oldest are pruned on save)
    history_limit: int = Field(default=100, ge=1, le=1000)
    #: Show real reasoning when the model provides it
    show_reasoning: bool = True
    #: Whether the reasoning block starts expanded
    reasoning_expanded: bool = False
    #: UI colour scheme; kept separate from the shared accent preset.
    theme: Literal[
        "obsidian", "light", "midnight", "terminal", "solarized", "graphite", "rosewood", "nord"
    ] = "obsidian"
    #: Accessible accent shared by Desktop and TUI.
    accent: Literal["garnet", "blue", "teal", "violet", "slate", "rose", "amber"] = "garnet"
    #: Highlight interactive panel/list rows while the pointer is over them.
    panel_hover: bool = True
    #: Subtle animations (spinners, splash, transitions)
    animations: bool = True
    #: Persist conversations between runs
    save_history: bool = True
    #: Optional generation parameters
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    system_prompt: str | None = None
    #: Global permission mode: ask, auto_approve_safe, auto_approve_all
    permission_mode: str = "auto_approve_safe"
    #: W4.9 derived autonomy preset (plan/edit/auto/full) composed from
    #: access_mode + permission_mode; informational, recomputed on demand.
    autonomy_mode: str = "auto"
    #: Optional Ollama embeddings model for the knowledge base (None = BM25 only)
    knowledge_embed_model: str | None = None
    #: Refuse covered external network paths (search, page fetch, embeddings).
    local_only: bool = False

    # ---------------------------------------------------------------- hooks
    #: Master switch for lifecycle hooks (W4.10). Disabling restores the
    #: previous behaviour exactly: no hook command is ever started.
    hooks_enabled: bool = True
    #: Declared hooks. Each entry is {"id", "event", "command", "tools",
    #: "paths", "timeout", "enabled"}; an entry with only {"id", "enabled"}
    #: toggles a builtin/global/project definition in place.
    hooks: list[dict] = Field(default_factory=list)
    #: Highest command risk tier a hook may run (W4.9 tiers). HIGH/CRITICAL
    #: hook commands are refused before execution at the default MEDIUM.
    hooks_max_risk: Literal["SAFE", "LOW", "MEDIUM", "HIGH"] = "MEDIUM"

    # ------------------------------------------------------- harness routing
    #: Enable the Model Router (п.16): pick provider/model per task type
    router_enabled: bool = True
    #: performance | balanced | economy (п.19 cost-aware routing)
    router_budget: Literal["performance", "balanced", "economy"] = "balanced"
    #: Primary route target {"provider_id": "...", "model": "..."} or None
    router_primary: dict | None = None
    #: Fallback chain [{"provider_id": "...", "model": "..."}, ...] (п.17)
    router_fallbacks: list[dict] = Field(default_factory=list)
    #: External MCP servers [{"name": "...", "command": ["npx", ...]}] (п.15)
    mcp_servers: list[dict] = Field(default_factory=list)

    # ------------------------------------------------------------ workspace UI
    #: UI density of the desktop workspace
    density: Literal["compact", "comfortable", "spacious"] = "comfortable"
    #: Base UI font size in pixels
    font_size: int = Field(default=14, ge=12, le=18)
    #: Sidebar visibility/width are part of the persisted workspace state
    sidebar_open: bool = True
    sidebar_width: int = Field(default=268, ge=200, le=420)
    #: Render assistant answers as markdown
    render_markdown: bool = True
    #: Keep the chat pinned to the newest message while streaming
    auto_scroll: bool = True
    #: Show real per-answer metrics (tokens, tok/s, duration)
    show_metrics: bool = True
    #: Show the context panel counters in the composer strip
    show_context: bool = True

    @classmethod
    def path(cls) -> Path:
        return axiom_home() / "config.json"

    @classmethod
    def load(cls) -> Config:
        """Load configuration, falling back to defaults on any problem.

        A corrupt or unreadable config file must never crash the application.
        """
        config_path = cls.path()
        if not config_path.exists():
            config = cls()
            config.save()
            return config
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except ValidationError:
            # keep only the fields that are still valid, ignore the rest
            valid: dict[str, object] = {}
            for name in cls.model_fields:
                if name in raw:
                    try:
                        cls.model_validate({name: raw[name]})
                    except ValidationError:
                        continue
                    valid[name] = raw[name]
            try:
                return cls.model_validate(valid)
            except ValidationError:
                return cls()

    def save(self) -> None:
        """Persist configuration atomically."""
        config_path = self.path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = config_path.with_suffix(".json.tmp")
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(config_path)
