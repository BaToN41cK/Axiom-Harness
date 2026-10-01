"""Frontend-agnostic core of AXIOM.

This package MUST NOT import any UI framework (textual, rich, PyQt, toga...).
It communicates with frontends exclusively through methods and an event stream
(see :mod:`axiom.core.events`).
"""

from axiom.core.agent import Agent
from axiom.core.artifact_workspace import ArtifactDocument, ArtifactVersion, ArtifactWorkspace
from axiom.core.artifacts import Artifact, ArtifactTools, build_artifact, to_csv, to_markdown, to_svg
from axiom.core.automation import (
    AutomationStore,
    Schedule,
    ScheduleInterval,
    create_automation_task,
    due_schedules,
    record_run,
    run_due,
)
from axiom.core.bus import EventBus, validate_event_envelope
from axiom.core.cache import TTLCache
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
from axiom.core.i18n import DEFAULT_LOCALE, Locale, locales, translate
from axiom.core.logging import get_logger, setup_logging
from axiom.core.models import ModelInfo, ModelRegistry
from axiom.core.ollama import ChatStreamParser, OllamaClient
from axiom.core.paging import Page, paginate, paginate_diff, paginate_lines
from axiom.core.performance import MetricsSnapshot, Timer, capture_metrics, compare_metrics
from axiom.core.permissions import PermissionManager, PermissionMode
from axiom.core.planner import Planner, PlanStep, TaskPlan
from axiom.core.profiles import ProfileManager
from axiom.core.retry import RetryResult, retry_async
from axiom.core.rules import RuleManager, RuleSource
from axiom.core.state import GenerationState
from axiom.core.state_machine import GenerationStateMachine
from axiom.core.tasks import Task, TaskError, TaskEvent, TaskState, TaskStore
from axiom.core.tools import ToolRegistry
from axiom.core.workspace import WorkspaceManager

__all__ = [
    "DEFAULT_LOCALE",
    "Agent",
    "Artifact",
    "ArtifactDocument",
    "ArtifactTools",
    "ArtifactVersion",
    "ArtifactWorkspace",
    "AutomationStore",
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
    "EventBus",
    "GenerationState",
    "GenerationStateMachine",
    "HistoryStore",
    "InvalidResponseError",
    "Locale",
    "Message",
    "MetricsSnapshot",
    "ModelInfo",
    "ModelRegistry",
    "OllamaClient",
    "Page",
    "PermissionManager",
    "PermissionMode",
    "PlanStep",
    "Planner",
    "ProfileManager",
    "ReasoningChunk",
    "RetryResult",
    "RuleManager",
    "RuleSource",
    "Schedule",
    "ScheduleInterval",
    "SearchUnavailableError",
    "StructuredCompaction",
    "TTLCache",
    "Task",
    "TaskError",
    "TaskEvent",
    "TaskPlan",
    "TaskState",
    "TaskStore",
    "Timer",
    "ToolCallEvent",
    "ToolRegistry",
    "ToolResultEvent",
    "WorkspaceManager",
    "build_artifact",
    "capture_metrics",
    "compare_metrics",
    "create_automation_task",
    "due_schedules",
    "get_logger",
    "locales",
    "paginate",
    "paginate_diff",
    "paginate_lines",
    "record_run",
    "retry_async",
    "run_due",
    "setup_logging",
    "to_csv",
    "to_markdown",
    "to_svg",
    "translate",
    "validate_event_envelope",
]
