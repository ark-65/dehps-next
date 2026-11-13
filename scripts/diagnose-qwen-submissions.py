"""Four declared known-input runtime probes; never count them as qualification."""

import argparse
import copy
import hashlib
import json
import signal
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

from psycopg import DatabaseError
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest, now
from dehps_next.errors import DomainError
from dehps_next.release import code_identity, numeric_identity
from dehps_next.research_agent import endpoint
from dehps_next.research_selection import make_context, select
from dehps_next.resources import Resources
from dehps_next.training_window import status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trial', required=True, choices=('a0', 'b2', 'b0', 'a2'))
    args = parser.parse_args()
    operation = Path('/operation')
    frozen = json.loads((operation / 'submission-diagnostic.json').read_text())
    source = json.loads((operation / 'production-request-cases.json').read_text())
    assert digest(source) == frozen['source_sha256']
    assert code_identity() == frozen['code'] and numeric_identity() == frozen['numeric']
    observed = json.loads((operation / (args.trial + '-environment.json')).read_text())
    trial = next(r for r in frozen['trials'] if r['id'] == args.trial)
    assert observed['serialized'] == trial['serialized']
    assert observed['primary_cpu_quota'] == 1200000 and observed['primary_cpu_period'] == 100000
    assert observed['helper_cpu_quota'] == 400000 and observed['helper_cpu_period'] == 100000
    assert observed['backend_image'] == frozen['backend_image']
    assert observed['model_cache_read_only'] and observed['fresh_backend_process']
    settings = Settings.from_env()
    assert conninfo_to_dict(settings.database_url)['dbname'] == 'dehps_next_qwen_latency_20261113'
    assert settings.runtime.name == 'qwen-latency-case'
    assert endpoint() == 'http://next-review-inference:11434'
    assert socket.gethostbyname('next-review-inference') == observed['review_ip']
    db = Database(settings)
    artifacts = Artifacts(settings, db)
    study = 'qwen-submission-diagnostic-20261113-v1'
    with db.pool.connection() as c:
        c.execute('INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) '
                  'ON CONFLICT DO NOTHING', (study, Jsonb(frozen), digest(frozen)))
        assert c.execute('SELECT sha256 FROM research_review_studies WHERE id=%s',
                         (study,)).fetchone()['sha256'] == digest(frozen)
    if db.rows('SELECT 1 FROM research_review_pairs WHERE study_id=%s AND pair=%s', (study, trial['index'])):
        raise RuntimeError('A diagnostic trial was already performed; never resample it')
    case = source[str(trial['source_call'])]
    config = copy.deepcopy(case['profile'])
    if trial['serialized']:
        config['backend']['serialize_submissions'] = True
    context = make_context(case['parent'], case['business'], case['offered'], case['memory'],
                           count=2, layout_seed=case['layout_seed'], id_seed=case['id_seed'],
                           selector_contract=config['selector_contract'])
    assert digest(context[0]) == case['input_digest'] and context[1] == case['schema']
    job = db.claim('qwen-submission-diagnostic', role='planning')
    if not job:
        raise RuntimeError('Planning admission unavailable; do not bypass real resource/draw guards')
    campaign = db.rows('SELECT r.* FROM research_campaigns r JOIN research_nodes n ON n.campaign_id=r.id '
                       'WHERE n.id=%s', (job['research_node_id'],))[0]
    assert campaign['id'] == 'qwen4-latency-20261113-v1-context'
    artifacts.reservation_token = job['token']
    stop, lost = threading.Event(), []

    def pulse():
        if lost:
            raise RuntimeError('Diagnostic lease heartbeat lost')
        with db.pool.connection() as c:
            if status(c)['paused']:
                raise RuntimeError('Official draw pause holds diagnostic generation')
        db.heartbeat(job)

    def heartbeat():
        while not stop.wait(10):
            try:
                db.heartbeat(job)
            except (DatabaseError, DomainError, PoolTimeout, TimeoutError) as exc:
                lost.append(type(exc).__name__)
                return

    keeper = threading.Thread(target=heartbeat, daemon=True)
    keeper.start()
    original_open = urllib.request.urlopen

    class ObservedResponse:
        def __init__(self, response):
            self.response = response

        def __enter__(self):
            self.response.__enter__()
            return self

        def __exit__(self, *values):
            return self.response.__exit__(*values)

        def __getattr__(self, name):
            return getattr(self.response, name)

        def readline(self, *values):
            line = self.response.readline(*values)
            try:
                frame = json.loads(line)
            except (ValueError, UnicodeError):
                return line
            if isinstance(frame, dict) and frame.get('error'):
                with (operation / (args.trial + '-provider-errors.jsonl')).open('a') as output:
                    output.write(json.dumps({'at': time.time(), 'frame': frame,
                                              'sha256': hashlib.sha256(line).hexdigest()}) + '\n')
            return line

    def audit_open(request, *values, **options):
        response = original_open(request, *values, **options)
        return ObservedResponse(response) if request.full_url.endswith('/api/generate') else response

    urllib.request.urlopen = audit_open
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    started = time.monotonic()
    result = {'trial': trial, 'profile_id': digest(config), 'observed_at': now().isoformat(),
              'valid': False, 'error': 'OPERATOR_INTERRUPTED_BEFORE_COMPLETE_RECEIPT',
              'scope': 'KNOWN_PRODUCTION_INPUT_RUNTIME_DIAGNOSTIC;NOT_QUALIFICATION_OR_PREDICTIVE_GAIN'}
    try:
        _, receipt, proof = select(db, artifacts, campaign, job, pulse, case['parent'], case['business'],
                                   case['offered'], case['memory'], config, count=2,
                                   layout_seed=case['layout_seed'], id_seed=case['id_seed'])
        result.update(valid=True, error=None, receipt=receipt, input_digest=proof['input_digest'])
    except (DatabaseError, DomainError, PoolTimeout, TimeoutError, RuntimeError) as exc:
        result.update(valid=False, error=getattr(exc, 'code', type(exc).__name__), detail=str(exc)[:600])
    finally:
        stop.set()
        keeper.join(2)
        result['elapsed_seconds'] = time.monotonic() - started
        result['native_calls'] = db.rows('SELECT * FROM research_model_calls WHERE job_id=%s '
                                         'AND attempt_id=%s ORDER BY id', (job['id'], job['token']))
        if result['native_calls']:
            logical = result['native_calls'][0]['metrics'].get('logical_request')
            assert not logical or logical['sha256'] == case['logical_request_sha256']
        db.defer(job, 'YIELD_SUBMISSION_DIAGNOSTIC_FINISHED', seconds=0)
        Resources(db).finish(job['token'], result['elapsed_seconds'], 0)
        with db.pool.connection() as c:
            c.execute('INSERT INTO research_review_pairs(study_id,pair,basis,sha256) VALUES(%s,%s,%s,%s)',
                      (study, trial['index'], Jsonb(trial), digest(trial)))
            c.execute('INSERT INTO research_review_selections(study_id,pair,arm,payload) VALUES(%s,%s,%s,%s)',
                      (study, trial['index'], args.trial, Jsonb(json.loads(json.dumps(result, default=str)))))
        (operation / (args.trial + '-result.json')).write_text(json.dumps(result, default=str, indent=2) + '\n')
        db.close()
    print(json.dumps({k: result[k] for k in ('trial', 'valid', 'elapsed_seconds', 'scope')}), flush=True)


if __name__ == '__main__':
    main()
