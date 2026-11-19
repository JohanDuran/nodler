"""Starter agents and workflow: coder (implements + tests) → reviewer → built-in merge."""

from .models import Agent, Outcome, Rule, Status, Transition, Workflow

CODER_PROMPT = """You are the CODER on an automated software team.

Your job: implement the task described in the card, on the git branch that is already checked out
in your working directory.

How you work:
- Read the repository first (and its CLAUDE.md / README if present) to follow its conventions.
- Keep the change focused on the card. Do not refactor unrelated code.
- Write or update automated tests for what you change, and run them until they pass.
- Commit your work with clear commit messages (git add + git commit). Leave no uncommitted changes.
- Never push, never open PRs, never switch branches: the orchestrator does that.
- If review feedback is included below, address every point of it.

Finish with one of these outcomes:
- done: the task is implemented, tested, and committed.
- blocked: you cannot complete it (unclear requirements, missing access, impossible). Explain why.

In `summary`, write a short PR-style description of what you changed and how you tested it."""

REVIEWER_PROMPT = """You are the REVIEWER on an automated software team.

Your job: review the change on the current branch (its diff against the base branch is below) against
the card's requirements. You must NOT modify any file; you only read and judge.

Check:
- Does it do what the card asks, completely?
- Correctness: bugs, edge cases, error handling.
- Tests: do they exist and actually cover the change?
- Readability and consistency with the rest of the codebase.
- Security problems (secrets, injection, unsafe input handling).

Finish with one of these outcomes:
- approved: ready to merge. Minor nits may be listed but must not block.
- changes_requested: there are problems the coder must fix.

In `summary`, write the review as you would post it on the PR: a verdict line, then a numbered list
of concrete, actionable points (file and what to change)."""


def default_agents() -> list[Agent]:
    return [
        Agent(
            id="coder",
            name="Coder",
            description="Implements the card, writes and runs tests, commits.",
            system_prompt=CODER_PROMPT,
            model="opus",
            tools=["Read", "Glob", "Grep", "Edit", "Write", "Bash"],
            workspace="write",
            max_turns=120,
            outcomes=[
                Outcome(name="done", description="Implemented, tested and committed"),
                Outcome(name="blocked", description="Cannot complete; needs a human"),
            ],
            post_checks=["has_commits", "tests_pass", "clean_worktree"],
        ),
        Agent(
            id="reviewer",
            name="Reviewer",
            description="Reviews the diff against the card. Read-only.",
            system_prompt=REVIEWER_PROMPT,
            model="opus",
            tools=["Read", "Glob", "Grep"],
            workspace="read",
            max_turns=40,
            include_diff=True,
            outcomes=[
                Outcome(name="approved", description="Ready to merge"),
                Outcome(name="changes_requested", description="Coder must fix the listed points"),
            ],
            post_checks=["clean_worktree"],
        ),
    ]


def default_workflow() -> Workflow:
    return Workflow(
        id="default",
        name="Code → Review → Merge",
        statuses=[
            Status(id="backlog", name="Backlog", kind="human", x=0, y=0),
            Status(id="ready", name="Ready", kind="agent", agent_id="coder", x=320, y=0),
            Status(id="review", name="In Review", kind="agent", agent_id="reviewer", x=640, y=0),
            Status(id="merge", name="Ready to merge", kind="action", action="merge", x=960, y=0),
            Status(id="done", name="Done", kind="done", x=1280, y=0),
            Status(id="human", name="Needs human", kind="human", x=640, y=300),
        ],
        transitions=[
            Transition(id="t1", source="ready", outcome="done", target="review", effects=["open_pr"]),
            Transition(id="t2", source="ready", outcome="blocked", target="human", effects=["comment"]),
            Transition(id="t3", source="ready", outcome="check_failed", target="ready"),
            Transition(id="t4", source="review", outcome="approved", target="merge", effects=["post_review"]),
            Transition(
                id="t5", source="review", outcome="changes_requested", target="ready", effects=["post_review"]
            ),
            Transition(id="t6", source="review", outcome="check_failed", target="human"),
            Transition(id="t7", source="merge", outcome="merged", target="done"),
            Transition(id="t8", source="merge", outcome="conflict", target="ready"),
            Transition(id="t9", source="merge", outcome="tests_failed", target="ready"),
            Transition(id="t10", source="merge", outcome="no_pr", target="human"),
        ],
        rules=[
            Rule(id="r1", type="max_visits", status="ready", limit=3, target="human"),
            Rule(id="r2", type="max_errors", status=None, limit=3, target="human"),
        ],
        fallback_status="human",
    )
