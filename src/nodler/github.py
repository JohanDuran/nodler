"""GitHub adapter (via the `gh` CLI): Projects v2 board, issues, PRs."""

from __future__ import annotations

import json
import time
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


def status_query(statuses: list[str]) -> str:
    """Projects filter syntax for 'Status is any of these', e.g. status:Ready,"In Review"."""
    return "status:" + ",".join(f'"{s}"' if " " in s else s for s in statuses)


def is_rate_limited(message: str) -> bool:
    """True when a gh failure is GitHub's API rate limit.

    `gh project ...` hides it behind "unknown owner type" (its owner lookup fails), so that case is
    confirmed with a tiny GraphQL query, which costs nothing when the limit is hit.
    """
    text = message.lower()
    if "rate limit" in text:
        return True
    if "unknown owner type" in text:
        res = run(["gh", "api", "graphql", "-f", "query=query { viewer { login } }"], check=False)
        return "rate_limit" in (res.out + res.err).lower() or "rate limit" in (res.out + res.err).lower()
    return False


def graphql_reset_time() -> float:
    """When the GraphQL budget resets (the REST rate_limit endpoint itself is free)."""
    try:
        data = gh_json(["api", "rate_limit"])
        return float(data["resources"]["graphql"]["reset"]) + 5
    except Exception:  # noqa: BLE001 - be conservative if we can't tell
        return time.time() + 900


def list_items(owner: str, number: int, limit: int = 100, statuses: list[str] | None = None) -> list[BoardItem]:
    args = ["project", "item-list", str(number), "--owner", owner, "--format", "json", "-L", str(limit)]
    if statuses:
        args += ["--query", status_query(statuses)]
    data = gh_json(args)
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


def list_repos(limit: int = 200) -> list[dict]:
    """Repos the logged-in user can push to (their own and their orgs')."""
    data = gh_json(["repo", "list", "--limit", str(limit), "--json",
                    "nameWithOwner,description,isPrivate,defaultBranchRef,updatedAt"])
    return [
        {"repo": r["nameWithOwner"], "description": r.get("description") or "", "private": r["isPrivate"],
         "default_branch": (r.get("defaultBranchRef") or {}).get("name") or "main", "updated_at": r["updatedAt"]}
        for r in data or []
    ]


STATUS_COLORS = ["GRAY", "BLUE", "PURPLE", "YELLOW", "GREEN", "RED", "ORANGE", "PINK"]

SET_OPTIONS_MUTATION = """
mutation($field: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
  updateProjectV2Field(input: {fieldId: $field, singleSelectOptions: $options}) {
    projectV2Field { ... on ProjectV2SingleSelectField { id } }
  }
}
"""


def create_board(owner: str, title: str, repo: str, status_names: list[str]) -> tuple[int, str]:
    """Create a NEW GitHub Project linked to ``repo`` whose Status column options are ``status_names``.

    Only ever used on a board nodler just created: replacing Status options on a board with items
    would clear their status.
    """
    created = gh_json(["project", "create", "--owner", owner, "--title", title, "--format", "json"])
    number = int(created["number"])
    run(["gh", "project", "link", str(number), "--owner", owner, "--repo", repo])
    fields = gh_json(["project", "field-list", str(number), "--owner", owner, "--format", "json"])
    status = next(f for f in fields["fields"] if f.get("name", "").lower() == "status")
    options = [
        {"name": n, "color": STATUS_COLORS[i % len(STATUS_COLORS)], "description": ""}
        for i, n in enumerate(status_names)
    ]
    run(["gh", "api", "graphql", "--input", "-"],
        input=json.dumps({"query": SET_OPTIONS_MUTATION, "variables": {"field": status["id"], "options": options}}))
    return number, created.get("url", "")
