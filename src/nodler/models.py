"""Data model: workflows (state machines), agents, projects, cards, runs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StatusKind = Literal["agent", "action", "human", "done"]
Workspace = Literal["write", "read", "none"]
PostCheck = Literal["has_commits", "tests_pass", "clean_worktree"]
Effect = Literal["open_pr", "post_review", "comment"]

ERROR = "error"  # pseudo-outcome when a run crashes; handled by max_errors rules
CHECK_FAILED = "check_failed"  # pseudo-outcome when a post-check fails


class Status(BaseModel):
    id: str
    name: str  # must match the option name of the board's Status field
    kind: StatusKind
    agent_id: str | None = None  # kind == "agent"
    action: str | None = None  # kind == "action" (see nodler.actions.ACTIONS)
    x: float = 0
    y: float = 0


class Transition(BaseModel):
    id: str
    source: str  # status id
    outcome: str
    target: str  # status id
    effects: list[Effect] = Field(default_factory=list)


class Rule(BaseModel):
    """Guard rails evaluated by the engine.

    - max_visits: entering ``status`` (or any status when None) more than ``limit``
      times redirects the card to ``target`` instead.
    - max_errors: ``limit`` consecutive run errors in ``status`` (or any) moves the
      card to ``target``. Below the limit the card stays and is retried.
    """

    id: str
    type: Literal["max_visits", "max_errors"]
    status: str | None = None
    limit: int = Field(ge=1)
    target: str


class Workflow(BaseModel):
    id: str
    name: str
    version: int = 1
    statuses: list[Status]
    transitions: list[Transition] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    fallback_status: str  # status id used when no transition matches

    def status(self, status_id: str) -> Status | None:
        return next((s for s in self.statuses if s.id == status_id), None)

    def status_by_name(self, name: str) -> Status | None:
        key = name.strip().lower()
        return next((s for s in self.statuses if s.name.strip().lower() == key), None)


class Outcome(BaseModel):
    name: str
    description: str = ""


class Agent(BaseModel):
    id: str
    name: str
    description: str = ""
    system_prompt: str
    model: str | None = None  # e.g. "opus", "sonnet", "haiku" or a full model id
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    tools: list[str] = Field(default_factory=lambda: ["Read", "Glob", "Grep"])
    permission_mode: Literal["default", "acceptEdits", "bypassPermissions", "dontAsk"] = "dontAsk"
    max_turns: int | None = 60
    workspace: Workspace = "read"
    outcomes: list[Outcome]
    post_checks: list[PostCheck] = Field(default_factory=list)
    blocked_commands: list[str] = Field(default_factory=list)  # substrings blocked in Bash
    include_diff: bool = False  # put the branch diff vs base into the prompt


class Project(BaseModel):
    id: str
    name: str
    repo: str  # "owner/name"
    board_owner: str  # user or org that owns the GitHub Project
    board_number: int
    local_path: str  # local clone of the repo
    base_branch: str = "main"
    setup_command: str = ""  # run once in each new worktree, e.g. "npm ci"
    test_command: str = ""  # empty = no tests
    workflow_id: str
    context: str = ""  # extra project context given to every agent
    enabled: bool = True


class Card(BaseModel):
    """Nodler's memory of a board item (the board itself holds the current status)."""

    item_id: str
    project_id: str
    issue_number: int | None = None
    title: str = ""
    workflow_id: str
    workflow_version: int
    status_id: str | None = None  # last status nodler saw or set
    visits: dict[str, int] = Field(default_factory=dict)
    errors: dict[str, int] = Field(default_factory=dict)
    branch: str | None = None
    pr_number: int | None = None
    last_output: dict = Field(default_factory=dict)  # last agent structured output
    locked: bool = False


class Run(BaseModel):
    id: str
    project_id: str
    item_id: str
    issue_number: int | None = None
    status_id: str
    worker: str  # agent id or action name
    started_at: float
    finished_at: float | None = None
    outcome: str | None = None
    target_status_id: str | None = None
    summary: str = ""
    error: str | None = None
    cost_usd: float | None = None
    num_turns: int | None = None
    session_id: str | None = None
    log: list[dict] = Field(default_factory=list)
