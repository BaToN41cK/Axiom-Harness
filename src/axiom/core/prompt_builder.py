"""Prompt layers — compact, budgeted, testable system prompts (W2.5).

The builder assembles the agent system prompt from ordered layers:

``core`` → ``role`` (profile) → ``workspace`` → ``project`` →
``memory`` → ``knowledge`` → ``skills``.

Every layer is optional except ``core``; the task always wins over profile
fluff because static layers stay minimal and dynamic blocks (memory, skills)
are appended last, right before this request's question. Two policy variants
keep small local models fast: ``mini`` (hard rules only) and ``full`` (the
complete decision policy). Selection is deterministic (request complexity,
never an extra LLM call) and hard budget-capped in characters.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Policy variant — concise rules vs the full decision policy.
MINI_VARIANT = "mini"
FULL_VARIANT = "full"

#: Hard budgets in characters (~4 chars ≈ 1 token).
MINI_BUDGET_CHARS = 4000
FULL_BUDGET_CHARS = 12000
#: Dynamic blocks are capped before the budget fight even starts.
MAX_MEMORY_CHARS = 1500
MAX_SKILLS_CHARS = 2000
MAX_TASK_CHARS = 2000
MAX_PROJECT_CHARS = 1500

#: Invariants every assembled prompt must satisfy. A prompt that violates
#: one is a builder bug, never something the model sees.
HONESTY_RULE = "Never claim a test, build, file, Git state, or tool result that was not observed."
NO_GUESS_RULE = "Do not guess: use list_files/read_file before answering about the project."

MINI_POLICY = (
    "You are AXIOM, a precise local AI assistant. "
    "Answer directly; use markdown when it helps. "
    + NO_GUESS_RULE + " " + HONESTY_RULE
)

FULL_POLICY = (
    "You are AXIOM, a precise local AI assistant running on the user's machine. "
    "Answer directly and accurately. Use markdown when it helps. "
    "Never invent facts; if you are unsure, say so. "
    "You have real tools: web_search(query) for current or factual online "
    "information, fetch_url(url) to read a linked page instead of guessing. "
    "Do not say you cannot browse the web. "
    "Workspace tools operate inside the user's project: list_files to explore, "
    "read_file before editing, edit_file with a unique exact snippet, "
    "write_file for new files, run_command for tests/builds, "
    "git_status/git_diff/git_log/git_branch for read-only inspection. "
    + NO_GUESS_RULE + " For changes: read first, then edit or write — "
    "use tools instead of only describing a plan. "
    "All paths are relative to the workspace root. "
    "Follow: understand → investigate → plan → execute → verify → "
    "correct → report. " + HONESTY_RULE + " "
    "If work is not verified, say exactly what remains unverified."
)

WORKSPACE_RULES = (
    "Workspace tools are enabled. For project questions use "
    "list_files/read_file instead of guessing; for changes use edit_file "
    "with a unique exact snippet, or write_file for new files."
)

RESPONSE_STYLE = (
    "Response style: lead with the answer, keep it tight, show the diff or "
    "the relevant code block for changes."
)


@dataclass
class PromptLayers:
    """Inputs for one system-prompt assembly. Plain data, no I/O."""

    user_text: str = ""
    variant: str = FULL_VARIANT
    budget_chars: int = FULL_BUDGET_CHARS
    role: str = ""             # active profile prompt (empty = none)
    workspace: str = ""        # real workspace block (path/kind/layout)
    project_rules: str = ""    # project rules that must survive
    memory: str = ""           # pre-rendered memory lines (already budgeted)
    knowledge: str = ""        # pre-rendered knowledge context
    skill_blocks: list[str] = field(default_factory=list)


def build_system_prompt(layers: PromptLayers) -> str:
    """Assemble the system prompt: fixed layer order, hard budget enforced."""
    policy = MINI_POLICY if layers.variant == MINI_VARIANT else FULL_POLICY
    parts: list[tuple[int, str]] = [(0, policy)]  # (priority, text); 0 never drops
    if layers.role:
        parts.append((8, f"Role: {layers.role.strip()}"[:MAX_PROJECT_CHARS]))
    if layers.workspace:
        parts.append((1, layers.workspace.strip()))
    if layers.project_rules:
        parts.append((2, f"Project rules: {layers.project_rules.strip()}"[:MAX_PROJECT_CHARS]))
    if layers.memory:
        parts.append((4, layers.memory.strip()[:MAX_MEMORY_CHARS]))
    if layers.knowledge:
        parts.append((5, layers.knowledge.strip()[:MAX_MEMORY_CHARS]))
    for block in layers.skill_blocks[:3]:
        if block and block.strip():
            parts.append((6, block.strip()[:MAX_SKILLS_CHARS // 2]))
    parts.append((7, RESPONSE_STYLE))
    tail = f"Current task: {(layers.user_text or '').strip()}"[:MAX_TASK_CHARS]
    if tail:
        parts.append((3, tail))
    # Priorities 0..2 (policy, workspace, project rules) and the task always
    # survive; the rest yield from least important until the budget fits.
    keep = sorted(parts, key=lambda item: item[0])
    budget = max(800, layers.budget_chars)
    while sum(len(text) for _, text in keep) > budget and len(keep) > 4:
        drop_at = max(range(len(keep)), key=lambda i: (keep[i][0], -i))
        if keep[drop_at][0] <= 2:  # must-survive floor reached
            break
        keep.pop(drop_at)
    ordered = sorted(keep, key=lambda item: item[0])
    return "\n\n".join(text for _, text in ordered)


def select_variant(user_text: str, *, mode: str = "auto", budget: str = "balanced") -> str:
    """Deterministic mini/full choice — no model call involved.

    ``fast``/economy pressure and trivial requests get ``mini``; an explicit
    ``deep`` mode or a complex task gets ``full``. Mirrors the reasoning-level
    heuristic so prompt depth tracks thinking depth.
    """
    if mode == "fast" or budget == "economy":
        return MINI_VARIANT
    if mode == "deep":
        return FULL_VARIANT
    from axiom.core.performance import complexity_of

    return FULL_VARIANT if complexity_of(user_text or "") == "high" else MINI_VARIANT

