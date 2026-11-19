# Nodler design

Nodler is a local, web-configurable orchestrator that runs an agentic software
development life cycle on GitHub Projects boards.

## Flow

1. The user and Claude discuss a project; Claude (or the user) creates issues on a
   GitHub Project board.
2. The user moves cards into a queued status (e.g. `Ready`).
3. The nodler worker picks the next card, runs the worker attached to that card's
   status, verifies the result, and moves the card according to the workflow.

## Core concepts

| Concept | Meaning |
|---|---|
| **Project** | A repo + a GitHub Project board + a local clone + a setup command (run once per worktree) + a test command + a workflow |
| **Workflow** | A versioned state machine: statuses, transitions, rules |
| **Status** | A board column. Its `kind` says who works on it: `agent`, `action` (built-in code), `human`, or `done` |
| **Transition** | `from status + outcome → to status`, optionally with effects (e.g. `open_pr`) |
| **Rule** | Guard rails, e.g. "after 3 visits to `In Dev` go to `Needs human`", "after 2 errors go to `Needs human`" |
| **Agent** | A role: prompt, model, allowed tools, outcomes it may return, workspace access, post-checks |

## Principles

- **Agents never move cards.** They return an outcome; the engine looks up the transition.
- **Roles are enforced, not requested.** Each agent gets a hard tool list (`tools`), a
  PreToolUse hook that blocks forbidden commands, and post-checks (e.g. a reviewer must
  leave the worktree clean).
- **Verify, don't trust.** The orchestrator itself runs tests, checks for commits, and
  opens/merges PRs. Deterministic steps are plain code, never an LLM.
- **The board is the source of truth for where a card is.** Nodler's DB stores the
  process (workflows, agents, rules) and history (runs, visit counts).
- **Cards are pinned to the workflow version they started with**, so editing the
  workflow never breaks in-flight cards.
- **Unknown outcome or missing transition → fallback status** (`Needs human`).

## Outcomes

An agent status can produce: any outcome declared by its agent, `check_failed` (a
post-check failed), or an error (handled by `max_errors` rules; otherwise retried).
Built-in action statuses produce the outcomes listed in `nodler.actions`.

## Card lifecycle in the worker

1. Scan every enabled project's board; sync nodler's card record (pinning new cards to the
   latest workflow version; a manual move out of a human status resets counters).
2. Pick one card in an agent/action status: latest status in the workflow first, then board order.
3. Lock it; for agents, ensure the card's worktree (`nodler/<issue>-<slug>`, setup command on creation),
   build the prompt (card, project context, notes from earlier runs, human comments, optional diff), run.
4. Post-checks may turn the outcome into `check_failed`; errors go through `max_errors` rules.
5. `engine.decide` → effects (`open_pr`, `post_review`, `comment`) → move on the board → comment.
6. Usage limit or login failure: no decision is made, the card stays, and the worker pauses.

## Auth

Agents run through the Claude Agent SDK, which runs the bundled Claude Code binary.
With no `ANTHROPIC_API_KEY` set it uses the user's Claude login (Pro plan). Nodler
warns if `ANTHROPIC_API_KEY` is set. When a `RateLimitEvent` reports `rejected`, the
worker pauses until `resets_at`.
