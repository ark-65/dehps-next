"""Read complete Qwen observation windows across bounded graph retirement.

No model requests, counter estimates, primary state changes or qualification.
"""

import argparse
import hashlib
import json
import math
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest
from dehps_next.release import code_identity

RECEIPT_BYTES_MAX = 32 * 1024**2
QUERY = """WITH observed_window AS (
 SELECT *,coalesce(finished_at,now()) until_at,now()>=deadline AND finished_at>=deadline elapsed_complete
 FROM research_soaks WHERE id=%s
), archive_campaigns AS (
 SELECT DISTINCT a.campaign_id FROM qwen_selection_audits a,observed_window w WHERE a.created_at>=w.started_at
), archived AS (
 SELECT e.seq,e.event_key,e.payload->>'campaign' campaign,n.call
 FROM archive_campaigns a JOIN research_memory_events e
 ON e.event_key='campaign:'||a.campaign_id AND e.kind='CAMPAIGN_ARCHIVE'
 CROSS JOIN LATERAL jsonb_array_elements(e.payload->'call_receipts') n(call)
), native AS (
 SELECT m.id,m.campaign_id,m.job_id,m.attempt_id::text,m.stage,m.state,m.created_at,m.model_digest,
 m.request,m.response,m.metrics,'LIVE_NATIVE' evidence_source,NULL::bigint archive_seq,NULL::text archive_event_key
 FROM research_model_calls m,observed_window w WHERE m.created_at>=w.started_at AND m.created_at<=w.until_at
 UNION ALL
 SELECT (a.call->>'id')::bigint,a.campaign,NULL::text,NULL::text,a.call->>'stage',a.call->>'state',
 (a.call->>'created_at')::timestamptz,a.call->>'model_digest',a.call->'request',a.call->'response',
 a.call->'metrics','IMMUTABLE_CAMPAIGN_ARCHIVE',a.seq,a.event_key
 FROM archived a,observed_window w
 WHERE (a.call->>'created_at')::timestamptz>=w.started_at AND (a.call->>'created_at')::timestamptz<=w.until_at
) SELECT json_build_object('run',to_jsonb(w),'native',(
 SELECT coalesce(json_agg(json_build_object('id',m.id,'campaign',m.campaign_id,'job',m.job_id,'attempt',m.attempt_id,
 'stage',m.stage,'state',m.state,'at',m.created_at,'wall',m.metrics->'wall_seconds',
 'failure',m.metrics->'failure_code','input',m.metrics->'prompt_eval_count','output',m.metrics->'eval_count',
 'total_ns',m.metrics->'total_duration','prefix',m.metrics->'thinking_call_id','model_digest',m.model_digest,
 'request',m.request,'response',m.response,'prefix_request',m.metrics#>'{thinking_receipt,request}',
 'prefix_response',m.metrics#>'{thinking_receipt,response}','prefix_model',m.metrics#>'{thinking_receipt,model_digest}',
 'prefix_counts',jsonb_build_object('input',m.metrics#>'{thinking_receipt,metrics,prompt_eval_count}',
 'output',m.metrics#>'{thinking_receipt,metrics,eval_count}','total_ns',m.metrics#>'{thinking_receipt,metrics,total_duration}'),
 'evidence_source',m.evidence_source,'archive_seq',m.archive_seq,'archive_event_key',m.archive_event_key) ORDER BY m.id),'[]'::json)
 FROM native m),'accepted',(
 SELECT coalesce(json_agg(x.id),'[]'::json) FROM (SELECT DISTINCT a.call_id id FROM qwen_selection_audits a
 WHERE a.source='QWEN_COMPARATIVE' AND a.call_id IS NOT NULL AND a.created_at>=w.started_at)x
)) AS observation FROM observed_window w"""


def counted(row):
    return bool(row and row['state'] == 'SUCCEEDED' and all(
        type(row[key]) is int and row[key] > 0 for key in ('input', 'output', 'total_ns')))


def paired(row, prefix):
    return bool(counted(row) and counted(prefix)
                and row['campaign'] == prefix['campaign']
                and row['model_digest'] == prefix['model_digest'] == row['prefix_model']
                and row['prefix_request'] == prefix['request']
                and row['prefix_response'] == prefix['response']
                and all(isinstance(row[key], dict) and row[key].get('sha256')
                        for key in ('prefix_request', 'prefix_response'))
                and row['prefix_counts'] == {key: prefix[key] for key in ('input', 'output', 'total_ns')})


