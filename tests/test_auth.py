import json
import sys
import time

from nodler.auth import LoginManager, parse_gh_status
from nodler.detect import detect_commands

GH_OK = """github.com
  ✓ Logged in to github.com account octo (keyring)
  - Active account: true
  - Token scopes: 'gist', 'project', 'read:org', 'repo', 'workflow'
"""


def test_parse_gh_status():
    s = parse_gh_status(GH_OK)
    assert s["logged_in"] and s["account"] == "octo" and s["missing_scopes"] == []
    s = parse_gh_status(GH_OK.replace("'project', ", ""))
    assert s["missing_scopes"] == ["project"]
    s = parse_gh_status("You are not logged into any GitHub hosts. To log in, run: gh auth login")
    assert not s["logged_in"] and s["missing_scopes"] == ["project", "repo", "read:org"]


def wait_done(mgr: LoginManager, provider: str, timeout: float = 10):
    end = time.time() + timeout
    while time.time() < end:
        s = mgr.current(provider)
        if s and s.state not in ("starting", "waiting"):
            return s
        time.sleep(0.05)
    raise AssertionError("login did not finish")


def fake(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_device_flow_code_and_url_are_captured_and_verified():
    mgr = LoginManager(verify={"github": lambda: True})
    script = ("print('! First copy your one-time code: 585B-BD04'); "
              "print('Open this URL to continue in your web browser: https://github.com/login/device')")
    mgr.start("github", fake(script))
    s = wait_done(mgr, "github")
    assert s.state == "succeeded"
    assert s.code == "585B-BD04"
    assert s.url == "https://github.com/login/device"


def test_failed_verification_marks_failed():
    mgr = LoginManager(verify={"claude": lambda: False})
    mgr.start("claude", fake("print('Opening https://claude.ai/oauth/authorize?x=1')"))
    s = wait_done(mgr, "claude")
    assert s.state == "failed" and s.url.startswith("https://claude.ai/oauth")


def test_input_is_forwarded_and_cancel_works():
    mgr = LoginManager(verify={"claude": lambda: True})
    s = mgr.start("claude", fake("import sys; print('Paste code here:', flush=True); print('got', input())"))
    time.sleep(0.5)
    mgr.send_input(s.id, "ABC123")
    s = wait_done(mgr, "claude")
    assert s.state == "succeeded" and "got ABC123" in s.output

    s2 = mgr.start("claude", fake("import time; time.sleep(30)"))
    assert mgr.start("claude", fake("print(1)")).id == s2.id  # one login per provider at a time
    mgr.cancel(s2.id)
    assert mgr.current("claude").state == "cancelled"


def test_detect_commands(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "typecheck": "tsc"}}))
    (tmp_path / "package-lock.json").write_text("{}")
    d = detect_commands(tmp_path)
    assert d["setup_command"].startswith("npm ci")
    assert d["test_command"] == "npm run typecheck && npm test"

    py = tmp_path / "py"
    (py / "tests").mkdir(parents=True)
    (py / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert detect_commands(py) == {"setup_command": "uv sync", "test_command": "uv run pytest", "stack": "Python"}
    assert detect_commands(tmp_path / "missing")["stack"] == ""
