"""Bound the existing progress SQL per statement, preserving exact snapshot totals."""

import argparse
import hashlib
import json
import signal
import sys
import time
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

from psycopg import DatabaseError
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import PoolTimeout

from dehps_next import training_observer
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.release import code_identity, numeric_identity
from dehps_next.research_memory import progress_status

BLOCK = 4096
SUMS = ('committed_fresh_origins', 'committed_gradient_steps', 'reused_origins')
OWNED_SOAKS = {'qwen-latency-stability-20261113', 'qwen-latency-stability-20261113-v2'}


class Query:
    def rows(self, query, params):
        self.query, self.params = query, params
        return [{}]


def partition_query(since):
    captured = Query()
    progress_status(captured, since=since)
    needle = 'FROM research_memory_events e WHERE kind IN'
    assert captured.query.count(needle) == 1 and captured.params == (since,)
    query = captured.query.replace(needle, 'FROM research_memory_events e '
                                   'WHERE e.seq>=%s AND e.seq<%s AND kind IN', 1)
    return query, hashlib.sha256(captured.query.encode()).hexdigest()


def aggregate(connection, query, since, low, high, block):
    result = {'last_actual_fit_at': None, **dict.fromkeys(SUMS, 0)}
    count = 0
    for start in range(low, high, block):
        row = connection.execute(query, (start, min(start + block, high), since)).fetchone()
        last = row['last_actual_fit_at']
        if last and (result['last_actual_fit_at'] is None or last > result['last_actual_fit_at']):
            result['last_actual_fit_at'] = last
        for field in SUMS:
            result[field] += row[field]
        count += 1
    if any(not -(2**63) <= result[field] < 2**63 for field in SUMS):
        raise OverflowError('Retain the original PostgreSQL bigint result bounds')
    return result, count


def bounded_progress(db, *, since):
    db = getattr(db, 'progress_db', db)
    query, query_hash = partition_query(since)
    started = time.monotonic()
    with db.pool.connection() as connection, connection.transaction():
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        connection.execute('SET LOCAL jit=off')
        assert connection.execute('SHOW statement_timeout').fetchone()['statement_timeout'] == '15s'
        limits = connection.execute('SELECT min(seq) AS low,max(seq) AS high '
                                    'FROM research_memory_events').fetchone()
        low = limits['low'] or 0
        high = (limits['high'] + 1) if limits['high'] is not None else low
        result, blocks = aggregate(connection, query, since, low, high, BLOCK)
    print(json.dumps({'progress_query_sha256': query_hash, 'snapshot_sequence_range': [low, high],
                      'blocks': blocks, 'block_size': BLOCK, 'seconds': time.monotonic() - started,
                      'statement_timeout_changed': False}), flush=True)
    return result


def sample_waiting_turn(db):
    # Queue behind Steward's original bounded transaction, rather than repeatedly
    # losing a SKIP LOCKED race. The original sampler reuses this owned connection.
    with db.pool.connection() as connection, connection.transaction():
        due = connection.execute(
            "SELECT id FROM research_soaks WHERE id=ANY(%s) AND state='RUNNING' "
            "AND next_sample<=now() ORDER BY started_at FOR UPDATE", (sorted(OWNED_SOAKS),)
        ).fetchall()
        if not due:
            return 0

        @contextmanager
        def owned_connection():
            yield connection

        proxy = SimpleNamespace(pool=SimpleNamespace(connection=owned_connection), progress_db=db)
        return training_observer.sample_due(proxy)


def verify(db, since):
    query, query_hash = partition_query(since)
    comparisons = []
    with db.pool.connection() as connection, connection.transaction():
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        connection.execute('SET LOCAL jit=off')
        assert connection.execute('SHOW statement_timeout').fetchone()['statement_timeout'] == '15s'
        limits = connection.execute('SELECT min(seq) AS low,max(seq) AS high '
                                    'FROM research_memory_events').fetchone()
        low, high = limits['low'], limits['high'] + 1
        for left, right in ((low, min(low + 8192, high)), (max(low, high - 8192), high)):
            for cutoff in ('1970-01-01T00:00:00+00:00', since):
                reference = connection.execute(query, (left, right, cutoff)).fetchone()
                result, blocks = aggregate(connection, query, cutoff, left, right, BLOCK)
                assert result == reference
                comparisons.append({'range': [left, right], 'since': str(cutoff), 'blocks': blocks,
                                    'exact_original_sql_result': result})
        result, blocks = aggregate(connection, query, since, low, high, BLOCK)
    print(json.dumps({'verified': True, 'original_query_sha256': query_hash,
                      'consistent_real_database_snapshot': True, 'comparisons': comparisons,
                      'full_progress': result, 'full_blocks': blocks,
                      'statement_timeout_changed': False}, default=str), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--soak', required=True)
    parser.add_argument('--controller-source', required=True)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    assert args.soak in OWNED_SOAKS
    assert code_identity() == args.controller_source
    settings = Settings.from_env()
    assert conninfo_to_dict(settings.database_url)['dbname'] == 'dehps_next'
    db = Database(settings)
    try:
        run = db.rows('SELECT * FROM research_soaks WHERE id=%s', (args.soak,))[0]
        assert run['interval_seconds'] == 300
        assert run['deadline'] - run['started_at'] == timedelta(hours=24)
        if args.verify:
            verify(db, run['started_at'])
            return
        training_observer.progress_status = bounded_progress
        while True:
            run = db.rows('SELECT * FROM research_soaks WHERE id=%s', (args.soak,))[0]
            if run['state'] != 'RUNNING':
                break
            primary = db.rows("SELECT p.config->>'code_digest' AS program_source,"
                              "r.config->>'code_digest' AS source,r.config->>'numeric_digest' AS numeric "
                              "FROM research_programs p LEFT JOIN research_campaigns r ON r.id=p.current_campaign "
                              "WHERE p.id='autonomous-v2'")[0]
            assert primary['program_source'] == args.controller_source
            if primary['source'] is None:
                print(json.dumps({'waiting_current_campaign_epoch': True, 'at': time.time()}), flush=True)
                time.sleep(10)
                continue
            assert primary['source'] == args.controller_source and primary['numeric'] == numeric_identity()
            active = db.rows("SELECT id FROM research_soaks WHERE state='RUNNING'")
            assert {r['id'] for r in active} <= OWNED_SOAKS
            try:
                count = sample_waiting_turn(db)
                if count:
                    print(json.dumps({'samples_taken': count, 'at': time.time()}), flush=True)
            except (DatabaseError, PoolTimeout, TimeoutError) as exc:
                print(json.dumps({'sample_failed': type(exc).__name__,
                                  'sqlstate': getattr(exc, 'sqlstate', None), 'at': time.time()}), flush=True)
                if getattr(exc, 'sqlstate', None) == '55P03':
                    time.sleep(1)
                    continue
            if args.once:
                run = db.rows('SELECT * FROM research_soaks WHERE id=%s', (args.soak,))[0]
                break
            time.sleep(10)
        print(json.dumps({'final_soak': run}, default=str), flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    main()
