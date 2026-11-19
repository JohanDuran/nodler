"""FastAPI app: REST API for the UI + serves the built UI + runs the worker in the background."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import github as gh
from .catalog import ACTIONS, BUILTIN_TOOLS, EFFECTS, POST_CHECKS
from .engine import possible_outcomes
from .models import Agent, Project, Workflow
from .proc import CommandError
from .store import Store
from .validate import validate_workflow
from .worker import Worker

STATIC = Path(__file__).parent / "static"


def create_app(data_dir: Path, start_worker: bool = True) -> FastAPI:
    store = Store(data_dir / "nodler.db")
    worker = Worker(store, data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(worker.loop()) if start_worker else None
        yield
        worker.stop()
        if task:
            task.cancel()

    app = FastAPI(title="nodler", lifespan=lifespan)
    app.state.store, app.state.worker = store, worker

    # ---------------------------------------------------------------- worker
    @app.get("/api/state")
    def state():
        return worker.status()

    @app.post("/api/worker/{action}")
    def control(action: str):
        if action == "pause":
            worker.set_paused(True)
        elif action == "resume":
            worker.set_paused(False)
        elif action == "poke":
            worker.poke()
        else:
            raise HTTPException(404, "unknown action")
        return worker.status()

    @app.get("/api/catalog")
    def catalog():
        return {"actions": ACTIONS, "effects": EFFECTS, "post_checks": POST_CHECKS, "tools": BUILTIN_TOOLS}

    # ---------------------------------------------------------------- projects
    @app.get("/api/projects")
    def projects():
        return store.list_projects()

    @app.put("/api/projects/{project_id}")
    def save_project(project_id: str, project: Project):
        if project.id != project_id:
            raise HTTPException(400, "id mismatch")
        if store.get_workflow(project.workflow_id) is None:
            raise HTTPException(400, f"workflow '{project.workflow_id}' does not exist")
        store.save_project(project)
        worker.poke()
        return project

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str):
        store.delete_project(project_id)
        return {"ok": True}

    @app.post("/api/projects/{project_id}/check")
    def check_project(project_id: str):
        project = store.get_project(project_id)
        if project is None:
            raise HTTPException(404, "no such project")
        checks = []
        local = Path(project.local_path)
        checks.append({"name": "Local clone exists", "ok": (local / ".git").exists(), "detail": str(local)})
        scopes = gh.auth_scopes()
        checks.append({"name": "gh token has 'project' scope", "ok": "'project'" in scopes,
                       "detail": "Run: gh auth refresh -s project" if "'project'" not in scopes else ""})
        workflow = store.get_workflow(project.workflow_id)
        try:
            board = gh.load_board(project.board_owner, project.board_number)
            names = [s.name for s in workflow.statuses] if workflow else []
            missing = [n for n in names if n.strip().lower() not in board.options]
            checks.append({"name": "Board reachable", "ok": True,
                           "detail": f"Status options: {', '.join(board.option_names)}"})
            checks.append({"name": "Board has every workflow status", "ok": not missing,
                           "detail": f"Add these Status options on GitHub: {', '.join(missing)}" if missing else ""})
        except CommandError as exc:
            checks.append({"name": "Board reachable", "ok": False, "detail": str(exc)})
        return checks

    # ---------------------------------------------------------------- agents
    @app.get("/api/agents")
    def agents():
        return store.list_agents()

    @app.put("/api/agents/{agent_id}")
    def save_agent(agent_id: str, agent: Agent):
        if agent.id != agent_id:
            raise HTTPException(400, "id mismatch")
        if not agent.outcomes:
            raise HTTPException(400, "an agent needs at least one outcome")
        store.save_agent(agent)
        return agent

    @app.delete("/api/agents/{agent_id}")
    def delete_agent(agent_id: str):
        used = [w.name for w in store.list_workflows() if any(s.agent_id == agent_id for s in w.statuses)]
        if used:
            raise HTTPException(400, f"agent is used by workflow(s): {', '.join(used)}")
        store.delete_agent(agent_id)
        return {"ok": True}

    # ---------------------------------------------------------------- workflows
    @app.get("/api/workflows")
    def workflows():
        return store.list_workflows()

    @app.get("/api/workflows/{workflow_id}")
    def workflow(workflow_id: str, version: int | None = None):
        wf = store.get_workflow(workflow_id, version)
        if wf is None:
            raise HTTPException(404, "no such workflow")
        return {"workflow": wf, "versions": store.workflow_versions(workflow_id)}

    @app.post("/api/workflows/validate")
    def validate(wf: Workflow):
        agents_map = store.agents_by_id()
        errors, warnings = validate_workflow(wf, agents_map)
        outcomes = {s.id: possible_outcomes(wf, s.id, agents_map) for s in wf.statuses}
        return {"errors": errors, "warnings": warnings, "outcomes": outcomes}

    @app.put("/api/workflows/{workflow_id}")
    def save_workflow(workflow_id: str, wf: Workflow):
        if wf.id != workflow_id:
            raise HTTPException(400, "id mismatch")
        errors, warnings = validate_workflow(wf, store.agents_by_id())
        if errors:
            raise HTTPException(400, {"errors": errors, "warnings": warnings})
        saved = store.save_workflow(wf)
        return {"workflow": saved, "warnings": warnings}

    # ---------------------------------------------------------------- history
    @app.get("/api/runs")
    def runs(project_id: str | None = None, limit: int = 100):
        return store.list_runs(limit=limit, project_id=project_id)

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        r = store.get_run(run_id)
        if r is None:
            raise HTTPException(404, "no such run")
        return r

    @app.get("/api/cards")
    def cards(project_id: str | None = None):
        return store.list_cards(project_id)

    @app.get("/api/settings")
    def settings():
        return {k: store.get_setting(k, d) for k, d in (("comment_moves", True), ("allow_api_key", False))}

    @app.put("/api/settings")
    def save_settings(values: dict):
        for k in ("comment_moves", "allow_api_key"):
            if k in values:
                store.set_setting(k, bool(values[k]))
        return settings()

    # ---------------------------------------------------------------- UI
    if STATIC.exists():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            return FileResponse(STATIC / "index.html")

    return app
