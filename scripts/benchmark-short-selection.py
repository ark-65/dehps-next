"""Fresh bounded-thinking4B acceptance; old long-thinking answers are never carried."""

import argparse
import copy
import hashlib
import importlib.util
import json
import time
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest, now
from dehps_next.release import code_identity, numeric_identity
from dehps_next.research_agent import request_json
from dehps_next.research_selection import make_context, mechanism_metrics
from dehps_next.research_selection_evidence import SEMANTIC_FAILURES
from dehps_next.research_short_thinking import PERFORMANCE_GATE, performance, profile, render

REQUEST_INTERVAL_SECONDS = 300


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', required=True)
    parser.add_argument('--receipt', required=True)
    args = parser.parse_args()
    if not 1 <= len(args.corpus) <= 50:
        raise SystemExit('Use a bounded new corpus identity')
    spec = importlib.util.spec_from_file_location('short_mechanism', Path(__file__).with_name('benchmark-selection.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    s = Settings.from_env()
    if (
        conninfo_to_dict(s.database_url).get('dbname') != 'dehps_next_qwen4_short_acceptance'
        or s.runtime.name != 'short-case'
    ):
        raise SystemExit('Only the named isolated Next acceptance database/runtime is allowed')
    d = Database(s)
    d.migrate()
    a = Artifacts(s, d)
    m.CORPUS, m.CONTEXT = args.corpus, args.corpus + '-context'
    inventory = request_json('/api/tags')['models']
    config = profile(next(r['digest'] for r in inventory if r['name'] == 'qwen3:4b'))
    header = m.prepare(d, a)
    freeze = {
        'kind': 'SHORT_QWEN4_ACCEPTANCE_V1', 'corpus': args.corpus, 'profile': config,
        'profile_id': digest(config), 'controller_source': code_identity(), 'numeric': numeric_identity(),
        'source_cases': header['source'], 'case_scope': 'FROZEN_REAL_OUTCOMES;ALL144_ANSWERS_NEW;NO_LONG_REPLY_REUSE',
        'request_interval_seconds': REQUEST_INTERVAL_SECONDS, 'performance_gate': PERFORMANCE_GATE,
        'gate': header['gate'], 'futility': header['futility'],
        'drivers': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (Path(__file__), Path(m.__file__))},
        'physical_recovery': 'SAME_INPUT_SEED;RECEIPTS_RETAINED;NEVER_RETRY_A_PERFORMED_WRONG_ANSWER',
        'primary_activation': False,
    }
    with d.pool.connection() as c, c.transaction():
        c.execute('INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                  (args.corpus+'-contract', Jsonb(freeze), digest(freeze)))
        assert c.execute('SELECT sha256 FROM research_review_studies WHERE id=%s',
                         (args.corpus+'-contract',)).fetchone()['sha256'] == digest(freeze)
        node = c.execute('SELECT id FROM research_nodes WHERE campaign_id=%s', (m.CONTEXT,)).fetchone()
        assert not c.execute("SELECT 1 FROM jobs WHERE kind='RESEARCH_PLAN' AND state='RUNNING' AND lease_until>now()").fetchone()
        c.execute("UPDATE jobs SET state='SNAPSHOT_EXCLUDED' WHERE kind='RESEARCH_PLAN' AND state='READY' AND research_node_id!=%s", (node['id'],))
    original = m.recoverable_review

    def fresh_review(db, artifacts, campaign, frozen, row, p, arm, variant, seed, **kw):
        expected, _, _, _, _ = make_context(frozen['parent_spec'], frozen['parent_business'],
            row['basis']['offered'], row['basis']['memory'], count=kw.get('count', 1),
            feedback=arm=='feedback', **row['basis']['variants'][variant])
        while True:
            last = db.rows("""SELECT created_at FROM research_model_calls WHERE campaign_id=%s
                AND stage LIKE 'CANDIDATE_SELECTION_V4_%%' ORDER BY id DESC LIMIT 1""", (campaign['id'],))
            if last:
                delay = REQUEST_INTERVAL_SECONDS-(now()-last[0]['created_at']).total_seconds()
                if delay > 0:
                    time.sleep(min(delay, 30))
                    continue
            result = original(db, artifacts, campaign, frozen, row, p, arm, variant, seed, **kw)
            actual = db.rows("""SELECT * FROM research_model_calls WHERE campaign_id=%s
                AND stage=%s ORDER BY id DESC LIMIT 1""",
                (campaign['id'], 'CANDIDATE_SELECTION_V4_'+arm.upper()))
            if actual:
                call = actual[0]
                metrics = call['metrics'] or {}
                logical = metrics.get('logical_request')
                if logical:
                    prompt = json.loads(artifacts.read(logical))
                    context = json.loads(prompt['messages'][1]['content'])
                    context.pop('output_contract', None)
                    if digest(context) != digest(expected):
                        raise RuntimeError('Actual provider input differs from the frozen logical slot')
                    first_receipt = metrics.get('thinking_receipt')
                    verified = False
                    if first_receipt:
                        first_request = json.loads(artifacts.read(first_receipt['request']))
                        first_response = json.loads(artifacts.read(first_receipt['response']))
                        second_request = json.loads(artifacts.read(call['request']))
                        prefix = render(prompt['messages'])
                        thought = first_response['thinking'].split('</think>', 1)[0]
                        assert first_request['prompt'] == prefix
                        assert second_request['prompt'] == prefix+thought+'\n</think>\n\n'
                        assert first_request['options']['num_predict'] == 512
                        assert second_request['options']['num_predict'] == 1024
                        assert first_request['options']['num_thread'] == second_request['options']['num_thread'] == 4
                        assert second_request['format'] == prompt['format']
                        verified = True
                    result['actual_call'] = {'call_id': call['id'], 'model_digest': call['model_digest'],
                        'request': call['request'], 'metrics': copy.deepcopy(metrics),
                        'logical_input_digest': digest(context), 'actual_prefix_verified': verified}
            if result['valid'] or result.get('error') in SEMANTIC_FAILURES:
                assert result.get('actual_call'), 'Performed answer requires its exact source-local provider receipt'
                return result
            print(json.dumps({'physical_void': result, 'logical_choice_recorded': False}), flush=True)
            time.sleep(15)

    m.recoverable_review = fresh_review
    try:
        result = m.run_profile(d, a, header, config)
        measured = performance(d, result['study'], config)
        passed = bool(result['passed'] and measured['passed'])
        qualification = {'kind': 'SHORT_QWEN4_QUALIFICATION_V1', 'passed': passed,
                         'mechanism_study': result['study'], 'measurement': measured,
                         'mechanism_passed': result['passed'], 'profile_id': digest(config)}
        study = result['study']+'-short-qualification'
        with d.pool.connection() as c, c.transaction():
            c.execute('INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                      (study, Jsonb(freeze), digest(freeze)))
            c.execute('INSERT INTO research_review_results(study_id,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING',
                      (study, Jsonb(qualification)))
        if passed:
            actual = mechanism_metrics(d, result['study'], config)
            assert all(abs(actual[k]-result[k])<1e-12 for k in actual)
        receipt = {'passed': passed, 'result': result, 'qualification': qualification,
                   'corpus': args.corpus, 'primary_activation': False}
        Path(args.receipt).write_text(json.dumps(receipt, indent=2)+'\n')
        print(json.dumps(qualification), flush=True)
    finally:
        d.close()


if __name__ == '__main__':
    main()
