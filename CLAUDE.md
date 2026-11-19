# Nodler

Local orchestrator that runs an agentic SDLC (role agents moving cards across a GitHub
Projects board) with a web UI to edit workflows and agents. Read `docs/design.md` first.

## Layout
- `src/nodler/` — Python backend (FastAPI + worker). `engine.py` is the pure state
  machine; keep it free of I/O so it stays easy to test.
- `web/` — React + Vite UI (workflow graph editor uses React Flow). `npm run build`
  outputs to `src/nodler/static/`, which FastAPI serves.
- `tests/` — pytest. Run `uv run pytest`.

## Commands
- `uv run pytest` — backend tests
- `uv run nodler serve` — start API + UI + worker on http://127.0.0.1:8787
- `cd web; npm run dev` — UI dev server (proxies `/api` to 8787)
- `cd web; npm run build` — build UI into the Python package

## Rules
- Deterministic steps (tests, push, PR, merge) are plain code, never an agent.
- Agents never move cards; they return an outcome and the engine decides.
- Never set `ANTHROPIC_API_KEY` for this project; it must run on the Claude login.
