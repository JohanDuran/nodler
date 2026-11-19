from pathlib import Path

from nodler.defaults import default_agents
from nodler.runner import build_options, make_guard, output_schema

AGENTS = {a.id: a for a in default_agents()}


def denied(result: dict) -> bool:
    return result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


async def test_guard_blocks_push_and_gh(tmp_path: Path):
    guard = make_guard(AGENTS["coder"], tmp_path)
    assert denied(await guard({"tool_name": "Bash", "tool_input": {"command": "git  push origin x"}}, None, None))
    assert denied(await guard({"tool_name": "Bash", "tool_input": {"command": "gh pr merge 3"}}, None, None))
    assert await guard({"tool_name": "Bash", "tool_input": {"command": "uv run pytest"}}, None, None) == {}


async def test_guard_keeps_writes_inside_worktree(tmp_path: Path):
    guard = make_guard(AGENTS["coder"], tmp_path)
    inside = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "a.py")}}
    outside = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path.parent / "evil.py")}}
    assert await guard(inside, None, None) == {}
    assert denied(await guard(outside, None, None))


async def test_reviewer_is_read_only(tmp_path: Path):
    guard = make_guard(AGENTS["reviewer"], tmp_path)
    assert denied(await guard({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "a.py")}}, None, None))
    opts = build_options(AGENTS["reviewer"], tmp_path)
    assert opts.tools == ["Read", "Glob", "Grep"]


def test_output_schema_lists_outcomes():
    schema = output_schema(AGENTS["reviewer"])
    assert schema["schema"]["properties"]["outcome"]["enum"] == ["approved", "changes_requested"]
