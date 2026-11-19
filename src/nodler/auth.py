"""Guided logins: detect Claude / GitHub / git status and drive the official browser login flows.

nodler never sees passwords or tokens. It starts the vendors' own CLI login commands, shows the user the
URL and one-time code they print, and checks the status afterwards. Tokens stay where each CLI keeps them.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .proc import run

URL_RE = re.compile(r"https://[^\s'\"<>]+")
CODE_RE = re.compile(r"one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})")
GITHUB_SCOPES = ["project", "repo", "read:org"]

INSTALL_HINTS = {
    "git": {"windows": "winget install --id Git.Git -e", "url": "https://git-scm.com/downloads"},
    "gh": {"windows": "winget install --id GitHub.cli -e", "url": "https://cli.github.com/"},
}


# ---------------------------------------------------------------------------- binaries
def claude_binary() -> str | None:
    """The Claude Code binary the Agent SDK uses: the bundled one first, then PATH."""
    try:
        import claude_agent_sdk

        bundled = Path(claude_agent_sdk.__file__).parent / "_bundled"
        for name in ("claude.exe", "claude"):
            if (bundled / name).is_file():
                return str(bundled / name)
    except ImportError:
        pass
    return shutil.which("claude")


# ---------------------------------------------------------------------------- status
def claude_status() -> dict:
    exe = claude_binary()
    if exe is None:
        return {"installed": False, "logged_in": False}
    res = run([exe, "auth", "status"], check=False, timeout=60)
    try:
        data = json.loads(res.out)
    except json.JSONDecodeError:
        return {"installed": True, "logged_in": False, "error": (res.err or res.out).strip()[:300]}
    return {
        "installed": True,
        "logged_in": bool(data.get("loggedIn")),
        "method": data.get("authMethod"),
        "email": data.get("email"),
        "plan": data.get("planTier") or data.get("subscriptionType"),
        "expires_at": data.get("loginExpiresAt"),
    }


def parse_gh_status(text: str) -> dict:
    account = re.search(r"Logged in to github\.com account (\S+)", text)
    scopes_line = re.search(r"Token scopes:\s*(.*)", text)
    scopes = re.findall(r"'([^']+)'", scopes_line.group(1)) if scopes_line else []
    logged_in = account is not None and "Failed to log in" not in text
    return {
        "logged_in": logged_in,
        "account": account.group(1) if account else None,
        "scopes": scopes,
        "missing_scopes": [s for s in GITHUB_SCOPES if s not in scopes] if logged_in else GITHUB_SCOPES,
    }


def github_status() -> dict:
    if shutil.which("gh") is None:
        return {"installed": False, "logged_in": False, "install": INSTALL_HINTS["gh"]}
    res = run(["gh", "auth", "status", "--hostname", "github.com"], check=False, timeout=60)
    return {"installed": True, **parse_gh_status(res.out + res.err)}


def git_status() -> dict:
    if shutil.which("git") is None:
        return {"installed": False, "install": INSTALL_HINTS["git"]}
    return {"installed": True, "version": run(["git", "--version"], check=False).out.strip()}


def setup_status() -> dict:
    claude, github, git = claude_status(), github_status(), git_status()
    ready = (
        claude.get("logged_in", False)
        and github.get("logged_in", False)
        and not github.get("missing_scopes")
        and git.get("installed", False)
    )
    return {"claude": claude, "github": github, "git": git, "ready": ready}


# ---------------------------------------------------------------------------- login sessions
@dataclass
class LoginSession:
    id: str
    provider: str  # "claude" | "github"
    args: list[str]
    state: str = "starting"  # starting | waiting | succeeded | failed | cancelled
    url: str | None = None
    code: str | None = None
    output: list[str] = field(default_factory=list)
    message: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    _proc: subprocess.Popen | None = None

    def public(self) -> dict:
        return {
            "id": self.id, "provider": self.provider, "state": self.state, "url": self.url, "code": self.code,
            "message": self.message, "output": self.output[-20:], "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class LoginManager:
    """Runs at most one login per provider; the UI polls it."""

    TIMEOUT = 15 * 60

    def __init__(self, verify=None):
        self.sessions: dict[str, LoginSession] = {}
        self._lock = threading.Lock()
        self._verify = verify or {"claude": lambda: claude_status().get("logged_in", False),
                                  "github": lambda: not github_status().get("missing_scopes", ["x"])}

    def current(self, provider: str) -> LoginSession | None:
        with self._lock:
            found = [s for s in self.sessions.values() if s.provider == provider]
        return max(found, key=lambda s: s.started_at) if found else None

    def start(self, provider: str, args: list[str] | None = None) -> LoginSession:
        existing = self.current(provider)
        if existing and existing.state in ("starting", "waiting"):
            return existing
        args = args or self.default_args(provider)
        session = LoginSession(id=uuid.uuid4().hex[:10], provider=provider, args=args)
        with self._lock:
            self.sessions[session.id] = session
        try:
            session._proc = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as exc:
            session.state, session.message, session.finished_at = "failed", str(exc), time.time()
            return session
        session.state = "waiting"
        threading.Thread(target=self._follow, args=(session,), daemon=True).start()
        return session

    def default_args(self, provider: str) -> list[str]:
        if provider == "claude":
            exe = claude_binary()
            if exe is None:
                raise RuntimeError("Claude Code is not available (the claude-agent-sdk package should bundle it)")
            return [exe, "auth", "login", "--claudeai"]
        if provider == "github":
            if shutil.which("gh") is None:
                raise RuntimeError("GitHub CLI (gh) is not installed")
            status = github_status()
            if status.get("logged_in"):  # just add the missing permissions
                return ["gh", "auth", "refresh", "--hostname", "github.com", "--scopes", ",".join(GITHUB_SCOPES)]
            return ["gh", "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web",
                    "--scopes", ",".join(GITHUB_SCOPES)]
        raise ValueError(f"unknown provider {provider}")

    def send_input(self, session_id: str, text: str) -> LoginSession:
        """For flows that ask the user to paste a code back (e.g. Claude's manual fallback)."""
        session = self.sessions[session_id]
        if session._proc and session._proc.stdin and session.state == "waiting":
            session._proc.stdin.write(text.strip() + "\n")
            session._proc.stdin.flush()
        return session

    def cancel(self, session_id: str) -> LoginSession:
        session = self.sessions[session_id]
        if session._proc and session._proc.poll() is None:
            session._proc.kill()
        if session.state in ("starting", "waiting"):
            session.state, session.finished_at = "cancelled", time.time()
        return session

    def _follow(self, session: LoginSession) -> None:
        proc = session._proc
        assert proc is not None and proc.stdout is not None
        killer = threading.Timer(self.TIMEOUT, lambda: proc.poll() is None and proc.kill())
        killer.start()
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                session.output.append(line)
                if session.code is None and (m := CODE_RE.search(line)):
                    session.code = m.group(1)
                if session.url is None and (m := URL_RE.search(line)):
                    session.url = m.group(0).rstrip(".,)")
            code = proc.wait()
        finally:
            killer.cancel()
        if session.state == "cancelled":
            return
        ok = code == 0 and self._verify[session.provider]()
        session.state = "succeeded" if ok else "failed"
        if not ok:
            session.message = (session.output[-1] if session.output else f"exited with code {code}")[:300]
        session.finished_at = time.time()
