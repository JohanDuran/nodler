"""The orchestrator loop: board → next card → worker (agent or action) → engine → board."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from . import github as gh
from . import gitops
from .engine import Decision, apply, decide
from .models import CHECK_FAILED, ERROR, Agent, Card, Project, Run, Status, Workflow
from .proc import CommandError
from .runner import api_key_in_env, run_agent
from .store import Store

log = logging.getLogger("nodler.worker")
to_thread = asyncio.to_thread


def is_auth_error(text: str) -> bool:
    t = text.lower()
    return any(s in t for s in ("failed to authenticate", "not logged in", "invalid api key", "oauth"))


def is_nodler_comment(body: str) -> bool:
    body = body.strip()
    return body.startswith("🤖 nodler") or body.endswith("by nodler._") or body.endswith("(reviewer agent)._")


class Worker:
    def __init__(self, store: Store, data_dir: Path, poll_seconds: int = 30):
        self.store = store
        self.data_dir = data_dir
        self.poll_seconds = poll_seconds
        self.paused: bool = bool(store.get_setting("paused", True))  # start paused until the user resumes
        self.paused_until: float | None = None
        self.current: dict | None = None  # the card being processed right now (for the UI)
        self.warnings: list[str] = []
        self.last_tick: float | None = None
        self.last_error: str | None = None
        self._wake = asyncio.Event()
        self._stop = False

    # ------------------------------------------------------------------ control
    def status(self) -> dict:
        return {
            "paused": self.paused,
            "paused_until": self.paused_until,
            "current": self.current,
            "warnings": self.warnings,
            "last_tick": self.last_tick,
            "last_error": self.last_error,
            "api_key_in_env": api_key_in_env(),
        }

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        if not paused:
            self.paused_until = None
        self.store.set_setting("paused", paused)
        self._wake.set()

    def poke(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop = True
        self._wake.set()

    async def loop(self) -> None:
        n = self.store.unlock_all_cards()
        if n:
            log.info("unlocked %d cards left locked by a previous run", n)
        while not self._stop:
            if self.paused_until and time.time() >= self.paused_until:
                self.paused_until = None
            if not self.paused and not self.paused_until:
                try:
                    worked = await self.tick()
                    self.last_error = None
                    if worked:
                        continue  # immediately look for the next card
                except Exception as exc:  # never let the loop die
                    log.exception("tick failed")
                    self.last_error = f"{type(exc).__name__}: {exc}"
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------ one pass
    async def tick(self) -> bool:
        """Process at most one card. Returns True if a card was worked on."""
        self.last_tick = time.time()
        if api_key_in_env() and not self.store.get_setting("allow_api_key", False):
            self.warnings = ["ANTHROPIC_API_KEY is set: runs would be billed to the API instead of your plan. "
                             "Unset it (or allow it in settings)."]
            return False
        warnings: list[str] = []
        candidates: list[tuple] = []
        for project in self.store.list_projects():
            if not project.enabled:
                continue
            try:
                found = await to_thread(self._scan_project, project, warnings)
                candidates.extend(found)
            except CommandError as exc:
                warnings.append(f"[{project.name}] {exc}")
        self.warnings = warnings
        if not candidates:
            return False
        # Finish work in progress first: statuses later in the workflow win, then board order.
        candidates.sort(key=lambda c: (-c[0], c[1]))
        _, _, project, board, item, card, workflow, status = candidates[0]
        await self.process(project, board, item, card, workflow, status)
        return True

    def _scan_project(self, project: Project, warnings: list[str]) -> list[tuple]:
        workflow_latest = self.store.get_workflow(project.workflow_id)
        if workflow_latest is None:
            warnings.append(f"[{project.name}] workflow '{project.workflow_id}' not found")
            return []
        board = gh.load_board(project.board_owner, project.board_number)
        missing = [s.name for s in workflow_latest.statuses if s.name.strip().lower() not in board.options]
        if missing:
            warnings.append(f"[{project.name}] board is missing Status options: {', '.join(missing)}")
        out = []
        for order, item in enumerate(gh.list_items(project.board_owner, project.board_number)):
            if not item.status:
                continue
            card = self.store.get_card(item.item_id)
            workflow = (
                self.store.get_workflow(card.workflow_id, card.workflow_version) if card else workflow_latest
            ) or workflow_latest
            status = workflow.status_by_name(item.status)
            if status is None:
                continue
            card = self._sync_card(project, item, card, workflow, status)
            if status.kind not in ("agent", "action") or card.locked:
                continue
            if item.content_type != "Issue" or not item.issue_number:
                warnings.append(f"[{project.name}] '{item.title}' is a draft; convert it to an issue to process it")
                continue
            if item.repo and item.repo.lower() != project.repo.lower():
                warnings.append(f"[{project.name}] '{item.title}' belongs to {item.repo}, not {project.repo}")
                continue
            position = workflow.statuses.index(status)
            out.append((position, order, project, board, item, card, workflow, status))
        return out

    def _sync_card(self, project: Project, item: gh.BoardItem, card: Card | None, workflow: Workflow,
                   status: Status) -> Card:
        if card is None:
            card = Card(
                item_id=item.item_id, project_id=project.id, issue_number=item.issue_number, title=item.title,
                workflow_id=workflow.id, workflow_version=workflow.version, status_id=status.id,
            )
        elif card.status_id != status.id:
            # Moved by a human. Leaving a human status = a fresh start for the counters.
            previous = workflow.status(card.status_id or "")
            if previous is not None and previous.kind == "human":
                card.visits.clear()
                card.errors.clear()
            card.status_id = status.id
        card.title = item.title
        self.store.save_card(card)
        return card

    # ------------------------------------------------------------------ processing
    async def process(self, project: Project, board: gh.Board, item: gh.BoardItem, card: Card,
                      workflow: Workflow, status: Status) -> None:
        card.locked = True
        self.store.save_card(card)
        run = Run(
            id=uuid.uuid4().hex[:12], project_id=project.id, item_id=card.item_id, issue_number=card.issue_number,
            status_id=status.id, worker=status.agent_id or status.action or "?", started_at=time.time(),
        )
        self.current = {"run_id": run.id, "project": project.name, "card": card.title, "issue": card.issue_number,
                        "status": status.name, "worker": run.worker, "started_at": run.started_at, "log": run.log}
        self.store.save_run(run)
        try:
            if status.kind == "agent":
                outcome, summary = await self._work_agent(project, item, card, status, run)
            else:
                outcome, summary = await self._work_action(project, card, status, run)
            run.summary = summary

            if outcome is None:  # usage limit / login problem: card stays put, no error counted
                run.outcome = "paused"
                return

            decision = decide(workflow, card, status.id, outcome)
            if outcome != ERROR and decision.effects:
                try:
                    await to_thread(self._apply_effects, project, card, status, outcome, summary, decision)
                except CommandError as exc:
                    run.error = f"effect failed: {exc}"
                    outcome, decision = ERROR, decide(workflow, card, status.id, ERROR)
            run.outcome = outcome
            apply(card, status.id, outcome, decision)
            run.target_status_id = decision.target
            await to_thread(self._move, project, board, card, workflow, status, outcome, decision)
        except Exception as exc:
            log.exception("processing failed")
            run.error = f"{type(exc).__name__}: {exc}"
            run.outcome = run.outcome or ERROR
            card.errors[status.id] = card.errors.get(status.id, 0) + 1
        finally:
            run.finished_at = time.time()
            card.locked = False
            self.store.save_card(card)
            self.store.save_run(run)
            self.current = None

    def _log(self, run: Run, entry: dict) -> None:
        entry.setdefault("t", time.time())
        run.log.append(entry)

    def _note(self, card: Card, text: str) -> None:
        notes = card.last_output.setdefault("notes", [])
        notes.append(text[:6000])
        del notes[:-6]

    def _worktree(self, project: Project, card: Card) -> Path:
        if not card.branch:
            card.branch = gitops.branch_name(card.issue_number, card.title)
        return gitops.ensure_worktree(
            project.local_path, self.data_dir / "worktrees" / project.id, card.branch, project.base_branch,
            setup_command=project.setup_command,
        )

    async def _work_agent(self, project: Project, item: gh.BoardItem, card: Card, status: Status,
                          run: Run) -> tuple[str | None, str]:
        agent = self.store.get_agent(status.agent_id or "")
        if agent is None:
            raise RuntimeError(f"agent '{status.agent_id}' not found")
        if agent.workspace == "none":
            cwd = self.data_dir / "scratch" / project.id
            cwd.mkdir(parents=True, exist_ok=True)
        else:
            cwd = await to_thread(self._worktree, project, card)
        prompt = await to_thread(self._prompt, project, item, card, agent, cwd)
        self._log(run, {"type": "info", "text": f"{agent.name} starting in {cwd}"})

        result = await run_agent(agent, prompt, cwd, on_log=lambda e: run.log.append(e))
        run.cost_usd, run.num_turns, run.session_id = result.cost_usd, result.num_turns, result.session_id

        if result.rate_limited_until and not result.outcome:
            self.paused_until = result.rate_limited_until
            self._log(run, {"type": "info", "text": "Usage limit reached; pausing until it resets."})
            if agent.workspace == "read":
                await to_thread(gitops.discard_changes, cwd)
            return None, ""
        if result.error and is_auth_error(result.error):
            # Not the card's fault: stop everything until the user logs in again.
            self.set_paused(True)
            self.last_error = ("Claude login problem; the worker was paused. Run `claude` in a terminal and use "
                               f"/login, then resume. ({result.error.splitlines()[0][:200]})")
            run.error = result.error
            if agent.workspace == "read":
                await to_thread(gitops.discard_changes, cwd)
            return None, ""
        if result.error or not result.outcome:
            run.error = result.error or "agent returned no outcome"
            self._note(card, f"Previous {agent.name} run failed: {run.error}")
            return ERROR, ""

        outcome, summary = result.outcome, result.summary
        card.last_output[agent.id] = {"outcome": outcome, "summary": summary}
        if agent.workspace != "none" and agent.post_checks:
            failed = await to_thread(self._post_checks, project, agent, cwd, outcome)
            if failed:
                self._log(run, {"type": "check_failed", "text": failed})
                self._note(card, f"Post-check failed after {agent.name} said '{outcome}': {failed}")
                return CHECK_FAILED, summary
        self._note(card, f"{agent.name} → {outcome}:\n{summary}")
        return outcome, summary

    def _post_checks(self, project: Project, agent: Agent, cwd: Path, outcome: str) -> str | None:
        # Checks guard the "work is finished" claims; a 'blocked' coder doesn't need commits.
        finishing = outcome in ("done", "approved") or len(agent.outcomes) == 1
        for check in agent.post_checks:
            if check == "clean_worktree" and not gitops.is_clean(cwd):
                if agent.workspace == "read":
                    gitops.discard_changes(cwd)  # enforce read-only: undo anything it touched
                    return f"the read-only {agent.name} modified files (changes were discarded)"
                return "uncommitted changes were left in the worktree"
            if not finishing:
                continue
            if check == "has_commits" and gitops.commits_ahead(cwd, project.base_branch) == 0:
                return "no commits on the branch"
            if check == "tests_pass":
                ok, tail = gitops.run_tests(cwd, project.test_command)
                if not ok:
                    return f"tests failed:\n```\n{tail}\n```"
        return None

    async def _work_action(self, project: Project, card: Card, status: Status, run: Run) -> tuple[str, str]:
        if status.action == "merge":
            return await to_thread(self._merge, project, card, run)
        raise RuntimeError(f"unknown action '{status.action}'")

    def _merge(self, project: Project, card: Card, run: Run) -> tuple[str, str]:
        if not card.pr_number or not card.branch:
            return "no_pr", "The card has no PR."
        wt = self._worktree(project, card)
        self._log(run, {"type": "info", "text": f"Rebasing {card.branch} on {project.base_branch}"})
        if not gitops.rebase_on_base(wt, project.base_branch):
            self._note(card, f"Merge: rebasing on {project.base_branch} hit conflicts. Rebase the branch on "
                             f"origin/{project.base_branch}, resolve the conflicts, run the tests, and commit.")
            return "conflict", "Rebase conflicts"
        ok, tail = gitops.run_tests(wt, project.test_command)
        if not ok:
            self._note(card, f"Merge: tests failed after rebasing on {project.base_branch}:\n```\n{tail}\n```")
            return "tests_failed", "Tests failed after rebase"
        gitops.push(wt, card.branch)
        gh.merge_pr(project.repo, card.pr_number)
        gitops.remove_worktree(project.local_path, wt, card.branch)
        self._log(run, {"type": "info", "text": f"Merged PR #{card.pr_number}"})
        return "merged", f"Merged PR #{card.pr_number}"

    def _apply_effects(self, project: Project, card: Card, status: Status, outcome: str, summary: str,
                       decision: Decision) -> None:
        for effect in decision.effects:
            if effect == "open_pr":
                wt = self._worktree(project, card)
                gitops.push(wt, card.branch)  # type: ignore[arg-type]
                card.pr_number = card.pr_number or gh.find_pr(project.repo, card.branch)  # type: ignore[arg-type]
                if card.pr_number is None:
                    body = f"{summary}\n\nCloses #{card.issue_number}\n\n_Opened by nodler._"
                    card.pr_number = gh.create_pr(
                        project.repo, card.branch, project.base_branch,  # type: ignore[arg-type]
                        f"{card.title} (#{card.issue_number})", body,
                    )
                else:
                    gh.comment_pr(project.repo, card.pr_number, f"**Updated by the coder**\n\n{summary}")
            elif effect == "post_review":
                body = f"**Review: {outcome.replace('_', ' ')}**\n\n{summary}\n\n_Posted by nodler (reviewer agent)._"
                if card.pr_number:
                    gh.comment_pr(project.repo, card.pr_number, body)
                else:
                    gh.comment_issue(project.repo, card.issue_number, body)  # type: ignore[arg-type]
            elif effect == "comment":
                gh.comment_issue(project.repo, card.issue_number, f"{summary}\n\n_Posted by nodler._")  # type: ignore[arg-type]

    def _move(self, project: Project, board: gh.Board, card: Card, workflow: Workflow, status: Status,
              outcome: str, decision: Decision) -> None:
        if decision.target is None:
            return
        target = workflow.status(decision.target)
        if target is None:
            raise RuntimeError(f"target status '{decision.target}' not in workflow")
        if target.id != status.id:
            gh.set_status(board, card.item_id, target.name)
        if self.store.get_setting("comment_moves", True):
            gh.comment_issue(
                project.repo, card.issue_number,  # type: ignore[arg-type]
                f"🤖 nodler: **{status.name}** → **{target.name}** ({decision.reason})",
            )

    # ------------------------------------------------------------------ prompts
    def _prompt(self, project: Project, item: gh.BoardItem, card: Card, agent: Agent, cwd: Path) -> str:
        parts = [f"# Card #{card.issue_number}: {card.title}", "", item.body.strip() or "(no description)", ""]
        if project.context.strip():
            parts += ["## Project context", project.context.strip(), ""]
        if agent.workspace != "none":
            parts += [f"Working directory: {cwd}", f"Branch: {card.branch} (base: {project.base_branch})", ""]
            if project.test_command:
                parts += [f"Test command: `{project.test_command}`", ""]
        notes = card.last_output.get("notes", [])
        if notes:
            parts += ["## History of this card (most recent last)", *[f"- {n}" for n in notes], ""]
        try:
            comments = gh.issue_comments(project.repo, card.issue_number) if card.issue_number else []
        except CommandError:
            comments = []
        human = [c for c in comments if not is_nodler_comment(c.get("body") or "")]
        if human:
            parts += ["## Comments from humans on the issue"]
            parts += [f"- {c.get('author', {}).get('login', '?')}: {c.get('body', '')[:2000]}" for c in human[-5:]]
            parts.append("")
        if agent.include_diff and agent.workspace != "none":
            diff = gitops.diff_vs_base(cwd, project.base_branch)
            parts += ["## Diff of this branch against the base branch", "```diff", diff or "(empty diff)", "```", ""]
        outcomes = "\n".join(f"- {o.name}: {o.description}" for o in agent.outcomes)
        parts += ["## Finish", "End by returning your outcome (one of the following) and a summary:", outcomes]
        return "\n".join(parts)
