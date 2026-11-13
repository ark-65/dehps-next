"""Fresh matched512/128 known-input causal probes; no qualification credit."""

import argparse
import copy
import importlib.util
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

from psycopg import DatabaseError
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout

from dehps_next import research_selection
from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest, now
from dehps_next.errors import DomainError
from dehps_next.release import code_identity, numeric_identity
from dehps_next.research_agent import endpoint
from dehps_next.resources import Resources
from dehps_next.training_window import status


def immutable(path, value):
    raw = json.dumps(value, default=str, indent=2) + '\n'
    pending = path.with_name(path.name + '.pending')
    with pending.open('x') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    os.link(pending, path)
    pending.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trial', choices=('a-large', 'b-small', 'b-large', 'a-small'))
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    op = Path('/operation')
    frozen = json.loads((op / 'freeze.json').read_text())
    cases = json.loads((op / 'source-cases.json').read_text())
    assert digest(cases) == frozen['cases_sha256']
    assert code_identity() == frozen['code'] and numeric_identity() == frozen['numeric']
    settings = Settings.from_env()
    assert conninfo_to_dict(settings.database_url)['dbname'] == 'dehps_next_qwen_latency_20261113'
    assert settings.runtime.name == 'qwen-latency-case'
    assert settings.inference_threads == settings.inference_busy_threads == 4
    db = Database(settings)
    artifacts = Artifacts(settings, db)
    for trial in frozen['trials']:
        case = cases[trial['case']]
        context, schema, *_ = research_selection.make_context(
            case['parent'], case['business'], case['offered'], case['memory'], count=case['count'],
            feedback=case['feedback'], layout_seed=case['layout_seed'], id_seed=case['id_seed'],
            selector_contract=case['profile']['selector_contract'],
        )
        assert digest(context) == case['input_digest'] and schema == case['schema']
        payload = case['original_payload']
        assert digest(payload) == case['original_logical_sha256']
        assert digest({**payload, 'options': {**payload['options'], 'num_batch': trial['batch']}}) == trial['request_sha256']
    spec = importlib.util.spec_from_file_location('mechanism', op / 'drivers/benchmark-selection.py')
    mechanism = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mechanism)
    mechanism.CORPUS, mechanism.CONTEXT = frozen['corpus'], frozen['context']
    mechanism.prepare(db, artifacts)
    with db.pool.connection() as connection, connection.transaction():
        connection.execute('INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) '
                           'ON CONFLICT DO NOTHING', (frozen['study'], Jsonb(frozen), digest(frozen)))
        assert connection.execute('SELECT sha256 FROM research_review_studies WHERE id=%s',
                                  (frozen['study'],)).fetchone()['sha256'] == digest(frozen)
        for index, trial in enumerate(frozen['trials']):
            connection.execute('INSERT INTO research_review_pairs(study_id,pair,basis,sha256) '
                               'VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                               (frozen['study'], index, Jsonb(trial), digest(trial)))
            assert connection.execute('SELECT sha256 FROM research_review_pairs WHERE study_id=%s AND pair=%s',
                                      (frozen['study'], index)).fetchone()['sha256'] == digest(trial)
    if args.prepare_only:
        immutable(op / 'preparation-acceptance.json', {'prepared': True, 'inputs_verified': 4,
                  'pair_rows_committed': 4, 'source': code_identity(), 'numeric': numeric_identity(),
                  'model_requests': 0, 'context': frozen['context']})
        db.close()
        return
    assert args.trial
    assert endpoint() == 'http://next-review-inference:11434'
    trial = next(t for t in frozen['trials'] if t['id'] == args.trial)
    index = frozen['trials'].index(trial)
    stage = 'CANDIDATE_SELECTION_V4_BATCH_DIAG_' + args.trial.upper()
    assert not db.rows('SELECT id FROM research_model_calls WHERE campaign_id=%s AND stage=%s',
                       (frozen['context'], stage)), 'Never resample an existing native attempt'
    assert not db.rows('SELECT 1 FROM research_review_selections WHERE study_id=%s AND pair=%s',
                       (frozen['study'], index))
    observed = json.loads((op / (args.trial + '-environment.json')).read_text())
    assert observed['cold_backend'] and observed['primary_cpu_quota'] == 1200000
    assert observed['helper_cpu_quota'] == 400000 and not observed['serialize_submissions']
    case = cases[trial['case']]
    profile = copy.deepcopy(case['profile'])
    profile['options']['num_batch'] = trial['batch']
    job = db.claim('qwen-batch-diag-' + args.trial, role='planning')
    if not job:
        raise RuntimeError('No actual planning admission; no resource/draw bypass')
    campaign = db.rows('SELECT c.* FROM research_campaigns c JOIN research_nodes n ON n.campaign_id=c.id '
                       'WHERE n.id=%s', (job['research_node_id'],))[0]
    assert campaign['id'] == frozen['context']
    artifacts.reservation_token = job['token']
    immutable(op / (args.trial + '-claimed.json'), {'at': now().isoformat(), 'job': job['id'],
              'attempt': job['token'], 'stage': stage, 'trial': trial})
    stop, lost = threading.Event(), []

    def pulse():
        if lost:
            raise RuntimeError('Heartbeat lost; preserve the attempted cell')
        with db.pool.connection() as connection:
            if status(connection)['paused']:
                raise DomainError('YIELD_DRAW_PAUSE', 'Complete official verification required')
        db.heartbeat(job)

    def heartbeat():
        while not stop.wait(10):
            try:
                db.heartbeat(job)
            except (DatabaseError, DomainError, PoolTimeout, TimeoutError) as exc:
                lost.append(type(exc).__name__)
                return

    original = research_selection.infer

    def tagged(db, artifacts, campaign, job, oldstage, *values, **options):
        assert oldstage.startswith('CANDIDATE_SELECTION_V4_')
        return original(db, artifacts, campaign, job, stage, *values, **options)

    research_selection.infer = tagged
    keeper = threading.Thread(target=heartbeat, daemon=True)
    keeper.start()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    started = time.monotonic()
    result = {'trial': trial, 'valid': False, 'error': 'OPERATOR_INTERRUPTED', 'profile': profile,
              'scope': 'KNOWN_FAILED_INPUT_DIAGNOSTIC;NO_REPLACEMENT_OR_QUALIFICATION;ZERO_FITS'}
    try:
        _, receipt, proof = research_selection.select(
            db, artifacts, campaign, job, pulse, case['parent'], case['business'], case['offered'],
            case['memory'], profile, count=case['count'], feedback=case['feedback'],
            layout_seed=case['layout_seed'], id_seed=case['id_seed'],
        )
        assert proof['input_digest'] == case['input_digest']
        result.update(valid=True, error=None, receipt=receipt, proof=proof)
    except (DatabaseError, DomainError, PoolTimeout, TimeoutError, RuntimeError) as exc:
        result.update(error=getattr(exc, 'code', type(exc).__name__), detail=str(exc)[:500])
    finally:
        stop.set()
        keeper.join(2)
        result['elapsed_seconds'] = time.monotonic() - started
        if result['error'] == 'OPERATOR_INTERRUPTED':
            from dehps_next.local_usage import record

            with db.pool.connection() as connection, connection.transaction():
                db.fence(connection, job)
                interrupted = connection.execute(
                    "SELECT id,metrics FROM research_model_calls WHERE attempt_id=%s AND state='RESERVED' "
                    "FOR UPDATE", (job['token'],)
                ).fetchall()
                for row in interrupted:
                    metrics = {**row['metrics'], 'failure_code': 'OPERATOR_INTERRUPTED_DIAGNOSTIC',
                               'provider_counts_unreported': True}
                    connection.execute("UPDATE research_model_calls SET state='FAILED',metrics=%s WHERE id=%s",
                                       (Jsonb(metrics), row['id']))
                    record(connection, row['id'], metrics)
        result['native_calls'] = db.rows('SELECT * FROM research_model_calls WHERE attempt_id=%s ORDER BY id',
                                         (job['token'],))
        if result['native_calls']:
            ref = result['native_calls'][0]['metrics'].get('logical_request')
            assert ref or not result['valid']
            if ref:
                assert ref['sha256'] == trial['request_sha256']
        payload = json.loads(json.dumps(result, default=str))
        # Preserve the model outcome before any job/result-ledger postprocessing.
        immutable(op / (args.trial + '-native-result.json'), payload)
        try:
            db.defer(job, 'YIELD_BATCH_DIAGNOSTIC_FINISHED', seconds=0)
            Resources(db).finish(job['token'], result['elapsed_seconds'], 0)
            with db.pool.connection() as connection:
                connection.execute('INSERT INTO research_review_selections(study_id,pair,arm,payload) '
                                   'VALUES(%s,%s,%s,%s)', (frozen['study'], index, args.trial, Jsonb(payload)))
            immutable(op / (args.trial + '-ledger.json'), {'committed': True})
        except (DatabaseError, DomainError, PoolTimeout, TimeoutError) as exc:
            immutable(op / (args.trial + '-ledger.json'), {'committed': False, 'error': type(exc).__name__,
                      'no_model_retry_permitted': True})
        db.close()
    print(json.dumps({k: result[k] for k in ('valid', 'error', 'elapsed_seconds')}), flush=True)


if __name__ == '__main__':
    main()
