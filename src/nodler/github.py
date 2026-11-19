"""GitHub adapter (via the `gh` CLI): Projects v2 board, issues, PRs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .proc import CommandError, run


@dataclass
class BoardItem:
    item_id: str
    status: str | None
    title: str
    issue_number: int | None
    repo: str | None
    body: str = ""
    url: str = ""
    content_type: str = ""


@dataclass
class Board:
    project_id: str
    status_field_id: str
    options: dict[str, str] = field(default_factory=dict)  # lowercase name -> option id
    option_names: list[str] = field(default_factory=list)


def gh_json(args: list[str], cwd: str | None = None):
    return json.loads(run(["gh", *args], cwd=cwd).out or "null")


def auth_scopes() -> str:
    res = run(["gh", "auth", "status"], check=False)
    return res.out + res.err


def load_board(owner: str, number: int) -> Board:
    view = gh_json(["project", "view", str(number), "--owner", owner, "--format", "json"])
    fields = gh_json(["project", "field-list", str(number), "--owner", owner, "--format", "json"])
    status = next((f for f in fields.get("fields", []) if f.get("name", "").lower() == "status"), None)
    if status is None:
        raise CommandError("The project has no 'Status' field.")
    opts = status.get("options", [])
    return Board(
        project_id=view["id"],
        status_field_id=status["id"],
        options={o["name"].strip().lower(): o["id"] for o in opts},
        option_names=[o["name"] for o in opts],
    )


def list_items(owner: str, number: int, limit: int = 300) -> list[BoardItem]:
    data = gh_json(["project", "item-list", str(number), "--owner", owner, "--format", "json", "-L", str(limit)])
    items = []
    for it in data.get("items", []):
        content = it.get("content") or {}
        items.append(
            BoardItem(
                item_id=it["id"],
                status=it.get("status"),
                title=it.get("title") or content.get("title", ""),
                issue_number=content.get("number"),
                repo=content.get("repository"),
                body=content.get("body", ""),
                url=content.get("url", ""),
                content_type=content.get("type", ""),
            )
        )
    return items


def set_status(board: Board, item_id: str, status_name: str) -> None:
    option = board.options.get(status_name.strip().lower())
    if option is None:
        raise CommandError(f"Board has no Status option named '{status_name}'. Add it on GitHub.")
    run([
        "gh", "project", "item-edit", "--id", item_id, "--project-id", board.project_id,
        "--field-id", board.status_field_id, "--single-select-option-id", option,
    ])


def issue_comments(repo: str, number: int, last: int = 15) -> list[dict]:
    data = gh_json(["issue", "view", str(number), "--repo", repo, "--json", "comments"])
    return (data or {}).get("comments", [])[-last:]


def comment_issue(repo: str, number: int, body: str) -> None:
    run(["gh", "issue", "comment", str(number), "--repo", repo, "--body-file", "-"], input=body)


def find_pr(repo: str, branch: str) -> int | None:
    data = gh_json(["pr", "list", "--repo", repo, "--head", branch, "--state", "open", "--json", "number"])
    return data[0]["number"] if data else None


def create_pr(repo: str, branch: str, base: str, title: str, body: str) -> int:
    res = run(
        ["gh", "pr", "create", "--repo", repo, "--head", branch, "--base", base, "--title", title,
         "--body-file", "-"],
        input=body,
    )
    return int(res.out.strip().rstrip("/").split("/")[-1])


def comment_pr(repo: str, number: int, body: str) -> None:
    run(["gh", "pr", "comment", str(number), "--repo", repo, "--body-file", "-"], input=body)


def merge_pr(repo: str, number: int) -> None:
    run(["gh", "pr", "merge", str(number), "--repo", repo, "--squash", "--delete-branch"])