def summarize(data):
    native = {}
    common = ('id', 'stage', 'state', 'model_digest', 'request', 'response',
              'input', 'output', 'total_ns', 'wall', 'prefix')
    for row in data['native']:
        previous = native.get(row['id'])
        if previous:
            assert all(previous[key] == row[key] for key in common), 'Conflicting native/archive evidence'
        native[row['id']] = row
    logical = [row for _, row in sorted(native.items()) if row['stage'].startswith('CANDIDATE_SELECTION_V4_')]
    accepted = [row for row in logical if row['id'] in data['accepted']]
    complete = [row for row in accepted if paired(row, native.get(row['prefix']))]
    walls = sorted(row['wall'] for row in complete
                   if type(row['wall']) in (int, float) and math.isfinite(row['wall']) and row['wall'] >= 0)
    return {'at': time.time(), 'observer_version': 'LIVE_AND_ARCHIVE_V1', 'window': data['run'],
            'logical_attempts': len(logical),
            'native_parsed_succeeded': sum(row['state'] == 'SUCCEEDED' for row in logical),
            'failed': sum(row['state'] == 'FAILED' for row in logical),
            'pending_logical': sum(row['state'] == 'RESERVED' for row in logical),
            'accepted_comparative_selection_ids': [row['id'] for row in accepted],
            'accepted_with_complete_two_phase_native_counts': [row['id'] for row in complete],
            'accepted_binding_review_ids': [row['id'] for row in accepted if row not in complete],
            'accepted_complete_latency': {'n': len(walls), 'mean': sum(walls)/len(walls) if walls else None,
                'nearest_rank_p95': walls[math.ceil(.95*len(walls))-1] if walls else None},
            'all_outcomes': logical, 'all_native_observations': list(native.values()),
            'native_counts_estimated': False, 'repair_epoch': False,
            'scope': 'ACTUAL_PRIMARY_LIVE_AND_IMMUTABLE_ARCHIVE_OBSERVATION;NOT_144_QUALIFICATION_OR_PREDICTIVE_GAIN'}


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def store(output, value):
    root = output.parent
    assert root.is_dir() and not root.is_symlink()
    receipts = root / 'selection-observation-receipts'
    receipts.mkdir(exist_ok=True)
    assert not receipts.is_symlink()
    entries = list(receipts.iterdir())
    assert not any(path.is_symlink() for path in entries)
    size = sum(path.stat().st_size for path in entries if path.is_file())
    for row in value['all_native_observations']:
        if row['state'] == 'RESERVED':
            continue
        evidence = {'window': value['window']['id'], 'native': row,
                    'accepted': row['id'] in value['accepted_comparative_selection_ids']}
        path = receipts / (str(row['id']) + '-' + digest(evidence) + '.json')
        if path.exists():
            assert json.loads(path.read_text()) == evidence
            continue
        raw = json.dumps(evidence, indent=2, allow_nan=False) + '\n'
        assert size + len(raw.encode()) <= RECEIPT_BYTES_MAX, 'Stop observer only; evidence storage cap'
        with path.open('x') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        size += len(raw.encode())
    sync_directory(receipts)
    if output.exists():
        previous = json.loads(output.read_text())
        if previous.get('observer_version') == value['observer_version']:
            assert previous['window']['id'] == value['window']['id']
            seen = {row['id'] for row in value['all_native_observations']}
            assert all(row['id'] in seen for row in previous['all_native_observations']), 'Observation lost native history'
            assert set(previous['accepted_comparative_selection_ids']) <= set(value['accepted_comparative_selection_ids'])
    pending = output.with_name(output.name + '.pending')
    with pending.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(output)
    sync_directory(root)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--soak', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--controller-source', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    settings = Settings.from_env()
    assert conninfo_to_dict(settings.database_url)['dbname'] == 'dehps_next'
    assert code_identity() == args.controller_source
    db = Database(settings)
    try:
        while True:
            started = time.monotonic()
            with db.pool.connection() as connection, connection.transaction():
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                connection.execute("SET LOCAL statement_timeout='8s'")
                row = connection.execute(QUERY, (args.soak,)).fetchone()
                assert row, 'Missing actual soak; never publish an empty successful window'
                data = row['observation']
            run = data['run']
            assert run['interval_seconds'] == 300
            assert datetime.fromisoformat(run['deadline']) - datetime.fromisoformat(run['started_at']) == timedelta(hours=24)
            value = summarize(data)
            value['capture_seconds'] = time.monotonic() - started
            value['observer_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            store(args.output, value)
            done = (run['state'] != 'RUNNING' and run['elapsed_complete'] is True
                    and not any(row['state'] == 'RESERVED' for row in value['all_native_observations']))
            if done:
                terminal = args.output.with_name('accepted-selection-24h-terminal.json')
                if not terminal.exists():
                    with terminal.open('x') as stream:
                        json.dump(value, stream, indent=2, allow_nan=False)
                        stream.flush()
                        os.fsync(stream.fileno())
                    sync_directory(terminal.parent)
            print(json.dumps({key: value[key] for key in ('logical_attempts', 'failed', 'pending_logical',
                  'accepted_comparative_selection_ids', 'accepted_complete_latency', 'capture_seconds')}), flush=True)
            if args.once or done:
                break
            time.sleep(60)
    finally:
        db.close()


if __name__ == '__main__':
    main()
