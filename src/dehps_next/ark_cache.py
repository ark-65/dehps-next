"""Immutable Next PostgreSQL replay cache and indexed lookups."""

from hashlib import sha256
from itertools import pairwise

from psycopg import connect, sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from .ark import _history
from .ark_cache_compute import (
    CHECKPOINT,
    COMBINATIONS,
    HISTORY,
    PERIODS,
    RULES,
    SIZES,
    TAKE,
    WIDTHS,
    X_MAX,
    X_MIN,
    X_VALUES,
    ReplayGrid,
    ReplaySummary,
)
from .domain import digest
from .errors import DomainError

LOCK = 740153
BATCH_SIZE = 12
SERIAL_FIELDS = (
    "rules_version",
    "issue",
    "input_digest",
    "x",
    "frequency_counts",
    "actual_frequency_ranks",
    "rank_count_checkpoints",
    "rank_increments",
)
SERIAL_TYPES = ("text", "text", "text", "int2", "int2[]", "bytea", "int2[]", "bytea")


def connection(dsn, *, read_only):
    name = conninfo_to_dict(dsn).get("dbname", "")
    if name != "dehps_next" and not name.startswith("dehps_next_test_ark"):
        raise DomainError("ARK_NEXT_DATABASE_REQUIRED", "ARK requires the named Next PostgreSQL database")
    mode = "on" if read_only else "off"
    return connect(
        dsn,
        autocommit=True,
        row_factory=dict_row,
        options=f"-c default_transaction_read_only={mode} -c statement_timeout=120000 -c lock_timeout=3000",
    )


def _period_table(color):
    return sql.Identifier(f"ark_replay_{color}_periods")


def _summary_table(color):
    return sql.Identifier(f"ark_replay_{color}_summary")


def _copy(c, table, fields, types, records):
    query = sql.SQL("COPY {} ({}) FROM STDIN (FORMAT BINARY)").format(
        table, sql.SQL(", ").join(map(sql.Identifier, fields))
    )
    with c.cursor().copy(query) as writer:
        writer.set_types(types)
        for record in records:
            writer.write_row(record)


def _keys(periods):
    return [(period["issue"], period["input_digest"]) for period in periods]


def _manifest(rows):
    inputs = [
        {
            key: row[key].isoformat() if key in ("draw_at", "available_at") else row[key]
            for key in ("issue", "draw_at", "available_at", "content_digest")
        }
        for row in rows
    ]
    hashes = [bytes.fromhex(digest(row)) for row in inputs]
    periods = [
        {
            "issue": row["issue"],
            "input_digest": sha256(b"".join(hashes[i - 2 * X_MAX : i + 1])).hexdigest(),
            "draw_digest": row["content_digest"],
        }
        for i, row in enumerate(rows)
        if i >= 2 * X_MAX
    ]
    return inputs, periods


def _snapshot(c, snapshot_id=None):
    columns = "snapshot_id, rules_version, end_issue, z, as_of, published_at, evidence"
    if snapshot_id is None:
        return c.execute(
            f"""SELECT {columns},periods FROM ark_replay_snapshots WHERE rules_version=%s
                ORDER BY end_issue DESC,published_at DESC,snapshot_id DESC LIMIT 1""",
            (RULES,),
        ).fetchone()
    return c.execute(
        f"SELECT {columns},periods FROM ark_replay_snapshots WHERE snapshot_id=%s", (snapshot_id,)
    ).fetchone()


def _history_input(c, end_issue):
    as_of = c.execute("SELECT transaction_timestamp() AS cutoff").fetchone()["cutoff"]
    end = c.execute(
        """
        SELECT d.issue,d.draw_at FROM effective_draws d
        JOIN official_publications p ON p.issue=d.issue
        WHERE (%s::text IS NULL OR d.issue=%s) AND p.first_verified_at<=%s
          AND d.draw_at<=%s AND d.available_at<=%s AND d.observed_at<=%s
        ORDER BY d.draw_at DESC LIMIT 1
    """,
        (end_issue, end_issue, as_of, as_of, as_of, as_of),
    ).fetchone()
    if end is None:
        raise DomainError(
            "ARK_OFFICIAL_DRAW_REQUIRED", "A verified Next draw is required at the requested cutoff"
        )
    rows = c.execute(
        """
        SELECT d.issue,d.draw_at,d.available_at,d.red,d.blue,d.content_digest,
               coalesce(p.first_verified_at<=%s,false) AS official
        FROM effective_draws d LEFT JOIN official_publications p ON p.issue=d.issue
        WHERE d.draw_at<=%s AND d.available_at<=%s AND d.observed_at<=%s
        ORDER BY d.draw_at DESC LIMIT %s
    """,
        (as_of, end["draw_at"], as_of, as_of, HISTORY),
    ).fetchall()[::-1]
    _history(rows, HISTORY, as_of)
    # The first possible winning-rank observation has 500 prior draws.
    if max(row["available_at"] for row in rows[:X_MAX]) >= rows[X_MAX]["draw_at"] or any(
        left["available_at"] >= right["draw_at"] for left, right in pairwise(rows[X_MAX - 1 :])
    ):
        raise DomainError(
            "ARK_INSUFFICIENT_HISTORY", "A required label was unavailable before a historical draw"
        )
    return rows, as_of


