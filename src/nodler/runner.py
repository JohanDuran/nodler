"""Runs one agent through the Claude Agent SDK with hard role enforcement."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    RateLimitEvent,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from .catalog import ALWAYS_BLOCKED
from .models import Agent


@dataclass
class AgentResult:
    outcome: str | None = None
    summary: str = ""
    error: str | None = None
    cost_usd: float | None = None
    num_turns: int | None = None
    session_id: str | None = None
    rate_limited_until: float | None = None  # unix time; set when the plan's usage limit was hit
    log: list[dict] = field(default_factory=list)


def output_schema(agent: Agent) -> dict:
    return {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "enum": [o.name for o in agent.outcomes]},
                "summary": {"type": "string"},
            },
            "required": ["outcome", "summary"],
            "additionalProperties": False,
        },
    }


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def make_guard(agent: Agent, cwd: Path) -> Callable:
    """PreToolUse hook: blocks forbidden shell commands and writes outside the worktree."""
    blocked = [b.lower() for b in ALWAYS_BLOCKED + agent.blocked_commands]
    root = cwd.resolve()

    async def guard(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict:
        tool = input_data.get("tool_name", "")
        args = input_data.get("tool_input", {}) or {}
        if tool == "Bash":
            cmd = " ".join(str(args.get("command", "")).lower().split())
            for b in blocked:
                if b in cmd:
                    return _deny(f"nodler policy: '{b.strip()}' is not allowed for the {agent.name} role.")
        if tool in ("Edit", "Write", "NotebookEdit"):
            if agent.workspace != "write":
                return _deny(f"nodler policy: the {agent.name} role is read-only.")
            target = Path(str(args.get("file_path", ""))).expanduser()
            target = (target if target.is_absolute() else root / target).resolve()
            if not target.is_relative_to(root):
                return _deny("nodler policy: you may only modify files inside your worktree.")
        return {}

    return guard


def build_options(agent: Agent, cwd: Path, stderr: Callable[[str], None] | None = None) -> ClaudeAgentOptions:
    guard = make_guard(agent, cwd)
    return ClaudeAgentOptions(
        tools=list(agent.tools),  # hard limit: the agent cannot see other tools at all
        allowed_tools=list(agent.tools),  # ...and the ones it has run without prompting
        permission_mode=agent.permission_mode,
        system_prompt=agent.system_prompt,
        model=agent.model,
        effort=agent.effort,
        max_turns=agent.max_turns,
        cwd=str(cwd),
        output_format=output_schema(agent),
        setting_sources=["project"],  # load the target repo's CLAUDE.md / project settings
        hooks={"PreToolUse": [HookMatcher(matcher="Bash|Edit|Write|NotebookEdit", hooks=[guard], on_failure="block")]},
        verbatim_prompts=True,  # card text is not trusted: no @file expansion or slash commands
        client_app="nodler/0.1",
        stderr=stderr,
    )


def _short(text: str, n: int = 2000) -> str:
    return text if len(text) <= n else text[:n] + " …"


async def run_agent(agent: Agent, prompt: str, cwd: Path, on_log: Callable[[dict], None] | None = None) -> AgentResult:
    result = AgentResult()

    def log(entry: dict) -> None:
        entry["t"] = time.time()
        result.log.append(entry)
        if on_log:
            on_log(entry)

    stderr_lines: list[str] = []
    options = build_options(agent, cwd, stderr=lambda line: stderr_lines.append(line))
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        log({"type": "text", "text": _short(block.text)})
                    elif isinstance(block, ToolUseBlock):
                        log({"type": "tool", "name": block.name, "input": _short(str(block.input), 500)})
            elif isinstance(message, RateLimitEvent):
                info = message.rate_limit_info
                log({"type": "rate_limit", "status": info.status, "kind": info.rate_limit_type,
                     "resets_at": info.resets_at, "utilization": info.utilization})
                if info.status == "rejected":
                    result.rate_limited_until = float(info.resets_at or time.time() + 1800)
            elif isinstance(message, ResultMessage):
                result.cost_usd = message.total_cost_usd
                result.num_turns = message.num_turns
                result.session_id = message.session_id
                data = message.structured_output
                if message.is_error or not isinstance(data, dict):
                    detail = "; ".join(message.errors or []) or message.result or message.subtype
                    result.error = f"agent run failed: {detail}"
                else:
                    result.outcome = data.get("outcome")
                    result.summary = data.get("summary", "")
                log({"type": "result", "subtype": message.subtype, "outcome": result.outcome,
                     "error": result.error, "cost_usd": result.cost_usd, "turns": result.num_turns})
    except Exception as exc:  # CLI crash, connection error, ...
        result.error = f"{type(exc).__name__}: {exc}"
        if stderr_lines:
            result.error += "\n" + "\n".join(stderr_lines[-20:])
        log({"type": "error", "text": _short(result.error)})
    if result.rate_limited_until and not result.outcome:
        result.error = result.error or "usage limit reached"
    return result


def api_key_in_env() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
