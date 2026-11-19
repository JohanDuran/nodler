"""Workflow validation: catches broken state machines before they are saved."""

from __future__ import annotations

from .catalog import ACTIONS
from .engine import possible_outcomes
from .models import Agent, Workflow


def validate_workflow(workflow: Workflow, agents: dict[str, Agent]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block saving; warnings are shown in the UI."""
    errors: list[str] = []
    warnings: list[str] = []
    ids = [s.id for s in workflow.statuses]
    names = [s.name.strip().lower() for s in workflow.statuses]

    if len(set(ids)) != len(ids):
        errors.append("Status ids must be unique.")
    if len(set(names)) != len(names):
        errors.append("Status names must be unique (they map to board columns).")
    if workflow.fallback_status not in ids:
        errors.append("The fallback status must be one of the workflow's statuses.")
    elif workflow.status(workflow.fallback_status).kind != "human":  # type: ignore[union-attr]
        warnings.append("The fallback status should be a human status (e.g. 'Needs human').")

    for s in workflow.statuses:
        if s.kind == "agent":
            if not s.agent_id:
                errors.append(f"Status '{s.name}' is an agent status but has no agent.")
            elif s.agent_id not in agents:
                errors.append(f"Status '{s.name}' uses unknown agent '{s.agent_id}'.")
        if s.kind == "action" and s.action not in ACTIONS:
            errors.append(f"Status '{s.name}' uses unknown action '{s.action}'.")

    for t in workflow.transitions:
        if t.source not in ids or t.target not in ids:
            errors.append(f"Transition '{t.id}' points to a missing status.")
            continue
        if t.outcome not in possible_outcomes(workflow, t.source, agents):
            errors.append(
                f"Transition from '{workflow.status(t.source).name}' uses outcome '{t.outcome}', "  # type: ignore[union-attr]
                "which that status cannot produce."
            )
    seen = set()
    for t in workflow.transitions:
        key = (t.source, t.outcome)
        if key in seen:
            errors.append(f"Two transitions handle outcome '{t.outcome}' from the same status.")
        seen.add(key)

    for r in workflow.rules:
        if r.target not in ids or (r.status is not None and r.status not in ids):
            errors.append(f"Rule '{r.id}' points to a missing status.")

    # Every outcome of a worked status should have somewhere to go.
    for s in workflow.statuses:
        if s.kind not in ("agent", "action"):
            continue
        handled = {t.outcome for t in workflow.transitions if t.source == s.id}
        for outcome in possible_outcomes(workflow, s.id, agents):
            if outcome not in handled:
                warnings.append(
                    f"Outcome '{outcome}' of '{s.name}' has no transition; it will go to the fallback status."
                )

    if not any(s.kind == "done" for s in workflow.statuses):
        warnings.append("No 'done' status: cards can never finish.")
    return errors, warnings