def _complete(c, periods):
    issues, hashes = map(list, zip(*_keys(periods), strict=True))
    complete = {}
    for color in SIZES:
        rows = c.execute(
            sql.SQL("""
            SELECT r.issue, r.input_digest, count(*) AS rows
            FROM unnest(%s::text[],%s::text[]) AS p(issue,input_digest)
            JOIN {} r ON r.issue=p.issue AND r.input_digest=p.input_digest AND r.rules_version=%s
            GROUP BY r.issue,r.input_digest
        """).format(_period_table(color)),
            (issues, hashes, RULES),
        ).fetchall()
        if any(row["rows"] != len(X_VALUES) for row in rows):
            raise DomainError("ARK_INCOMPLETE_PERIOD", f"An existing {color} cache period is incomplete")
        complete[color] = {(row["issue"], row["input_digest"]) for row in rows}
    if complete["red"] != complete["blue"]:
        raise DomainError("ARK_INCOMPLETE_PERIOD", "Red and blue cache periods differ")
    return complete["red"]


def _write_period(c, period, result, i):
    key = (RULES, period["issue"], period["input_digest"])
    with c.transaction():
        for color in SIZES:
            selected, hit_type, result_type = (
                ("red_masks", "int2[]", "int8[]") if color == "red" else ("blue_numbers", "bool[]", "int2[]")
            )
            fields = (
                *SERIAL_FIELDS,
                selected,
                f"{color}_hits",
                "actual_ark_positions",
                "actual_cutoff_offsets",
            )
            types = (*SERIAL_TYPES, result_type, hit_type, "bytea", "bytea")
            _copy(c, _period_table(color), fields, types, ((*key, *row) for row in result[color][i]))


def _load_period(c, color, key):
    with c.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            sql.SQL("""SELECT x,{},actual_ark_positions,actual_cutoff_offsets
              FROM {} WHERE rules_version=%s AND issue=%s AND input_digest=%s ORDER BY x""").format(
                sql.Identifier(f"{color}_hits"), _period_table(color)
            ),
            (RULES, *key),
        )
        rows = cur.fetchall()
    if [row[0] for row in rows] != list(X_VALUES):
        raise DomainError("ARK_INCOMPLETE_PERIOD", f"Missing {color} data for {key[0]}")
    return [row[1:] for row in rows]


def _load_summaries(c, snapshot_id, summaries):
    for color, summary in summaries.items():
        fields = sql.SQL(",red_hit_histogram") if color == "red" else sql.SQL("")
        with c.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                sql.SQL("""SELECT x,y,{},actual_position_histogram,cutoff_offset_histogram{}
                FROM {} WHERE snapshot_id=%s ORDER BY x,y""").format(
                    sql.Identifier(f"{color}_hits"), fields, _summary_table(color)
                ),
                (snapshot_id,),
            )
            summary.load(cur)


