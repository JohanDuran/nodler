"""Git operations: one worktree + branch per card, rebases, pushes, tests."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .proc import run


def slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "card"


def branch_name(issue_number: int | None, title: str) -> str:
    return f"nodler/{issue_number or 'x'}-{slug(title)}"


def ensure_worktree(clone: str, worktrees_root: Path, branch: str, base: str, setup_command: str = "") -> Path:
    """Create (or reuse) a worktree for ``branch``, branched from origin/<base>.

    ``setup_command`` (e.g. ``npm ci``) runs once, right after the worktree is created.
    """
    path = worktrees_root / branch.replace("/", "_")
    if path.exists() and (path / ".git").exists():
        return path
    worktrees_root.mkdir(parents=True, exist_ok=True)
    run(["git", "fetch", "origin", base], cwd=clone)
    run(["git", "worktree", "prune"], cwd=clone)
    exists = run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=clone, check=False).ok
    if exists:
        run(["git", "worktree", "add", str(path), branch], cwd=clone)
    else:
        run(["git", "worktree", "add", "-b", branch, str(path), f"origin/{base}"], cwd=clone)
    if setup_command.strip():
        res = run(setup_command, cwd=str(path), check=False, shell=True, timeout=1800)
        if not res.ok:
            run(["git", "worktree", "remove", "--force", str(path)], cwd=clone, check=False)
            shutil.rmtree(path, ignore_errors=True)
            run(["git", "worktree", "prune"], cwd=clone, check=False)
            if not exists:  # only delete a branch we just created
                run(["git", "branch", "-D", branch], cwd=clone, check=False)
            raise RuntimeError(f"setup command `{setup_command}` failed:\n{(res.out + res.err)[-3000:]}")
    return path


def remove_worktree(clone: str, path: Path, branch: str) -> None:
    run(["git", "worktree", "remove", "--force", str(path)], cwd=clone, check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    run(["git", "worktree", "prune"], cwd=clone, check=False)
    run(["git", "branch", "-D", branch], cwd=clone, check=False)


def commits_ahead(wt: Path, base: str) -> int:
    run(["git", "fetch", "origin", base], cwd=str(wt), check=False)
    res = run(["git", "rev-list", "--count", f"origin/{base}..HEAD"], cwd=str(wt))
    return int(res.out.strip() or 0)


def is_clean(wt: Path) -> bool:
    return run(["git", "status", "--porcelain"], cwd=str(wt)).out.strip() == ""


def discard_changes(wt: Path) -> None:
    run(["git", "reset", "--hard", "HEAD"], cwd=str(wt), check=False)
    run(["git", "clean", "-fd"], cwd=str(wt), check=False)


def diff_vs_base(wt: Path, base: str, max_chars: int = 80_000) -> str:
    out = run(["git", "diff", f"origin/{base}...HEAD"], cwd=str(wt)).out
    if len(out) > max_chars:
        out = out[:max_chars] + f"\n\n[diff truncated at {max_chars} characters]"
    return out


def run_tests(wt: Path, command: str, timeout: int = 1800) -> tuple[bool, str]:
    if not command.strip():
        return True, "(no test command configured)"
    res = run(command, cwd=str(wt), check=False, shell=True, timeout=timeout)
    tail = (res.out + "\n" + res.err)[-4000:]
    return res.ok, tail


def push(wt: Path, branch: str) -> None:
    run(["git", "push", "--force-with-lease", "-u", "origin", branch], cwd=str(wt))


def rebase_on_base(wt: Path, base: str) -> bool:
    """Rebase onto origin/<base>. Returns False (and aborts) on conflicts."""
    run(["git", "fetch", "origin", base], cwd=str(wt))
    res = run(["git", "rebase", f"origin/{base}"], cwd=str(wt), check=False)
    if not res.ok:
        run(["git", "rebase", "--abort"], cwd=str(wt), check=False)
        return False
    return True
