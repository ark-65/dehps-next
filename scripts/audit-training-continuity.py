"""Read-only audit of actual fit gaps, including gaps hidden between soak samples."""

import argparse
import hashlib
import inspect
import json
import time as monotonic_clock
from datetime import datetime, time, timedelta
from itertools import pairwise

from psycopg.conninfo import conninfo_to_dict

from dehps_next import training_window
from dehps_next.calendar import CALENDAR, ZONE
from dehps_next.config import Settings
from dehps_next.db import Database

BLOCK = 4096
STALL_SECONDS = 900


def pause_intervals(connection, start, end):
    # status() changes at a calendar boundary, draw timestamp, publication
    # verification or source observation. Evaluate the real gate between all
    # such boundaries; never use midnight as a resumption event.
    points = {start, end}
    day = start.astimezone(ZONE).date()
    while day <= end.astimezone(ZONE).date():
        if not CALENDAR['valid_from'] <= day.isoformat() <= CALENDAR['valid_until']:
            raise RuntimeError('Calendar coverage missing; do not infer pause exemptions')
        if day.weekday() in CALENDAR['weekdays']:
            boundary = datetime.combine(day, time.fromisoformat(CALENDAR['prepare_time']), ZONE)
            if start < boundary < end:
                points.add(boundary)
        day += timedelta(days=1)
    publications = connection.execute(
        """SELECT d.issue,d.draw_at,p.first_verified_at,s.observed_at
        FROM draws d JOIN official_publications p ON p.issue=d.issue
        JOIN sources s ON s.id=p.source_id
        WHERE d.draw_at>=%s AND d.draw_at<=%s ORDER BY d.draw_at LIMIT 101""",
        (start - timedelta(days=8), end),
    ).fetchall()
    if len(publications) > 100:
        raise RuntimeError('Unexpected publication cardinality; no incomplete boundary audit')
    for row in publications:
        for key in ('draw_at', 'first_verified_at', 'observed_at'):
            if row[key] is not None and start < row[key] < end:
                points.add(row[key])
    pauses = []
    boundaries = sorted(points)
    for left, right in pairwise(boundaries):
        window = training_window.status(connection, left + (right - left) / 2)
        if window['reason'] == 'CALENDAR_REVIEW_REQUIRED':
            raise RuntimeError('Unknown training window; no continuity pass')
        if window['paused']:
            assert window['reason'] == 'WAITING_OFFICIAL_DRAW_VERIFICATION'
            pauses.append((left, right, window))
    return pauses


def active_seconds(left, right, pauses):
    paused = sum(max(0, (min(right, end) - max(left, start)).total_seconds())
                 for start, end, _ in pauses)
    return (right - left).total_seconds() - paused


def main():
    began = monotonic_clock.monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument('--soak', required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    if conninfo_to_dict(settings.database_url).get('dbname') != 'dehps_next':
        raise SystemExit('Only read-only Next primary observation is supported')
    db = Database(settings)
    try:
        with db.pool.connection() as connection, connection.transaction():
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            connection.execute('SET LOCAL jit=off')
            assert connection.execute('SHOW statement_timeout').fetchone()['statement_timeout'] == '15s'
            run = connection.execute('SELECT * FROM research_soaks WHERE id=%s', (args.soak,)).fetchone()
            assert run and run['interval_seconds'] == 300
            assert run['deadline'] - run['started_at'] == timedelta(hours=24)
            captured = connection.execute('SELECT now() AS at').fetchone()['at']
            start, end = run['started_at'], min(captured, run['deadline'])
            assert start <= end
            pauses = pause_intervals(connection, start, end)
            bounds = connection.execute('SELECT min(seq) AS low,max(seq) AS high '
                                        'FROM research_memory_events').fetchone()
            markers, blocks = [], 0
            low, high = bounds['low'] or 0, (bounds['high'] or 0) + 1
            for block in range(low, high, BLOCK):
                markers.extend(connection.execute(
                    """SELECT seq,kind,(payload->>'completed_at')::timestamptz AS at
                    FROM research_memory_events WHERE seq>=%s AND seq<%s
                    AND kind IN ('EVALUATION','FIT_PROGRESS')
                    AND coalesce((payload->'execution'->>'gradient_steps_executed_this_attempt')::bigint,
                                 (payload->>'gradient_steps')::bigint)>0
                    AND (payload->>'completed_at')::timestamptz>=%s
                    AND (payload->>'completed_at')::timestamptz<=%s""",
                    (block, min(block + BLOCK, high), start, end),
                ).fetchall())
                blocks += 1
            markers.sort(key=lambda row: (row['at'], row['seq']))
            points = [{'at': start, 'boundary': 'OBSERVATION_START'}, *markers,
                      {'at': end, 'boundary': 'OBSERVATION_END'}]
            failures, maximum = [], None
            for left, right in pairwise(points):
                gap = {'left': left, 'right': right,
                       'wall_seconds': (right['at'] - left['at']).total_seconds(),
                       'unpaused_seconds': active_seconds(left['at'], right['at'], pauses)}
                if maximum is None or gap['unpaused_seconds'] > maximum['unpaused_seconds']:
                    maximum = gap
                if gap['unpaused_seconds'] > STALL_SECONDS:
                    failures.append(gap)
            samples = connection.execute(
                """SELECT count(*) AS samples,count(*) FILTER(
                WHERE (payload->>'review_required')::boolean) AS sampled_warnings
                FROM research_soak_samples WHERE soak_id=%s""", (args.soak,),
            ).fetchone()
        elapsed = captured >= run['deadline']
        complete = elapsed and run['state'] != 'RUNNING'
        print(json.dumps({
            'kind': 'ACTUAL_FIT_CONTINUITY_AUDIT_V1', 'soak': args.soak,
            'audit_wall_seconds': monotonic_clock.monotonic() - began,
            'captured_at': captured, 'start': start, 'end': end, 'soak_state': run['state'],
            'elapsed_24_hours': elapsed, 'sampling_terminal': run['state'] != 'RUNNING',
            'threshold_seconds_unchanged': STALL_SECONDS,
            'sampling_gap_threshold_seconds_unchanged': 600,
            'raw_sampler_max_gap_seconds': run['max_gap_seconds'], 'raw_sampler': samples,
            'snapshot_sequence_range': [low, high], 'blocks': blocks,
            'block_size': BLOCK, 'actual_positive_fit_markers': len(markers),
            'maximum_unpaused_gap': maximum, 'actual_continuity_failures': failures,
            'official_pause_intervals': [{'start': l, 'end': r, 'window': w} for l, r, w in pauses],
            'window_source_sha256': hashlib.sha256(inspect.getsource(training_window).encode()).hexdigest(),
            'actual_continuity_passed': not failures if complete else None,
            'combined_training_observation_passed': bool(not failures and run['state'] == 'OBSERVED_COMPLETE'
                                                        and run['max_gap_seconds'] <= 600) if complete else None,
            'failed_so_far': bool(failures), 'database_writes': 0,
            'scope': 'ACTUAL_TRAINING_CONTINUITY_ONLY;NOT_QWEN_QUALIFICATION_DELIVERY_OR_PREDICTIVE_EVIDENCE',
        }, default=str, indent=2), flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    main()
