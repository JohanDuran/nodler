"""SQLite persistence. Every entity is stored as a JSON document; workflows are versioned."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .defaults import default_agents, default_workflow
from .models import Agent, Card, Project, Run, Workflow

T = TypeVar("T", bound=BaseModel)

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec')),
    PRIMARY KEY (id, version)
);
CREATE TABLE IF NOT EXISTS cards (item_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, item_id TEXT NOT NULL,
    started_at REAL NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_started ON runs (started_at DESC);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self._seed()

    def _seed(self) -> None:
        if not self.list_agents():
            for agent in default_agents():
                self.save_agent(agent)
        if not self.list_workflows():
            self.save_workflow(default_workflow())

    # -- generic helpers
    def _exec(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
            self._db.commit()
            return rows

    def _get(self, table: str, key: str, model: type[T], key_col: str = "id") -> T | None:
        rows = self._exec(f"SELECT data FROM {table} WHERE {key_col} = ?", (key,))
        return model.model_validate_json(rows[0][0]) if rows else None

    # -- projects
    def list_projects(self) -> list[Project]:
        return [Project.model_validate_json(r[0]) for r in self._exec("SELECT data FROM projects ORDER BY id")]

    def get_project(self, project_id: str) -> Project | None:
        return self._get("projects", project_id, Project)

    def save_project(self, project: Project) -> None:
        self._exec("INSERT OR REPLACE INTO projects VALUES (?, ?)", (project.id, project.model_dump_json()))

    def delete_project(self, project_id: str) -> None:
        self._exec("DELETE FROM projects WHERE id = ?", (project_id,))

    # -- agents
    def list_agents(self) -> list[Agent]:
        return [Agent.model_validate_json(r[0]) for r in self._exec("SELECT data FROM agents ORDER BY id")]

    def agents_by_id(self) -> dict[str, Agent]:
        return {a.id: a for a in self.list_agents()}

    def get_agent(self, agent_id: str) -> Agent | None:
        return self._get("agents", agent_id, Agent)

    def save_agent(self, agent: Agent) -> None:
        self._exec("INSERT OR REPLACE INTO agents VALUES (?, ?)", (agent.id, agent.model_dump_json()))

    def delete_agent(self, agent_id: str) -> None:
        self._exec("DELETE FROM agents WHERE id = ?", (agent_id,))

    # -- workflows (append-only versions)
    def list_workflows(self) -> list[Workflow]:
        """Latest version of each workflow."""
        rows = self._exec(
            "SELECT w.data FROM workflows w JOIN (SELECT id, MAX(version) v FROM workflows GROUP BY id) m "
            "ON w.id = m.id AND w.version = m.v ORDER BY w.id"
        )
        return [Workflow.model_validate_json(r[0]) for r in rows]

    def get_workflow(self, workflow_id: str, version: int | None = None) -> Workflow | None:
        if version is None:
            rows = self._exec(
                "SELECT data FROM workflows WHERE id = ? ORDER BY version DESC LIMIT 1", (workflow_id,)
            )
        else:
            rows = self._exec("SELECT data FROM workflows WHERE id = ? AND version = ?", (workflow_id, version))
        return Workflow.model_validate_json(rows[0][0]) if rows else None

    def workflow_versions(self, workflow_id: str) -> list[dict]:
        rows = self._exec(
            "SELECT version, created_at FROM workflows WHERE id = ? ORDER BY version DESC", (workflow_id,)
        )
        return [{"version": v, "created_at": c} for v, c in rows]

    def save_workflow(self, workflow: Workflow) -> Workflow:
        """Saves a NEW version (never overwrites, so in-flight cards keep theirs)."""
        current = self.get_workflow(workflow.id)
        workflow = workflow.model_copy(update={"version": (current.version + 1) if current else 1})
        self._exec(
            "INSERT INTO workflows (id, version, data) VALUES (?, ?, ?)",
            (workflow.id, workflow.version, workflow.model_dump_json()),
        )
        return workflow

    # -- cards
    def get_card(self, item_id: str) -> Card | None:
        return self._get("cards", item_id, Card, key_col="item_id")

    def save_card(self, card: Card) -> None:
        self._exec(
            "INSERT OR REPLACE INTO cards VALUES (?, ?, ?)", (card.item_id, card.project_id, card.model_dump_json())
        )

    def list_cards(self, project_id: str | None = None) -> list[Card]:
        if project_id:
            rows = self._exec("SELECT data FROM cards WHERE project_id = ?", (project_id,))
        else:
            rows = self._exec("SELECT data FROM cards")
        return [Card.model_validate_json(r[0]) for r in rows]

    def unlock_all_cards(self) -> int:
        n = 0
        for card in self.list_cards():
            if card.locked:
                card.locked = False
                self.save_card(card)
                n += 1
        return n

    # -- runs
    def save_run(self, run: Run) -> None:
        self._exec(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?)",
            (run.id, run.project_id, run.item_id, run.started_at, run.model_dump_json()),
        )

    def get_run(self, run_id: str) -> Run | None:
        return self._get("runs", run_id, Run)

    def list_runs(self, limit: int = 100, project_id: str | None = None) -> list[Run]:
        if project_id:
            rows = self._exec(
                "SELECT data FROM runs WHERE project_id = ? ORDER BY started_at DESC LIMIT ?", (project_id, limit)
            )
        else:
            rows = self._exec("SELECT data FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))
        runs = [Run.model_validate_json(r[0]) for r in rows]
        for r in runs:
            r.log = []  # list view stays light; fetch one run for its log
        return runs

    # -- settings
    def get_setting(self, key: str, default=None):
        rows = self._exec("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(rows[0][0]) if rows else default

    def set_setting(self, key: str, value) -> None:
        self._exec("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))
