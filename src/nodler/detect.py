"""Guess a repo's setup and test commands so non-technical users don't have to know them."""

from __future__ import annotations

import json
from pathlib import Path


def detect_commands(path: Path) -> dict[str, str]:
    """Return {"setup_command", "test_command", "stack"} for a local clone (empty strings when unknown)."""
    pkg = path / "package.json"
    if pkg.exists():
        try:
            scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
        except (json.JSONDecodeError, OSError):
            scripts = {}
        if (path / "pnpm-lock.yaml").exists():
            setup, runner = "pnpm install --frozen-lockfile", "pnpm"
        elif (path / "yarn.lock").exists():
            setup, runner = "yarn install --frozen-lockfile", "yarn"
        elif (path / "package-lock.json").exists():
            setup, runner = "npm ci --no-audit --no-fund", "npm"
        else:
            setup, runner = "npm install --no-audit --no-fund", "npm"
        steps = []
        if "typecheck" in scripts:
            steps.append(f"{runner} run typecheck")
        if "lint" in scripts:
            steps.append(f"{runner} run lint")
        if "test" in scripts and "no test specified" not in scripts["test"]:
            steps.append(f"{runner} test")
        return {"setup_command": setup, "test_command": " && ".join(steps), "stack": "Node.js"}

    if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists():
        has_tests = (path / "tests").is_dir() or any(path.glob("test_*.py"))
        if (path / "uv.lock").exists() or (path / "pyproject.toml").exists():
            return {"setup_command": "uv sync", "test_command": "uv run pytest" if has_tests else "",
                    "stack": "Python"}
        return {"setup_command": "pip install -r requirements.txt",
                "test_command": "python -m pytest" if has_tests else "", "stack": "Python"}

    if (path / "go.mod").exists():
        return {"setup_command": "go mod download", "test_command": "go test ./...", "stack": "Go"}
    if (path / "Cargo.toml").exists():
        return {"setup_command": "cargo fetch", "test_command": "cargo test", "stack": "Rust"}
    return {"setup_command": "", "test_command": "", "stack": ""}
