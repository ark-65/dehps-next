"""Command-line entry points for building and reading the ARK replay cache."""

import re

from . import ark_cache
from .ark_cache_compute import COMBINATIONS, PERIODS, SIZES, X_MAX, X_MIN
from .errors import DomainError


def arguments(commands):
    ark = commands.add_parser("ark-cache", help="Build or query the Next ARK replay cache")
    actions = ark.add_subparsers(dest="ark_action", required=True)
    for name in ("init", "status", "update"):
        actions.add_parser(name)
    backfill = actions.add_parser("backfill")
    backfill.add_argument("--end-issue", help="Verified final issue, default is latest verified")
    for name in ("detail", "rank"):
        parser = actions.add_parser(name)
        parser.add_argument("--color", required=True, choices=SIZES)
        parser.add_argument("--snapshot", help="Snapshot ID, default is latest")
        if name == "detail":
            parser.add_argument(
                "--x", required=True, type=int, choices=range(X_MIN, X_MAX + 1), metavar="50..500"
            )
            parser.add_argument("--y", required=True, type=int)
            parser.add_argument("--periods", type=int, default=10)
            parser.add_argument("--full-ranks", action="store_true")
        else:
            parser.add_argument("--limit", type=int, default=20)
    return ark


def run(args, settings, output):
    action = args.ark_action
    dsn = settings.database_url
    if action == "init":
        from .db import Database

        with ark_cache.connection(dsn, read_only=True):
            database = Database(settings)
            try:
                schema = database.migrate()
            finally:
                database.close()
        output({"schema": schema, "state": "INITIALIZED"})
        return

    end_issue = getattr(args, "end_issue", None)
    if end_issue is not None and not re.fullmatch(r"[0-9]{7}", end_issue):
        raise DomainError("ARK_PARAMETERS", "--end-issue must be a seven-digit Next issue")
    if action == "detail" and not (X_MIN <= args.y <= args.x and 1 <= args.periods <= PERIODS):
        raise DomainError("ARK_PARAMETERS", "Require 50 <= y <= x and 1 <= periods <= 500")
    if action == "rank" and not 1 <= args.limit <= COMBINATIONS:
        raise DomainError("ARK_PARAMETERS", f"Require 1 <= limit <= {COMBINATIONS}")

    with ark_cache.connection(dsn, read_only=action in ("status", "detail", "rank")) as conn:
        if action == "status":
            value = ark_cache.status(conn)
        elif action == "detail":
            value = ark_cache.details(
                conn,
                args.color,
                args.x,
                args.y,
                args.periods,
                args.snapshot,
                args.full_ranks,
            )
        elif action == "rank":
            value = ark_cache.rankings(conn, args.color, args.limit, args.snapshot)
        else:
            value = ark_cache.refresh(
                conn, incremental=action == "update", end_issue=end_issue, progress=output
            )
        output(value)
