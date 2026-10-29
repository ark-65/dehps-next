import argparse
import json
import logging
import signal
import threading

from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout

from .artifacts import Artifacts
from .config import Settings
from .data import DataService
from .db import Database
from .errors import DomainError
from .model import Recipe
from .scheduler import Scheduler
from .status import get_status
from .worker import Worker, event


def output(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(prog="dehps-next")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "sync", "status"):
        commands.add_parser(name)
    loop = commands.add_parser("create-loop")
    loop.add_argument("--name", required=True)
    loop.add_argument("--mode", choices=["REPLAY", "FORWARD"], default="REPLAY")
    loop.add_argument("--bootstrap", type=int, default=64)
    loop.add_argument("--epochs", type=int, default=20)
    loop.add_argument("--max-cycles", type=int, default=64)
    worker = commands.add_parser("worker")
    worker.add_argument("--max-jobs", type=int)
    worker.add_argument("--role", choices=["all", "compute", "planning"], default="all")
    research = commands.add_parser("research-create")
    research.add_argument("--name", required=True)
    research.add_argument("--planner", choices=["rules", "local"], default="rules")
    research.add_argument("--max-nodes", type=int, default=3)
    research.add_argument("--recent", type=int, default=60)
    research.add_argument("--historical", type=int, default=200)
    research_status = commands.add_parser("research-status")
    research_status.add_argument("--name", required=True)
    adopt = commands.add_parser("adopt-release")
    adopt.add_argument("--loop", required=True)
    adopt.add_argument("--reason", required=True)
    expect = commands.add_parser("expect")
    expect.add_argument("--issue", required=True)
    expect.add_argument("--draw-at", required=True)
    expect.add_argument("--deadline", required=True)
    importer = commands.add_parser("import-json")
    importer.add_argument("path")
    importer.add_argument("--source", required=True)
    importer.add_argument("--provenance", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8341)
    watcher = commands.add_parser("watch-source")
    watcher.add_argument("--interval", type=int, default=3600)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(settings), host="0.0.0.0", port=args.port, access_log=False)
        return
    db = Database(settings)
    artifacts = Artifacts(settings)
    try:
        if args.command == "init":
            db.migrate()
            output({"schema": 2, "status": "initialized", "runtime": str(settings.runtime)})
        elif args.command == "sync":
            output(DataService(db, artifacts).sync())
        elif args.command == "import-json":
            from pathlib import Path

            with Path(args.path).open("rb") as h:
                raw = h.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise DomainError("SOURCE_TOO_LARGE", "Import exceeds 2MiB")
            output(
                DataService(db, artifacts).ingest(
                    json.loads(raw), source_url=args.source, raw=raw, provenance=args.provenance
                )
            )
        elif args.command == "create-loop":
            output(
                Scheduler(db, artifacts).create_loop(
                    args.name, args.mode, args.bootstrap, Recipe(epochs=args.epochs), args.max_cycles
                )
            )
        elif args.command == "expect":
            output(Scheduler(db, artifacts).expect(args.issue, args.draw_at, args.deadline))
        elif args.command == "worker":
            Worker(db, artifacts, role=args.role).run(args.max_jobs)
        elif args.command == "research-create":
            from .research import Research

            output(
                Research(db, artifacts).create(
                    args.name,
                    planner=args.planner,
                    max_nodes=args.max_nodes,
                    recent=args.recent,
                    historical=args.historical,
                )
            )
        elif args.command == "research-status":
            output(
                {
                    "campaign": db.rows("SELECT * FROM research_campaigns WHERE id=%s", (args.name,)),
                    "nodes": db.rows(
                        "SELECT path,parent_id,spec,status,evaluation,decision FROM research_nodes WHERE campaign_id=%s ORDER BY created_at",
                        (args.name,),
                    ),
                    "decisions": db.rows(
                        "SELECT * FROM research_decisions WHERE campaign_id=%s ORDER BY id", (args.name,)
                    ),
                }
            )
        elif args.command == "adopt-release":
            from .research import Research

            output(Research(db, artifacts).adopt_release(args.loop, args.reason))
        elif args.command == "status":
            output(get_status(db, artifacts))
        elif args.command == "watch-source":
            if args.interval < 300:
                raise DomainError("POLL_BUDGET", "Official source interval must be at least 300 seconds")
            stop = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            signal.signal(signal.SIGINT, lambda *_: stop.set())
            while not stop.is_set():
                try:
                    event("source_sync", **DataService(db, artifacts).sync())
                except (DomainError, OSError, ValueError, DatabaseError, PoolTimeout) as exc:
                    event("source_sync_failed", code=getattr(exc, "code", type(exc).__name__))
                stop.wait(args.interval)
    except DomainError as exc:
        output({"status": "error", "code": exc.code, "detail": str(exc)})
        raise SystemExit(2) from exc
    finally:
        db.close()


if __name__ == "__main__":
    main()
