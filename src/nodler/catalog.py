"""Static catalog of built-in actions, effects, checks and tools (used by engine, validator and UI)."""

ACTIONS: dict[str, dict] = {
    "merge": {
        "description": "Rebase the card's branch on the base branch, re-run tests, and merge the PR.",
        "outcomes": {
            "merged": "PR merged into the base branch",
            "conflict": "Rebase hit conflicts; the coder must resolve them",
            "tests_failed": "Tests failed after rebasing",
            "no_pr": "The card has no PR to merge",
        },
    },
}

EFFECTS: dict[str, str] = {
    "open_pr": "Push the card's branch and open (or update) its PR",
    "post_review": "Post the agent's review as a PR comment",
    "comment": "Post the agent's summary as an issue comment",
}

POST_CHECKS: dict[str, str] = {
    "has_commits": "The branch has at least one commit ahead of the base branch",
    "tests_pass": "The project's test command exits with code 0",
    "clean_worktree": "No uncommitted changes are left in the worktree",
}

BUILTIN_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write", "Bash", "WebSearch", "WebFetch"]

# Commands no agent may run, whatever its configuration: nodler does git pushes, PRs and merges itself.
ALWAYS_BLOCKED = [
    "git push",
    "gh ",
    "git remote",
    "git checkout main",
    "git reset --hard origin",
    "rm -rf /",
    "rm -rf ~",
    "format c:",
]
