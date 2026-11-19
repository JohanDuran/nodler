from nodler.defaults import default_agents, default_workflow
from nodler.engine import apply, decide, possible_outcomes
from nodler.models import ERROR, Card
from nodler.validate import validate_workflow

AGENTS = {a.id: a for a in default_agents()}


def card() -> Card:
    return Card(item_id="i1", project_id="p", workflow_id="default", workflow_version=1, status_id="ready")


def test_default_workflow_is_valid():
    errors, warnings = validate_workflow(default_workflow(), AGENTS)
    assert errors == []
    assert warnings == []


def test_happy_path():
    wf, c = default_workflow(), card()
    d = decide(wf, c, "ready", "done")
    assert d.target == "review" and d.effects == ["open_pr"]
    apply(c, "ready", "done", d)
    d = decide(wf, c, "review", "approved")
    assert d.target == "merge" and d.effects == ["post_review"]
    apply(c, "review", "approved", d)
    assert decide(wf, c, "merge", "merged").target == "done"


def test_bounce_limit_sends_to_human():
    wf, c = default_workflow(), card()
    for _ in range(3):  # three rework round trips are allowed
        d = decide(wf, c, "review", "changes_requested")
        assert d.target == "ready"
        apply(c, "review", "changes_requested", d)
    d = decide(wf, c, "review", "changes_requested")
    assert d.target == "human"
    assert d.effects == ["post_review"]  # the review is still posted
    assert "limit 3" in d.reason


def test_unknown_outcome_goes_to_fallback():
    d = decide(default_workflow(), card(), "ready", "something_weird")
    assert d.target == "human"


def test_errors_retry_then_escalate():
    wf, c = default_workflow(), card()
    for _ in range(2):
        d = decide(wf, c, "ready", ERROR)
        assert d.target is None
        apply(c, "ready", ERROR, d)
    d = decide(wf, c, "ready", ERROR)
    assert d.target == "human"


def test_success_resets_error_count():
    wf, c = default_workflow(), card()
    apply(c, "ready", ERROR, decide(wf, c, "ready", ERROR))
    apply(c, "ready", "done", decide(wf, c, "ready", "done"))
    assert c.errors == {}


def test_possible_outcomes():
    wf = default_workflow()
    assert possible_outcomes(wf, "ready", AGENTS) == ["done", "blocked", "check_failed"]
    assert possible_outcomes(wf, "merge", AGENTS) == ["merged", "conflict", "tests_failed", "no_pr"]
    assert possible_outcomes(wf, "backlog", AGENTS) == []


def test_validator_catches_problems():
    wf = default_workflow()
    wf.transitions[0].outcome = "approved"  # coder can't produce this
    wf.statuses[1].agent_id = "ghost"
    errors, _ = validate_workflow(wf, AGENTS)
    assert any("unknown agent" in e for e in errors)
