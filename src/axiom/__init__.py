"""AXIOM — Local Intelligence Terminal Workspace.

A premium terminal AI client powered by a local Ollama backend.

Public API surface. Frontends should depend only on what is exported here
and on :mod:`axiom.core` / :mod:`axiom.shared` modules.
"""

from axiom.core.agents import AgentProfile, AgentRegistry
from axiom.core.bus import EventBus
from axiom.core.chat import ChatSession
from axiom.core.config import Config
from axiom.core.context_engine import ContextEngine
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
from axiom.core.mcp import MCPClient, MCPManager, MCPServer
from axiom.core.models import ModelInfo, ModelRegistry
from axiom.core.orchestrator import Orchestrator
from axiom.core.parallel import ParallelResult, run_parallel
from axiom.core.planner import Planner, PlanStep, TaskPlan
from axiom.core.plugins import PluginManifest, PluginRegistry
from axiom.core.presets import AgentPreset, PresetStore, detect_mode
from axiom.core.project_index import ProjectIndex, ProjectMemory, index_project
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
from axiom.core.sandbox import Sandbox
from axiom.core.skills import Skill, SkillRegistry
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
    "ContextEngine",
    "VerificationLoop",
    "Sandbox",
    "Skill",
    "SkillRegistry",
    "ModelRouter",
    "RouteTarget",
    "RouterConfig",
    "MCPClient",
    "MCPManager",
    "MCPServer",
    "PluginManifest",
    "PluginRegistry",
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
