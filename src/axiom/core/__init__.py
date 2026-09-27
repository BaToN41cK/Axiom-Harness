"""Frontend-agnostic core of AXIOM.

This package MUST NOT import any UI framework (textual, rich, PyQt, toga...).
It communicates with frontends exclusively through methods and an event stream
(see :mod:`axiom.core.events`).
"""

from axiom.core.agent import Agent
from axiom.core.chat import ChatSession
from axiom.core.config import Config
from axiom.core.context import ContextManager, ContextReport
from axiom.core.context_engine import CompactionState, ContextEngine, StructuredCompaction
from axiom.core.errors import AxiomError, InvalidResponseError, SearchUnavailableError
from axiom.core.events import (
    ContentChunk,
    Done,
    ErrorEvent,
    Event,
    Message,
    ReasoningChunk,
    ToolCallEvent,
    ToolResultEvent,
)
from axiom.core.history import HistoryStore
from axiom.core.logging import get_logger, setup_logging
from axiom.core.models import ModelInfo, ModelRegistry
from axiom.core.ollama import ChatStreamParser, OllamaClient
from axiom.core.permissions import PermissionManager, PermissionMode
from axiom.core.planner import Planner, PlanStep, TaskPlan
from axiom.core.profiles import ProfileManager
from axiom.core.retry import RetryResult, retry_async
from axiom.core.state import GenerationState
from axiom.core.state_machine import GenerationStateMachine
from axiom.core.tasks import Task, TaskError, TaskEvent, TaskState, TaskStore
from axiom.core.tools import ToolRegistry
from axiom.core.workspace import WorkspaceManager

__all__ = [
    "Agent",
    "AxiomError",
    "ChatSession",
    "ChatStreamParser",
    "CompactionState",
    "Config",
    "ContentChunk",
    "ContextEngine",
    "ContextManager",
    "ContextReport",
    "Done",
    "ErrorEvent",
    "Event",
    "GenerationState",
    "GenerationStateMachine",
    "HistoryStore",
    "InvalidResponseError",
    "Message",
    "ModelInfo",
    "ModelRegistry",
    "OllamaClient",
    "PermissionManager",
    "PermissionMode",
    "PlanStep",
    "Planner",
    "ProfileManager",
    "ReasoningChunk",
    "RetryResult",
    "SearchUnavailableError",
    "StructuredCompaction",
    "Task",
    "TaskError",
    "TaskEvent",
    "TaskPlan",
    "TaskState",
    "TaskStore",
    "ToolCallEvent",
    "ToolRegistry",
    "ToolResultEvent",
    "WorkspaceManager",
    "get_logger",
    "retry_async",
    "setup_logging",
]