def _publish(c, snapshot_id, inputs, periods, as_of, summaries):
    with c.transaction():
        c.execute(
            """INSERT INTO ark_replay_snapshots
                  (snapshot_id,rules_version,end_issue,z,as_of,input_manifest,periods)
                  VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (snapshot_id, RULES, periods[-1]["issue"], PERIODS, as_of, Jsonb(inputs), Jsonb(periods)),
        )
        for color, summary in summaries.items():
            summary.validate()
            fields = (
                "snapshot_id",
                "x",
                "y",
                f"{color}_hits",
                "actual_position_histogram",
                "cutoff_offset_histogram",
            )
            types = ("text", "int2", "int2", "int4", "int4[]", "int4[]")
            if color == "red":
                fields, types = (*fields, "red_hit_histogram"), (*types, "int4[]")
            _copy(c, _summary_table(color), fields, types, summary.records(snapshot_id))


def refresh(c, *, incremental, end_issue=None, progress=None):
    if not c.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (LOCK,)).fetchone()["acquired"]:
        return {"state": "BUSY"}
    try:
        previous = _snapshot(c)
        if incremental and previous is None:
            raise DomainError(
                "ARK_BACKFILL_REQUIRED", "Publish an initial 500-period replay before incremental use"
            )
        with c.transaction():
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            rows, as_of = _history_input(c, end_issue)
        inputs, periods = _manifest(rows)
        snapshot_id = digest({"rules_version": RULES, "periods": periods})
        existing = _snapshot(c, snapshot_id)
        if existing is not None:
            return _receipt(existing, "UP_TO_DATE", 0, PERIODS)
        if incremental and any(
            row["issue"] > previous["end_issue"] and not row["official"] for row in rows[-PERIODS:]
        ):
            raise DomainError(
                "ARK_OFFICIAL_DRAW_REQUIRED", "An intervening new draw is awaiting Next verification"
            )

        summaries = {color: ReplaySummary(color) for color in SIZES}
        existing_periods = _complete(c, periods)
        old_keys = set(_keys(previous["periods"])) if previous else set()
        new_keys = set(_keys(periods))
        added, removed = new_keys - old_keys, old_keys - new_keys
        if previous and old_keys & new_keys:
            _load_summaries(c, previous["snapshot_id"], summaries)
            for key in sorted(removed):
                for color, summary in summaries.items():
                    summary.apply(_load_period(c, color, key), -1)
            added_keys = added
        else:
            added_keys = new_keys
        for key in sorted(added_keys & existing_periods):
            for color, summary in summaries.items():
                summary.apply(_load_period(c, color, key), 1)

        missing = [i for i, key in enumerate(_keys(periods)) if key not in existing_periods]
        if progress:
            progress(
                {
                    "state": "RUNNING",
                    "snapshot_id": snapshot_id,
                    "end_issue": periods[-1]["issue"],
                    "periods": PERIODS,
                    "cached": len(existing_periods),
                    "to_compute": len(missing),
                }
            )
        if missing:
            grid = ReplayGrid(rows)
            for start in range(0, len(missing), BATCH_SIZE):
                batch = missing[start : start + BATCH_SIZE]
                result = grid.calculate([i + 2 * X_MAX for i in batch])
                for i in batch:
                    origin = i + 2 * X_MAX
                    _write_period(c, periods[i], result, origin)
                    if _keys([periods[i]])[0] in added_keys:
                        for color, summary in summaries.items():
                            summary.apply([row[-3:] for row in result[color][origin]], 1)
                if progress:
                    progress(
                        {
                            "state": "RUNNING",
                            "complete": len(existing_periods) + start + len(batch),
                            "periods": PERIODS,
                            "through": periods[batch[-1]]["issue"],
                        }
                    )
        if _complete(c, periods) != new_keys:
            raise DomainError("ARK_INCOMPLETE_PERIOD", "Full fixed-window cache must exist before publishing")
        _publish(c, snapshot_id, inputs, periods, as_of, summaries)
        return _receipt(_snapshot(c, snapshot_id), "PUBLISHED", len(missing), len(existing_periods))
    finally:
        c.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))


def _receipt(snapshot, state, computed, cached):
    return {
        "state": state,
        "snapshot_id": snapshot["snapshot_id"],
        "end_issue": snapshot["end_issue"],
        "periods": snapshot["z"],
        "evidence": snapshot["evidence"],
        "combinations": COMBINATIONS,
        "computed_periods": computed,
        "reused_periods": cached,
    }


def status(c):
    snapshot = _snapshot(c)
    if snapshot is None:
        return {"state": "BACKFILL_REQUIRED"}
    output = _receipt(snapshot, "READY", 0, snapshot["z"])
    output["first_issue"] = snapshot["periods"][0]["issue"]
    output["rules_version"] = snapshot["rules_version"]
    output["published_at"] = snapshot["published_at"]
    for color in SIZES:
        count = c.execute(
            sql.SQL("SELECT count(*) AS n FROM {} WHERE snapshot_id=%s").format(_summary_table(color)),
            (snapshot["snapshot_id"],),
        ).fetchone()["n"]
        output[f"{color}_summary_rows"] = count
    return output


def _require_snapshot(c, snapshot_id):
    value = _snapshot(c, snapshot_id)
    if value is None:
        raise DomainError("ARK_SNAPSHOT_NOT_FOUND", "Requested ARK replay snapshot was not found")
    return value


def rankings(c, color, limit, snapshot_id=None):
    snapshot = _require_snapshot(c, snapshot_id)
    fields = sql.SQL(",red_hit_histogram") if color == "red" else sql.SQL("")
    rows = c.execute(
        sql.SQL("""SELECT x,y,{} AS hits,actual_position_histogram,cutoff_offset_histogram{}
        FROM {} WHERE snapshot_id=%s ORDER BY {} DESC,x,y LIMIT %s""").format(
            sql.Identifier(f"{color}_hits"), fields, _summary_table(color), sql.Identifier(f"{color}_hits")
        ),
        (snapshot["snapshot_id"], limit),
    ).fetchall()
    for row in rows:
        row["rate"] = row["hits"] / (snapshot["z"] * WIDTHS[color])
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "end_issue": snapshot["end_issue"],
        "evidence": snapshot["evidence"],
        "periods": snapshot["z"],
        "color": color,
        "rankings": rows,
    }


def _full_ranks(row, color, y):
    size, width = SIZES[color], WIDTHS[color]
    point = (y - X_MIN) // CHECKPOINT
    anchor = X_MIN + point * CHECKPOINT
    counts = row["rank_count_checkpoints"][point * size : (point + 1) * size]
    for rank in row["rank_increments"][(anchor - X_MIN) * width : (y - X_MIN) * width]:
        counts[rank - 1] += 1
    frequency = row["frequency_counts"]
    number_order = sorted(range(1, size + 1), key=lambda number: (-frequency[number - 1], number))
    rank_order = sorted(range(1, size + 1), key=lambda rank: (-counts[rank - 1], rank))
    return [
        {
            "ark_position": i,
            "number": number_order[rank - 1],
            "frequency_rank": rank,
            "frequency_count": frequency[number_order[rank - 1] - 1],
            "winning_rank_count": counts[rank - 1],
            "coefficient": counts[rank - 1] / y,
        }
        for i, rank in enumerate(rank_order, 1)
    ]


def details(c, color, x, y, count, snapshot_id=None, full=False):
    snapshot = _require_snapshot(c, snapshot_id)
    periods = snapshot["periods"][-count:]
    issues, hashes, draw_hashes = map(
        list, zip(*((p["issue"], p["input_digest"], p["draw_digest"]) for p in periods), strict=True)
    )
    picked = "red_masks" if color == "red" else "blue_numbers"
    rank_fields = (
        sql.SQL(",r.frequency_counts,r.rank_count_checkpoints,r.rank_increments") if full else sql.SQL("")
    )
    array_index = y - X_MIN + 1
    rows = c.execute(
        sql.SQL("""SELECT r.issue,(r.{})[%s] AS selected,(r.{})[%s] AS hits,
                r.actual_frequency_ranks,r.actual_ark_positions,r.actual_cutoff_offsets,d.{} AS actual{}
        FROM unnest(%s::text[],%s::text[],%s::text[]) WITH ORDINALITY AS p(issue,input_digest,draw_digest,ordinal)
        JOIN {} r ON r.issue=p.issue AND r.input_digest=p.input_digest AND r.rules_version=%s AND r.x=%s
        JOIN draws d ON d.issue=p.issue AND d.content_digest=p.draw_digest ORDER BY p.ordinal""").format(
            sql.Identifier(picked),
            sql.Identifier(f"{color}_hits"),
            sql.Identifier(color),
            rank_fields,
            _period_table(color),
        ),
        (array_index, array_index, issues, hashes, draw_hashes, snapshot["rules_version"], x),
    ).fetchall()
    if len(rows) != len(periods):
        raise DomainError("ARK_INCOMPLETE_PERIOD", "Snapshot has unavailable cached records or draw content")
    width = WIDTHS[color]
    start = (y - X_MIN) * width
    result = []
    for row in rows:
        actual = sorted(row["actual"]) if color == "red" else [row["actual"]]
        selected = (
            [number for number in range(1, 34) if row["selected"] & (1 << (number - 1))]
            if color == "red"
            else row["selected"]
        )
        balls = [
            {
                "number": number,
                "frequency_rank": rank,
                "ark_position": position,
                "offset": offset,
                "hit": position <= TAKE[color],
            }
            for number, rank, position, offset in zip(
                actual,
                row["actual_frequency_ranks"],
                row["actual_ark_positions"][start : start + width],
                row["actual_cutoff_offsets"][start : start + width],
                strict=True,
            )
        ]
        item = {"issue": row["issue"], "selected": selected, "actual": balls, "hits": row["hits"]}
        if color == "red":
            item["red_hit_positions"] = sorted(ball["ark_position"] for ball in balls if ball["hit"])
        if full:
            item["ranks"] = _full_ranks(row, color, y)
        result.append(item)
    hits = sum(item["hits"] for item in result)
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "end_issue": snapshot["end_issue"],
        "color": color,
        "x": x,
        "y": y,
        "z": len(result),
        "snapshot_z": snapshot["z"],
        "evidence": snapshot["evidence"],
        "hits": hits,
        "rate": hits / (len(result) * width),
        "periods": result,
    }
