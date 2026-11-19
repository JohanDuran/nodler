"""nodler: local orchestrator for an agentic software development life cycle."""

import argparse
import logging
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="nodler")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="Start the web UI, API and worker")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--data", default=str(Path.cwd() / "data"), help="Folder for the database and worktrees")
    serve.add_argument("--no-worker", action="store_true", help="Run the UI/API only")
    args = parser.parse_args()

    if args.cmd == "serve":
        import uvicorn

        from .api import create_app

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        app = create_app(Path(args.data).resolve(), start_worker=not args.no_worker)
        print(f"nodler running on http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
