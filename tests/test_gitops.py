"""Git operations against a real temporary repo with a local bare 'origin'."""

from pathlib import Path

import pytest

from nodler import gitops
from nodler.proc import run


def git(cwd, *args):
    return run(["git", *args], cwd=str(cwd))


@pytest.fixture
def repo(tmp_path: Path):
    origin = tmp_path / "origin.git"
    run(["git", "init", "--bare", "-b", "main", str(origin)])
    clone = tmp_path / "clone"
    run(["git", "clone", str(origin), str(clone)])
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false")):
        git(clone, "config", k, v)
    (clone / "app.txt").write_text("line1\n")
    git(clone, "add", ".")
    git(clone, "commit", "-m", "init")
    git(clone, "push", "-u", "origin", "main")
    return tmp_path, clone


def commit(wt: Path, name: str, text: str, msg: str):
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false")):
        git(wt, "config", k, v)
    (wt / name).write_text(text)
    git(wt, "add", ".")
    git(wt, "commit", "-m", msg)


def test_worktree_commit_push_and_clean_rebase(repo):
    tmp, clone = repo
    branch = gitops.branch_name(7, "Add a Login Page!")
    assert branch == "nodler/7-add-a-login-page"
    wt = gitops.ensure_worktree(str(clone), tmp / "wts", branch, "main")
    assert gitops.ensure_worktree(str(clone), tmp / "wts", branch, "main") == wt  # reused
    assert gitops.commits_ahead(wt, "main") == 0
    commit(wt, "login.txt", "login\n", "add login")
    assert gitops.commits_ahead(wt, "main") == 1
    assert gitops.is_clean(wt)
    assert "login" in gitops.diff_vs_base(wt, "main")
    gitops.push(wt, branch)

    # main moves on with an unrelated change -> rebase is clean
    commit(clone, "other.txt", "x\n", "other")
    git(clone, "push", "origin", "main")
    assert gitops.rebase_on_base(wt, "main") is True


def test_rebase_conflict_is_detected_and_aborted(repo):
    tmp, clone = repo
    wt = gitops.ensure_worktree(str(clone), tmp / "wts", "nodler/1-x", "main")
    commit(wt, "app.txt", "branch version\n", "branch edit")
    commit(clone, "app.txt", "main version\n", "main edit")
    git(clone, "push", "origin", "main")
    assert gitops.rebase_on_base(wt, "main") is False
    assert gitops.is_clean(wt)  # rebase was aborted, worktree usable


def test_setup_command_runs_once_and_failure_cleans_up(repo):
    tmp, clone = repo
    wt = gitops.ensure_worktree(str(clone), tmp / "wts", "nodler/3-s", "main", setup_command="echo hi> setup.txt")
    assert (wt / "setup.txt").exists()
    (wt / "setup.txt").unlink()
    gitops.ensure_worktree(str(clone), tmp / "wts", "nodler/3-s", "main", setup_command="echo hi> setup.txt")
    assert not (wt / "setup.txt").exists()  # reused worktree: setup not re-run

    with pytest.raises(RuntimeError):
        gitops.ensure_worktree(str(clone), tmp / "wts", "nodler/4-f", "main", setup_command="exit 1")
    assert not (tmp / "wts" / "nodler_4-f").exists()


def test_discard_and_tests(repo):
    tmp, clone = repo
    wt = gitops.ensure_worktree(str(clone), tmp / "wts", "nodler/2-y", "main")
    (wt / "junk.txt").write_text("x")
    assert not gitops.is_clean(wt)
    gitops.discard_changes(wt)
    assert gitops.is_clean(wt)
    assert gitops.run_tests(wt, "")[0] is True
    assert gitops.run_tests(wt, "exit 0")[0] is True
    assert gitops.run_tests(wt, "exit 3")[0] is False
    gitops.remove_worktree(str(clone), wt, "nodler/2-y")
    assert not wt.exists()
