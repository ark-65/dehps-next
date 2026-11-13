"""Two declared known-input state probes, never qualification or replacement answers."""

import argparse
import copy
import hashlib
import json
import signal
import socket
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
from dehps_next.research_selection import make_context
from dehps_next.resources import Resources
from dehps_next.training_window import status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trial', required=True, choices=('warm', 'fresh'))
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    operation = Path('/operation')
    frozen = json.loads((operation / 'runner-state-diagnostic.json').read_text())
    assert code_identity() == frozen['code'] and numeric_identity() == frozen['numeric']
    original = json.loads((operation / 'revalidation-source.json').read_text())
    assert hashlib.sha256((operation / 'source-export.json').read_bytes()).hexdigest() == frozen['source_sha256']
    header = original['header']
    config = copy.deepcopy(original['profile'])
    config['options']['num_batch'] = 512
    settings = Settings.from_env()
    assert conninfo_to_dict(settings.database_url)['dbname'] == 'dehps_next_qwen_latency_20261113'
    assert settings.runtime.name == 'qwen-latency-case'
    assert settings.inference_threads == settings.inference_busy_threads == 4
    db = Database(settings)
    artifacts = Artifacts(settings, db)
    row = db.rows('SELECT * FROM research_review_pairs WHERE study_id=%s AND pair=0',
                  ('qwen4-latency-20261113-v1',))[0]
    assert digest(row['basis']) == original['pair_hashes']['0']
    context, schema, *_ = make_context(
        header['parent_spec'], header['parent_business'], row['basis']['offered'], row['basis']['memory'],
        count=1, feedback=False, selector_contract=config['selector_contract'], **row['basis']['variants']['base'],
    )
    assert digest(context) == original['input_hashes']['0:no_feedback:base:1729']
    prior = db.rows('SELECT * FROM research_model_calls WHERE id=23')[0]
    assert prior['state'] == 'FAILED' and prior['metrics']['failure_code'] == 'LOCAL_MODEL_REPETITION'
    logical = json.loads(artifacts.read(prior['metrics']['logical_request']))
    expected = {**logical, 'options': {**logical['options'], 'num_batch': 512}}
    assert digest(expected) == frozen['explicit_batch_logical_request_sha256']
    assert logical['format'] == schema and config['options']['seed'] == 1729
    if args.prepare_only:
        print(json.dumps({'prepared': True, 'input_digest': digest(context),
                          'logical_request_sha256': digest(expected), 'source': code_identity()}), flush=True)
        db.close()
        return
    observed = json.loads((operation / ('runner-' + args.trial + '-environment.json')).read_text())
    assert endpoint() == ('http://next-inference:11434' if args.trial == 'warm'
                          else 'http://next-review-inference:11434')
    host = 'next-inference' if args.trial == 'warm' else 'next-review-inference'
    assert socket.gethostbyname(host) == observed['ip']
    assert observed['backend_image'] == frozen['backend_image'] and observed['cpu_quota'] == 400000
    assert observed['primary_cpu_quota'] == 1200000
    assert args.trial != 'warm' or observed['pids_before']
    study = 'qwen-runner-state-20261113-v1'
    with db.pool.connection() as connection:
        connection.execute('INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) '
                           'ON CONFLICT DO NOTHING', (study, Jsonb(frozen), digest(frozen)))
        assert connection.execute('SELECT sha256 FROM research_review_studies WHERE id=%s',
                                  (study,)).fetchone()['sha256'] == digest(frozen)
    assert not db.rows('SELECT 1 FROM research_review_selections WHERE study_id=%s AND arm=%s', (study, args.trial))
    job = db.claim('qwen-runner-state-diagnostic', role='planning')
    if not job:
        raise RuntimeError('No actual planning admission; do not bypass resource/draw gates')
    campaign = db.rows('SELECT r.* FROM research_campaigns r JOIN research_nodes n ON n.campaign_id=r.id '
                       'WHERE n.id=%s', (job['research_node_id'],))[0]
    assert campaign['id'] == 'qwen4-latency-20261113-v1-context'
    artifacts.reservation_token = job['token']
    stop, lost = threading.Event(), []

    def pulse():
        if lost:
            raise RuntimeError('Heartbeat lost')
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

    original_infer = research_selection.infer

    def tagged_infer(db, artifacts, campaign, job, stage, *values, **options):
        assert stage == 'CANDIDATE_SELECTION_V4_NO_FEEDBACK'
        return original_infer(db, artifacts, campaign, job,
                              'CANDIDATE_SELECTION_V4_RUNNER_STATE_' + args.trial.upper(), *values, **options)

    research_selection.infer = tagged_infer
    keeper = threading.Thread(target=heartbeat, daemon=True)
    keeper.start()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    started = time.monotonic()
    result = {'trial': args.trial, 'valid': False, 'error': 'OPERATOR_INTERRUPTED',
              'observed_at': now().isoformat(), 'profile_id': digest(config),
              'scope': 'KNOWN_FAILED_INPUT_DIAGNOSTIC;NO_REPLACEMENT_OR_QUALIFICATION;NO_NEW_FITS'}
    try:
        _, receipt, proof = research_selection.select(
            db, artifacts, campaign, job, pulse, header['parent_spec'], header['parent_business'],
            row['basis']['offered'], row['basis']['memory'], config, count=1, feedback=False,
            **row['basis']['variants']['base'],
        )
        assert proof['input_digest'] == digest(context)
        result.update(valid=True, error=None, receipt=receipt, proof=proof)
    except (DatabaseError, DomainError, PoolTimeout, TimeoutError, RuntimeError) as exc:
        result.update(error=getattr(exc, 'code', type(exc).__name__), detail=str(exc)[:400])
    finally:
        stop.set()
        keeper.join(2)
        result['elapsed_seconds'] = time.monotonic() - started
        result['native_calls'] = db.rows('SELECT * FROM research_model_calls WHERE attempt_id=%s ORDER BY id',
                                         (job['token'],))
        if result['native_calls']:
            actual = result['native_calls'][0]['metrics'].get('logical_request')
            assert actual or not result['valid']
            if actual:
                assert actual['sha256'] == digest(expected)
        db.defer(job, 'YIELD_RUNNER_STATE_DIAGNOSTIC_FINISHED', seconds=0)
        Resources(db).finish(job['token'], result['elapsed_seconds'], 0)
        with db.pool.connection() as connection:
            connection.execute('INSERT INTO research_review_selections(study_id,pair,arm,payload) '
                               'VALUES(%s,%s,%s,%s)',
                               (study, 0 if args.trial == 'warm' else 1, args.trial,
                                Jsonb(json.loads(json.dumps(result, default=str)))))
        (operation / ('runner-' + args.trial + '-result.json')).write_text(
            json.dumps(result, default=str, indent=2) + '\n')
        db.close()
    print(json.dumps({k: result[k] for k in ('trial', 'valid', 'error', 'elapsed_seconds')}), flush=True)


if __name__ == '__main__':
    main()
