"""AXIOM — Open Local AI Coding Workspace & Agent Harness.

A local-first AI coding workspace and agent harness powered by Ollama, with a
Textual TUI and a Tauri/React desktop client sharing the same core.

Public API surface. Frontends should depend only on what is exported here
and on :mod:`axiom.core` / :mod:`axiom.shared` modules.
"""

from axiom.core.agents import (
    REPORT_SECTIONS,
    AgentProfile,
    AgentRegistry,
    SubagentBudget,
    compact_report,
)
from axiom.core.bus import EventBus
from axiom.core.cancellation import CancelToken
from axiom.core.chat import ChatSession
from axiom.core.config import Config
from axiom.core.context_engine import CompactionState, ContextEngine, StructuredCompaction
from axiom.core.errors import (
    AxiomError,
    GenerationCancelledError,
    InvalidResponseError,
    ModelNotFoundError,
    OllamaUnavailableError,
    SearchUnavailableError,
)
from axiom.core.events import (
    ChatEvent,
    ContentChunk,
    Done,
    ErrorEvent,
    Message,
    ReasoningChunk,
    SearchResultEvent,
    StatusChange,
    ToolCallEvent,
    ToolResultEvent,
)
from axiom.core.hooks import (
    HOOK_EVENTS,
    Hook,
    HookResult,
    HookRunner,
    build_hook_runner,
    load_hooks,
)
from axiom.core.knowledge import KnowledgeHit, KnowledgeManager, KnowledgeStore, KnowledgeTools
from axiom.core.mcp import MCPClient, MCPManager, MCPServer
from axiom.core.memory import MemoryCategory, MemoryItem, MemoryScope, MemoryStore, MemoryTools
from axiom.core.models import ModelInfo, ModelRegistry
from axiom.core.orchestrator import Orchestrator
from axiom.core.parallel import ParallelResult, run_parallel
from axiom.core.planner import Planner, PlanStep, TaskPlan
from axiom.core.plugins import PluginManifest, PluginRegistry, UIExtension, UIExtensionBlock
from axiom.core.presets import AgentPreset, PresetStore, detect_mode
from axiom.core.project_index import ProjectIndex, ProjectMemory, index_project
from axiom.core.prompt_builder import (
    FULL_BUDGET_CHARS,
    MINI_BUDGET_CHARS,
    PromptLayers,
    build_system_prompt,
    select_variant,
)
from axiom.core.providers import (
    KNOWN_PROVIDERS,
    AnthropicProvider,
    ChatMessage,
    KnownProvider,
    ModelCatalog,
    ModelProfile,
    OllamaProvider,
    OpenAICompatibleProvider,
    Provider,
    ProviderCapabilities,
    ProviderManager,
    ProviderStatus,
)
from axiom.core.ptc import parse_program, run_program
from axiom.core.router import ModelRouter, RouterConfig, RouteTarget
from axiom.core.rules import RuleManager, RuleReport, RuleSource
from axiom.core.sandbox import Sandbox
from axiom.core.skills import Skill, SkillRegistry, load_skill_directory, parse_skill_file
from axiom.core.state import GenerationState
from axiom.core.state_machine import GenerationStateMachine
from axiom.core.tasks import Task, TaskError, TaskEvent, TaskState, TaskStore
from axiom.core.trajectory import Trajectory
from axiom.core.trajectory_store import TrajectoryStore
from axiom.core.verify import VerificationLoop

__version__ = "1.0.0"

__all__ = [
    "__version__",
    # core
    "ChatSession",
    "Config",
    "GenerationState",
    "GenerationStateMachine",
    "Message",
    "ModelInfo",
    "ModelRegistry",
    "Provider",
    "ProviderManager",
    "AgentProfile",
    "AgentRegistry",
    "SubagentBudget",
    "compact_report",
    "REPORT_SECTIONS",
    "AnthropicProvider",
    "ChatMessage",
    "KnownProvider",
    "KNOWN_PROVIDERS",
    "ModelCatalog",
    "ModelProfile",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "ProviderCapabilities",
    "ProviderStatus",
    "CancelToken",
    "EventBus",
    "Trajectory",
    "TrajectoryStore",
    "Orchestrator",
    "PlanStep",
    "Planner",
    "Task",
    "TaskError",
    "TaskEvent",
    "TaskPlan",
    "TaskState",
    "TaskStore",
    "CompactionState",
    "ContextEngine",
    "StructuredCompaction",
    "VerificationLoop",
    "Sandbox",
    "Skill",
    "SkillRegistry",
    "load_skill_directory",
    "parse_skill_file",
    "RuleManager",
    "RuleReport",
    "RuleSource",
    "HOOK_EVENTS",
    "Hook",
    "HookResult",
    "HookRunner",
    "build_hook_runner",
    "load_hooks",
    "ModelRouter",
    "RouteTarget",
    "RouterConfig",
    "MCPClient",
    "MCPManager",
    "MCPServer",
    "MemoryCategory",
    "MemoryItem",
    "MemoryScope",
    "MemoryStore",
    "MemoryTools",
    "KnowledgeHit",
    "KnowledgeManager",
    "KnowledgeStore",
    "KnowledgeTools",
    "PluginManifest",
    "PluginRegistry",
    "PromptLayers",
    "FULL_BUDGET_CHARS",
    "MINI_BUDGET_CHARS",
    "build_system_prompt",
    "select_variant",
    "UIExtension",
    "UIExtensionBlock",
    "AgentPreset",
    "PresetStore",
    "detect_mode",
    "ProjectIndex",
    "ProjectMemory",
    "index_project",
    "parse_program",
    "run_program",
    "ParallelResult",
    "run_parallel",
    # events
    "ChatEvent",
    "ContentChunk",
    "Done",
    "ErrorEvent",
    "ReasoningChunk",
    "SearchResultEvent",
    "StatusChange",
    "ToolCallEvent",
    "ToolResultEvent",
    # errors
    "AxiomError",
    "GenerationCancelledError",
    "InvalidResponseError",
    "ModelNotFoundError",
    "OllamaUnavailableError",
    "SearchUnavailableError",
]
