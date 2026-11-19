"""Pure state-machine logic. No I/O: given a workflow, a card and an outcome, decide where it goes."""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import ACTIONS
from .models import CHECK_FAILED, ERROR, Agent, Card, Workflow


@dataclass
class Decision:
    target: str | None  # status id to move to; None = stay where it is (retry later)
    effects: list[str] = field(default_factory=list)
    reason: str = ""


def possible_outcomes(workflow: Workflow, status_id: str, agents: dict[str, Agent]) -> list[str]:
    """Outcomes a status can produce (what the editor lets you draw arrows for)."""
    status = workflow.status(status_id)
    if status is None:
        return []
    if status.kind == "agent":
        agent = agents.get(status.agent_id or "")
        if agent is None:
            return []
        outs = [o.name for o in agent.outcomes]
        if agent.post_checks:
            outs.append(CHECK_FAILED)
        return outs
    if status.kind == "action":
        return list(ACTIONS.get(status.action or "", {}).get("outcomes", {}))
    return []


def decide(workflow: Workflow, card: Card, status_id: str, outcome: str) -> Decision:
    """Where does a card go after ``outcome`` in ``status_id``?"""
    if outcome == ERROR:
        return decide_error(workflow, card, status_id)

    transition = next(
        (t for t in workflow.transitions if t.source == status_id and t.outcome == outcome),
        None,
    )
    if transition is None:
        return Decision(
            target=workflow.fallback_status,
            reason=f"no transition for outcome '{outcome}' from '{_name(workflow, status_id)}'",
        )

    target = transition.target
    reason = f"'{outcome}' → '{_name(workflow, target)}'"
    visits = card.visits.get(target, 0) + 1
    for rule in workflow.rules:
        if rule.type == "max_visits" and rule.status in (None, target) and visits > rule.limit:
            return Decision(
                target=rule.target,
                effects=list(transition.effects),
                reason=(
                    f"'{_name(workflow, target)}' visited {visits} times (limit {rule.limit}) "
                    f"→ '{_name(workflow, rule.target)}'"
                ),
            )
    return Decision(target=target, effects=list(transition.effects), reason=reason)


def decide_error(workflow: Workflow, card: Card, status_id: str) -> Decision:
    errors = card.errors.get(status_id, 0) + 1
    for rule in workflow.rules:
        if rule.type == "max_errors" and rule.status in (None, status_id) and errors >= rule.limit:
            return Decision(
                target=rule.target,
                reason=f"{errors} errors in '{_name(workflow, status_id)}' (limit {rule.limit})",
            )
    return Decision(target=None, reason=f"error #{errors} in '{_name(workflow, status_id)}', will retry")


def apply(card: Card, status_id: str, outcome: str, decision: Decision) -> None:
    """Update the card's counters after a decision (mutates ``card``)."""
    if outcome == ERROR:
        card.errors[status_id] = card.errors.get(status_id, 0) + 1
    else:
        card.errors.pop(status_id, None)
    if decision.target is not None:
        card.visits[decision.target] = card.visits.get(decision.target, 0) + 1
        card.status_id = decision.target


def _name(workflow: Workflow, status_id: str) -> str:
    s = workflow.status(status_id)
    return s.name if s else status_id
