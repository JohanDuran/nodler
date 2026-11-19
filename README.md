# nodler

**An agentic software development life cycle that runs on your own PC.**

You plan work as issues on a GitHub Projects board. nodler picks up each card and hands it to role agents: a
**coder** writes the change and its tests, and a **reviewer** reviews the code. nodler itself checks the work,
opens the PR and merges it. Every step follows a state machine that you draw and edit in a web UI.

```
 You (+ Claude) ──create issues──►  GitHub Project board  ◄── you add / move cards
                                          ▲      │
                              move + comment      │ next queued card
                                          │      ▼
                           nodler worker (runs on your PC)
                                          │ runs the worker attached to the card's status
          ┌──────────────┬────────────────┼────────────────┬──────────────┐
       Coder agent   Reviewer agent   built-in merge   your own agents   human statuses
     (writes code)   (read-only)     (plain code)     (QA, docs, …)    (nodler waits)
```

Agents run through the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview), which uses
the Claude Code login on your machine.

---

## Contents

- [Why nodler](#why-nodler)
- [How a card flows](#how-a-card-flows)
- [Core concepts](#core-concepts)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Using the web UI](#using-the-web-ui)
- [Role enforcement and safety](#role-enforcement-and-safety)
- [Usage limits and authentication](#usage-limits-and-authentication)
- [Configuration reference](#configuration-reference)
- [Development](#development)
- [Limitations and roadmap](#limitations-and-roadmap)

---

## Why nodler

- **Real separation of roles.** The coder never reviews, and the reviewer can't change a file. These are hard
  limits that nodler enforces, not polite requests in a prompt.
- **Deterministic steps stay deterministic.** Running tests, pushing, opening PRs and merging are plain code.
  An LLM is only used where judgment is needed.
- **Agents never move cards.** An agent returns an *outcome* such as `done`, `approved` or
  `changes_requested`. The workflow engine decides where the card goes.
- **You own the process.** Statuses, transitions, retry rules and agents are all editable in the UI. Workflows
  are versioned, so editing one never breaks a card that's already in progress.
- **The board is the source of truth.** Every move is visible on GitHub, and every step leaves a comment on
  the issue.

## How a card flows

Example: issue **#12 "Add a dark mode toggle"** in the default workflow.

```
Backlog → Ready → In Review → Ready to merge → Done
            ▲         │              │
            └─────────┴──────────────┘   rework (review feedback, conflicts, failing tests)
                       └──→ Needs human  (limits reached / blocked / unknown outcome)
```

1. **You queue it.** Move the card from `Backlog` (a human status that nodler ignores) to `Ready`.
2. **The coder works.** nodler creates a git worktree on branch `nodler/12-add-a-dark-mode-toggle` from
   the latest base branch and runs the project's setup command (for example `npm ci`). It then starts the
   **Coder** agent with the issue, the project context and the card's history. The coder implements the
   change, writes tests, runs them and **commits locally**. It can't push or call `gh`.
3. **nodler checks the claim.** If the coder says `done`, nodler runs the post-checks itself: are there
   commits, do the tests pass, is the worktree clean? If a check fails, the outcome becomes `check_failed`.
4. **The engine moves the card.** `Ready + done → In Review`, with the effect `open_pr`: nodler pushes the
   branch and opens a PR that says "Closes #12".
5. **The reviewer works.** It gets the diff and read-only access, and returns `approved` or
   `changes_requested` with a written review, which nodler posts on the PR.
   - `changes_requested` sends the card back to `Ready`. The coder runs again with the review in its prompt,
     and the existing PR is updated.
   - After 3 round trips (a rule you can change), the card goes to `Needs human`.
6. **Merge (plain code).** nodler rebases the branch onto the base branch and re-runs the tests. If both pass,
   it squash-merges the PR and deletes the branch and worktree. Conflicts or failing tests send the card
   back to the coder with the details.
7. **Done.** The PR closes the issue.

## Core concepts

| Concept | What it is |
|---|---|
| **Project** | A repo, its GitHub Project board, a local clone, a setup command, a test command, extra context for agents, and a workflow |
| **Workflow** | A versioned state machine made of **statuses**, **transitions** and **rules**, plus a **fallback status** |
| **Status** | A board column. Its *kind* says who works on cards there: an `agent`, a built-in `action`, a `human` (nodler ignores the card), or `done` |
| **Outcome** | What a worker returns. Agents declare their own outcomes; built-in actions have fixed ones. A failed post-check produces `check_failed`, and a crash produces an error |
| **Transition** | `status + outcome → status`, optionally with **effects** that run before the move |
| **Effect** | `open_pr` (push the branch, open or update the PR), `post_review` (post the agent's summary on the PR), `comment` (post it on the issue) |
| **Rule** | A guard rail. `max_visits`: entering a status more than N times redirects the card to another status. `max_errors`: N errors in a row moves the card; below that it's retried |
| **Agent** | A role: prompt, model, effort, a **hard tool list**, workspace access (`write` / `read` / `none`), outcomes, post-checks, extra blocked commands |
| **Card** | nodler's memory of a board item: the workflow version it's pinned to, visit and error counters, branch, PR, notes |
| **Run** | One worker execution on a card, with its log, outcome, summary, turns and equivalent cost |

### Built-in action: `merge`

Rebase onto the base branch, then re-run tests, then push, then squash-merge, then clean up.
Outcomes: `merged`, `conflict`, `tests_failed`, `no_pr`.

### Post-checks

| Check | Passes when |
|---|---|
| `has_commits` | the branch has at least one commit ahead of the base branch |
| `tests_pass` | the project's test command exits with code 0 |
| `clean_worktree` | there are no uncommitted changes. For a read-only agent, any change is **discarded** and flagged |

`has_commits` and `tests_pass` only run for "finishing" outcomes (`done`, `approved`, or an agent's only
outcome), so a coder that reports `blocked` doesn't fail them.

## Requirements

- **Windows, macOS or Linux.** It has been developed and tested on Windows 11.
- **Python 3.12+** and [uv](https://docs.astral.sh/uv/)
- **Node.js 18+**, only needed to rebuild the web UI
- **git**
- **GitHub CLI** (`gh`), installed. You don't need to log in from a terminal: the **Setup** page does it.
- **A Claude subscription** (e.g. Pro or Max). The Agent SDK bundles Claude Code, and the **Setup** page signs
  it in.

### Connecting accounts (no terminal needed)

When something is missing, nodler opens on the **Setup** page, which walks through four steps:

| Step | What happens |
|---|---|
| **Connect Claude** | nodler runs Claude Code's own browser login (`claude auth login`) with the SDK's bundled binary. A claude.ai tab opens; sign in and approve. If the page shows a code, paste it into nodler. The step then shows your account and plan |
| **Connect GitHub** | nodler starts GitHub's device login (`gh auth login --web`, or `gh auth refresh` to add missing permissions). It shows a **one-time code**: click **Copy code & open GitHub**, paste it, approve. Permissions requested: `project`, `repo`, `read:org` |
| **Git** | Checks that git is installed. If it isn't, nodler shows the install command and download link (same for the GitHub CLI) |
| **Add your first project** | Pick a repository from your list. nodler downloads it (or uses a folder you name), **detects the install and test commands** (npm/pnpm/yarn, uv/pip, Go, Rust), and **creates a GitHub project board** with the workflow's columns, linked to the repo |

nodler never sees your passwords or tokens. Both logins happen on the official claude.ai and github.com
pages, and the tokens stay where each tool normally keeps them. The buttons work because nodler runs on the
same computer as your browser.

If a login expires later, the worker pauses and the dashboard shows **Reconnect in Setup**.

Terminal alternative, if you prefer it:
```bash
gh auth login --web --scopes project,repo,read:org
claude          # then type /login
```

## Installation

```bash
git clone https://github.com/JohanDuran/nodler.git
cd nodler
uv sync                      # Python dependencies (includes claude-agent-sdk)
cd web && npm install && npm run build && cd ..   # builds the UI into src/nodler/static
```

Start it:

```bash
uv run nodler serve          # http://127.0.0.1:8787
```

| Option | Default | Meaning |
|---|---|---|
| `--port` | `8787` | HTTP port |
| `--host` | `127.0.0.1` | Bind address. Keep it local: the API has no authentication |
| `--data` | `./data` | Folder for the SQLite database and card worktrees |
| `--no-worker` | off | Serve the UI and API without processing cards |

The worker **starts paused**. Press **Resume** on the dashboard once a project is set up.

## Quick start

The fastest way: start nodler, open http://127.0.0.1:8787, and follow the **Setup** page (above). After
"Add your first project", jump to step 5 below.

Manual setup, e.g. to use an existing board:

1. **Create a GitHub Project** for your repo and link it to the repo.
2. **Set its `Status` field options** to match the workflow's statuses. For the default workflow:
   `Backlog`, `Ready`, `In Review`, `Ready to merge`, `Done`, `Needs human`.
   Status names are matched without regard to case.
3. **Clone the repo locally** and make sure its tests pass on the base branch.
4. In nodler, go to **Projects → + New** and fill in:
   - repository `owner/name`, board owner and board number
   - local clone path, base branch
   - **setup command** (e.g. `npm ci`, `uv sync`), which runs once in each new worktree
   - **test command** (e.g. `npm run typecheck && npm test`)
   - project context for the agents (stack, conventions)

   Save. The **setup check** confirms the clone, the `gh` scope, the board, and that every status exists as
   a column.
5. **Create an issue** with clear requirements and a "done when" section, and add it to the board in
   `Backlog`.
6. Press **Resume** on the dashboard, then **move the card to `Ready`**. Follow it live under **Now:**.

> Tip: small, well-scoped cards succeed far more often than large ones. Use an issue's description as the
> spec: what to do, what's out of scope, and when it's done.

## Using the web UI

| Page | What you can do |
|---|---|
| **Dashboard** | Pause or resume the worker, trigger a board check, watch the live log of the current run, see warnings and recent runs |
| **Workflows** | Edit the state machine as a graph. Click a status to set its kind and agent or action, then wire **each outcome to a target status** and toggle effects. Drag from a status's right handle to another status to add a transition. Edit **rules** and the **fallback status**. Saving creates a new version; older versions open read-only. **Duplicate** a workflow to make a variant |
| **Agents** | Create and edit agents: role prompt, model (`opus` / `sonnet` / `haiku` or a full id), effort, max turns, workspace, **tools**, outcomes, post-checks, "include branch diff in prompt", extra blocked commands |
| **Projects** | Register repos and boards (or edit what Setup created), and run the setup check |
| **Setup** | Connect Claude and GitHub, check tools, add a project in one click |
| **Runs** | History of every run with outcome, summary, log, turns and equivalent cost |

The editor validates continuously: unknown agents, outcomes a status can't produce, duplicate transitions and
missing statuses block saving. Unhandled outcomes produce a warning, because they go to the fallback status.

### Adding an agent to the workflow

Example: add a **QA** step between review and merge.

1. **Agents → + New**: id `qa`, workspace `read`, tools `Read, Glob, Grep, Bash`, outcomes `pass` and `fail`,
   post-check `clean_worktree`, and a prompt explaining how to exercise the feature.
2. **Workflows → + Status** `QA` (add the same option to the board's Status field), kind *agent*, agent *QA*.
3. Re-wire `In Review: approved → QA`, then `QA: pass → Ready to merge` and `QA: fail → Ready`.
4. Save. New cards use the new version; cards already in progress finish on theirs.

## Role enforcement and safety

Agents run unattended with shell access on your machine, so nodler applies several layers of protection:

1. **Hard tool list.** Each agent only *sees* the tools in its configuration (the SDK's `tools` option). A
   reviewer with `Read, Glob, Grep` has no way to edit a file or run a command.
2. **PreToolUse guard** (a Python hook, which blocks on failure):
   - blocks `git push`, `gh …`, `git remote`, switching to the base branch, and destructive commands, plus
     any extra commands you configure for the agent
   - blocks writes outside the card's worktree, and all writes by `read` / `none` agents
3. **Post-checks** verify the result from outside the agent. A read-only agent that somehow changed files
   gets the changes discarded and the outcome becomes `check_failed`.
4. **nodler does all GitHub writes itself.** Agents never need GitHub credentials.
5. **The card text is treated as untrusted:** prompts are sent verbatim (no `@file` expansion or slash
   commands).

What nodler does **not** do (yet): run agents in a container or sandbox. Worktrees isolate files per card,
but not the process. Only point nodler at repos you trust. Consider a dedicated GitHub account or token for
`gh`, and keep `--host` on `127.0.0.1`.

## Usage limits and authentication

- nodler is meant to run on your **Claude Code login** (for example a Pro or Max plan). Usage counts toward
  that plan's limits, which are shared with claude.ai.
- If **`ANTHROPIC_API_KEY`** is set, the SDK uses it and runs are **billed to the API**. nodler refuses to
  run in that case unless you allow it explicitly (setting `allow_api_key`).
- When Claude Code reports a **usage limit** (`RateLimitEvent` with status `rejected`), the worker pauses
  until the reported reset time. The card stays where it is, and no error is counted against it.
- When the **login is missing or expired**, the worker pauses and the dashboard links to **Setup** to
  reconnect.
- The "cost" shown for runs is the equivalent API cost reported by Claude Code. It's useful for comparing
  runs; on a subscription you aren't billed that amount.

Whether a subscription login may be used with the Agent SDK is governed by Anthropic's terms. Check them for
your plan.

## Configuration reference

### Project

| Field | Description |
|---|---|
| `id`, `name` | Identifier and display name |
| `repo` | `owner/name` on GitHub |
| `board_owner`, `board_number` | The GitHub Project (user or org login, or `@me`) |
| `local_path` | Local clone. Worktrees are created from it |
| `base_branch` | Usually `main` |
| `setup_command` | Runs once in each new worktree (e.g. `npm ci`). If it fails, the worktree is removed |
| `test_command` | Used by the `tests_pass` check and before merging. Leave empty for none |
| `workflow_id` | The workflow this project uses |
| `context` | Extra text added to every agent prompt |
| `enabled` | Whether the worker processes this board |

### Settings (`/api/settings`)

| Setting | Default | Meaning |
|---|---|---|
| `comment_moves` | `true` | Comment on the issue every time nodler moves the card |
| `allow_api_key` | `false` | Allow runs while `ANTHROPIC_API_KEY` is set (billed to the API) |

### How cards are picked

The worker processes **one card at a time**. Among all cards in agent or action statuses, it picks the one in
the status that comes latest in the workflow (finishing work comes before starting new work), then follows
board order. It checks boards every 60 seconds, immediately after finishing a card, or when you press
**Check boards now**.

### GitHub API budget

GitHub Projects is only reachable through GitHub's GraphQL API, which allows each user 5,000 points per hour,
shared by every tool you use with that account. nodler keeps its use low:
- It caches each board's layout (project, field and column ids) for 10 minutes.
- It only fetches cards in statuses it works on (`--query status:…`), not the whole board.
- It checks boards every 60 seconds.

If the limit is hit anyway, nodler waits until GitHub's reset time and says so on the dashboard. (`gh project`
reports this as "unknown owner type"; nodler recognizes it.)

### Manual moves

You can drag cards anywhere at any time, and nodler follows the board. Moving a card **out of a human
status** (e.g. rescuing it from `Needs human`) resets its visit and error counters.

## Development

```bash
uv run pytest                 # backend tests (engine, git worktrees, guards, API)
cd web && npm run dev         # UI dev server on :5173, proxies /api to :8787
cd web && npm run build       # type-check + build into src/nodler/static
```

### Layout

```
src/nodler/
  models.py     data model (Workflow, Status, Transition, Rule, Agent, Project, Card, Run)
  engine.py     pure state machine: decide(workflow, card, status, outcome) -> Decision
  validate.py   workflow validation (errors block saving, warnings are shown)
  catalog.py    built-in actions, effects, post-checks, tools, always-blocked commands
  defaults.py   starter agents (coder, reviewer) and workflow
  worker.py     the loop: scan boards, pick a card, run worker, check, effects, move
  runner.py     Claude Agent SDK wrapper: options, guard hook, structured outcome, rate limits
  github.py     gh CLI adapter: Projects v2 board, issues, PRs, repo list, board creation, rate limits
  auth.py       status of Claude / GitHub / git and guided browser logins (LoginManager)
  detect.py     guesses a repo's setup and test commands
  gitops.py     worktrees, rebase, push, diff, tests
  store.py      SQLite store (JSON documents; workflows are append-only versions)
  api.py        FastAPI REST API + serves the built UI + runs the worker
web/src/
  pages/        Dashboard, WorkflowEditor (React Flow), Agents, Projects, Runs, Setup
docs/design.md  design principles and decisions
```

Design rules for contributors are in [`CLAUDE.md`](CLAUDE.md) and [`docs/design.md`](docs/design.md). The most
important: `engine.py` stays free of I/O, deterministic steps are never agents, and agents never move cards.

## Limitations and roadmap

Current limitations:

- One card at a time, with no parallel cards yet.
- No container sandbox for agents (see [safety](#role-enforcement-and-safety)).
- Setup creates boards with the right columns, but nodler doesn't edit the columns of an existing board,
  because replacing Status options would clear the cards' statuses. Add missing options on GitHub (the setup
  check lists them).
- Draft board items are skipped. Convert them to issues.
- The coder and reviewer act through one GitHub identity. nodler posts reviews as PR comments rather than
  formal approvals.
- The API has no authentication. Keep it bound to localhost.

Ideas:

- Turn non-blocking review suggestions into new Backlog cards.
- More built-in actions (run CI, notify, deploy) and rules (timeouts, switching to a stronger model on retry).
- Parallel cards with conflict-aware scheduling.
- Running agents in containers.
- Metrics: first-pass approval rate, bounces per card, time and cost per card.
