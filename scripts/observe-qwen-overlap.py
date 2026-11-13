"""Keep primary inference intervals across graph retirement, without model calls."""

import argparse
import fcntl
import hashlib
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

from dehps_next.config import Settings
from dehps_next.db import Database

MAX_BYTES = 32 * 1024**2
BLOCK = 4096
FIELDS = """json_build_object('id',m.id,'campaign',m.campaign_id,'stage',m.stage,
 'state',m.state,'at',m.created_at,'model_digest',m.model_digest,
 'request',m.request,'response',m.response,'wall',m.metrics->'wall_seconds')"""
ARCHIVES = """SELECT e.seq,json_build_object(
 'id',(n.call->>'id')::bigint,'campaign',e.payload->>'campaign','stage',n.call->>'stage',
 'state',n.call->>'state','at',n.call->>'created_at','model_digest',n.call->>'model_digest',
 'request',n.call->'request','response',n.call->'response','wall',n.call#>'{metrics,wall_seconds}') call
 FROM research_memory_events e CROSS JOIN LATERAL
 jsonb_array_elements(e.payload->'call_receipts') n(call)
 WHERE e.seq BETWEEN %s AND %s AND e.kind='CAMPAIGN_ARCHIVE'
 AND n.call->>'stage' LIKE 'CANDIDATE_SELECTION_V4_%%' ORDER BY e.seq"""


def epoch(value):
    return datetime.fromisoformat(value).timestamp()


def merge(calls, row, captured, source, archive_seq=None):
    key = str(row['id'])
    start, wall = epoch(row['at']), row['wall']
    assert row['state'] in ('RESERVED', 'SUCCEEDED', 'FAILED')
    assert math.isfinite(start) and start <= captured + 1
    if wall is not None:
        assert type(wall) in (int, float) and math.isfinite(wall) and wall >= 0
    previous = calls.get(key)
    current = {**row, 'start': start, 'evidence_sources': [source],
               'archive_sequences': [archive_seq] if archive_seq is not None else []}
    if previous:
        assert previous['start'] == start and previous['campaign'] == row['campaign']
        assert previous['stage'] == row['stage'] and previous['model_digest'] == row['model_digest']
        if previous['state'] != 'RESERVED':
            assert all(previous[k] == current[k] for k in ('state', 'request', 'response'))
            if previous['wall'] is not None:
                assert previous['wall'] == wall, 'Conflicting terminal interval evidence'
        current['evidence_sources'] = sorted(set(previous['evidence_sources'] + [source]))
        current['archive_sequences'] = sorted(set(previous['archive_sequences'] + current['archive_sequences']))
        if previous.get('first_terminal_observed_at') is not None:
            current['first_terminal_observed_at'] = previous['first_terminal_observed_at']
    if row['state'] == 'RESERVED':
        current.update(end=captured, end_kind='ACTIVE_AT_SNAPSHOT')
    else:
        current.setdefault('first_terminal_observed_at', captured)
        # Missing latency is never filled with zero or an estimated provider duration.
        current['end'] = start + wall if wall is not None else current['first_terminal_observed_at']
        current['end_kind'] = ('ACTUAL_RECORDED_LOGICAL_WALL' if wall is not None
                               else 'FIRST_TERMINAL_OBSERVATION_UPPER_BOUND')
    calls[key] = current


def capture(db, previous, since=None):
    started = time.monotonic()
    calls = {str(r['id']): r for r in previous['calls']} if previous else {}
    active_before = {key for key, r in calls.items() if r['state'] == 'RESERVED'}
    seen = set()
    with db.pool.connection() as connection, connection.transaction():
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        connection.execute("SET LOCAL statement_timeout='8s'")
        anchor = connection.execute("SELECT extract(epoch FROM statement_timestamp())::float8 at,"
            "extract(epoch FROM clock_timestamp())::float8 captured,"
            "coalesce(max(seq),0) cursor FROM research_memory_events").fetchone()
        observed, captured, upper = anchor['at'], anchor['captured'], anchor['cursor']
        lower = previous['coverage_from'] if previous else (epoch(since) if since else observed)
        initialized = previous['initialized_at'] if previous else observed
        assert lower <= initialized <= observed <= captured
        cursor = previous['event_cursor'] if previous else (0 if since else upper)
        assert cursor <= upper, 'Primary archive cursor regressed'
        blocks = 0
        for first in range(cursor + 1, upper + 1, BLOCK):
            for row in connection.execute(ARCHIVES, (first, min(first + BLOCK - 1, upper))):
                native = row['call']
                merge(calls, native, captured, 'IMMUTABLE_CAMPAIGN_ARCHIVE', row['seq'])
                seen.add(str(native['id']))
            blocks += 1
        # Read every live logical call, including a call that straddles the
        # coverage boundary. Archive receipts are read before their event's
        # sequence is allocated; this live union also covers late commits
        # behind the sequence frontier. Never assume sequence commit order.
        query = 'SELECT ' + FIELDS + " FROM research_model_calls m WHERE " \
            "m.stage LIKE 'CANDIDATE_SELECTION_V4_%%' ORDER BY m.id"
        for row in connection.execute(query):
            merge(calls, row['json_build_object'], captured, 'LIVE_NATIVE_AT_SNAPSHOT')
            seen.add(str(row['json_build_object']['id']))
        assert active_before <= seen, 'An active primary call vanished without its archive'
    return {'kind': 'ACTUAL_PRIMARY_INTERVAL_LEDGER_V1', 'observed_at': observed,
            'initialized_at': initialized, 'coverage_from': lower,
            'historical_reconstruction': lower < initialized, 'event_cursor': upper,
            'complete': True, 'calls': sorted(calls.values(), key=lambda r: r['id']),
            'archive_blocks_this_snapshot': blocks, 'capture_seconds': time.monotonic() - started,
            'scope': 'ACTUAL_PRIMARY_INTERVALS;NOT_HISTORICAL_LIVE_SAMPLING_OR_24H_PASS',
            'native_counts_estimated': False}


def store(path, value):
    assert path.parent.is_dir() and not path.parent.is_symlink() and not path.is_symlink()
    raw = json.dumps(value, indent=2, allow_nan=False) + '\n'
    assert len(raw.encode()) <= MAX_BYTES, 'Stop observer only; bounded interval artifact'
    pending = path.with_name(path.name + '.pending')
    assert not pending.is_symlink()
    with pending.open('w') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    pending.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--since', help='Initial historical reconstruction; never renews on restart')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    settings = Settings.from_env()
    assert conninfo_to_dict(settings.database_url)['dbname'] == 'dehps_next'
    lock = args.output.with_name(args.output.name + '.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    source = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    previous = None
    if args.output.exists():
        assert not args.output.is_symlink() and args.output.stat().st_size <= MAX_BYTES
        previous = json.loads(args.output.read_text())
        assert previous['kind'] == 'ACTUAL_PRIMARY_INTERVAL_LEDGER_V1'
        assert previous['observer_source_sha256'] == source, 'Preserve the frozen interval observer'
        if args.since:assert previous['coverage_from'] == epoch(args.since)
    db = Database(settings)
    try:
        while True:
            value = capture(db, previous, args.since)
            value['observer_source_sha256'] = source
            store(args.output, value)
            previous = value
            print(json.dumps({k: value[k] for k in ('observed_at', 'event_cursor',
                  'archive_blocks_this_snapshot', 'capture_seconds')}), flush=True)
            if args.once:break
            time.sleep(10)
    finally:db.close()


if __name__ == '__main__':
    main()
