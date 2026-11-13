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
from dehps_next.errors import DomainError
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
    parser.add_argument('--schedule-amendment', type=Path)
    parser.add_argument('--idle-admission', action='store_true')
    parser.add_argument('--latency-revalidation', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= len(args.corpus) <= 50:
        raise SystemExit('Use a bounded new corpus identity')
    spec = importlib.util.spec_from_file_location('short_mechanism', Path(__file__).with_name('benchmark-selection.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    spec = importlib.util.spec_from_file_location('fresh_slots', Path(__file__).with_name('qwen-fresh-slots.py'))
    fresh_slots = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh_slots)
    s = Settings.from_env()
    database, runtime = ('dehps_next_qwen_latency_20261113', 'qwen-latency-case') if args.latency_revalidation else (
        'dehps_next_qwen4_grounded_acceptance', 'grounded-case')
    if conninfo_to_dict(s.database_url).get('dbname') != database or s.runtime.name != runtime:
        raise SystemExit('Only the named isolated Next acceptance database/runtime is allowed')
    d = Database(s)
    d.migrate()
    a = Artifacts(s, d)
    m.CORPUS, m.CONTEXT = args.corpus, args.corpus + '-context'
    inventory = request_json('/api/tags')['models']
    config = profile(next(r['digest'] for r in inventory if r['name'] == 'qwen3:4b'))
    header = m.prepare(d, a)
    revalidation = None
    if args.latency_revalidation:
        if not args.idle_admission or args.schedule_amendment:
            raise SystemExit('Revalidation retains idle admission and requires a fresh corpus')
        revalidation = json.loads(Path('/operation/revalidation-source.json').read_text())
        assert revalidation['profile'] == config
        assert header['parent_spec'] == revalidation['header']['parent_spec']
        assert header['parent_business'] == revalidation['header']['parent_business']
        rows = d.rows('SELECT pair,basis FROM research_review_pairs WHERE study_id=%s ORDER BY pair', (args.corpus,))
        assert len(rows) == 12
        assert {str(r['pair']): digest(r['basis']) for r in rows} == revalidation['pair_hashes']
        inputs = {}
        for row in rows:
            for variant in header['variants']:
                for seed in header['seeds']:
                    for arm in header['arms']:
                        context = make_context(header['parent_spec'], header['parent_business'],
                            row['basis']['offered'], row['basis']['memory'], count=1,
                            feedback=arm == 'feedback', selector_contract=config['selector_contract'],
                            **row['basis']['variants'][variant])[0]
                        inputs[f"{row['pair']}:{arm}:{variant}:{seed}"] = digest(context)
        assert len(inputs) == 144 and inputs == revalidation['input_hashes']
    prior_failure = d.rows('SELECT payload FROM research_review_results WHERE study_id=%s',
                           ('qwen-mechanism-ed39e4838f547bff',))[0]['payload']
    assert prior_failure['passed'] is False
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
        'supersedes_failed_study': 'qwen-mechanism-ed39e4838f547bff',
        'prior_failure_sha256': digest(prior_failure),
        'development_scope': 'KNOWN_CASE_REGRESSION_AFTER_FAILURE_DIAGNOSIS;FRESH_CALLS;FIXED24_POOL_COMPARISON_SEPARATE',
    }
    admission, amendment = None, None
    if args.idle_admission:
        assert not args.schedule_amendment
        spec = importlib.util.spec_from_file_location('admission', Path(__file__).with_name('qwen-acceptance-admission.py'))
        admission = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(admission)
        freeze['request_interval_seconds'] = None
        freeze['admission_policy'] = admission.POLICY
        freeze['drivers']['qwen-acceptance-admission.py'] = hashlib.sha256(Path(admission.__file__).read_bytes()).hexdigest()
    if revalidation:
        freeze['drivers']['qwen-fresh-slots.py'] = hashlib.sha256(Path(fresh_slots.__file__).read_bytes()).hexdigest()
        freeze['fresh_slot_recovery'] = {
            'started_without_outcome': 'REVIEW_REQUIRED;NEVER_RESAMPLE',
            'performed_before_ledger': 'RECOVER_EXACT_DURABLE_PAYLOAD;NO_MODEL_CALL',
            'retry': 'EVERY_NATIVE_PHASE_FAILED;ACTUAL_ZERO_STREAM_BYTES;NO_GENERATED_TEXT_OR_TOKENS',
            'unclassified_nonempty_failure': 'REVIEW_REQUIRED;NEVER_PHYSICAL_VOID',
        }
        freeze['revalidation_source'] = {
            'study': revalidation['study'], 'protocol_sha256': revalidation['protocol_sha256'],
            'input_manifest_sha256': digest(revalidation['input_hashes']),
            'same_144_inputs_seeds_and_gates': True, 'old_answers_reused': False,
        }
        freeze['primary_priority_admission'] = {
            'fresh_snapshot_seconds_max': 30, 'minimum_primary_headroom_seconds': 900,
            'active_primary_calls_max': 0, 'primary_paused_holds': True,
            'overlap_invalidates_revalidation': True,
        }
    with d.pool.connection() as c, c.transaction():
        if args.schedule_amendment:
            spec = importlib.util.spec_from_file_location('admission', Path(__file__).with_name('qwen-acceptance-admission.py'))
            admission = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(admission)
            amendment = json.loads(args.schedule_amendment.read_text())
            original = c.execute('SELECT protocol,sha256 FROM research_review_studies WHERE id=%s',
                                 (args.corpus+'-contract',)).fetchone()
            assert original and digest(original['protocol']) == original['sha256']
            assert amendment['kind'] == 'QWEN_ACCEPTANCE_SCHEDULING_AMENDMENT_V1'
            assert amendment['id'] == args.corpus+'-schedule-v2'
            assert amendment['original_contract_sha256'] == original['sha256']
            assert amendment['policy'] == admission.POLICY
            assert amendment['drivers'] == {**freeze['drivers'], 'qwen-acceptance-admission.py':
                hashlib.sha256(Path(admission.__file__).read_bytes()).hexdigest()}
            assert {k: v for k, v in freeze.items() if k != 'drivers'} == {
                k: v for k, v in original['protocol'].items() if k != 'drivers'}
            assert freeze['drivers']['benchmark-selection.py'] == original['protocol']['drivers']['benchmark-selection.py']
            for record in amendment['preserved_choices']:
                old = c.execute('SELECT payload FROM research_review_selections WHERE study_id=%s AND pair=%s AND arm=%s',
                                (record['study'], record['pair'], record['arm'])).fetchone()
                assert old and digest(old['payload']) == record['payload_sha256']
            c.execute('INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                      (amendment['id'], Jsonb(amendment), digest(amendment)))
            assert c.execute('SELECT sha256 FROM research_review_studies WHERE id=%s',
                             (amendment['id'],)).fetchone()['sha256'] == digest(amendment)
            freeze = {'base_contract': original['protocol'], 'scheduling_amendment': amendment}
        else:
            c.execute('INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                      (args.corpus+'-contract', Jsonb(freeze), digest(freeze)))
            assert c.execute('SELECT sha256 FROM research_review_studies WHERE id=%s',
                             (args.corpus+'-contract',)).fetchone()['sha256'] == digest(freeze)
        node = c.execute('SELECT id FROM research_nodes WHERE campaign_id=%s', (m.CONTEXT,)).fetchone()
        assert not c.execute("SELECT 1 FROM jobs WHERE kind='RESEARCH_PLAN' AND state='RUNNING' AND lease_until>now()").fetchone()
        c.execute("UPDATE jobs SET state='SNAPSHOT_EXCLUDED' WHERE kind='RESEARCH_PLAN' AND state='READY' AND research_node_id!=%s", (node['id'],))
    if args.prepare_only:
        if not revalidation:
            raise SystemExit('Prepare-only is reserved for the named revalidation')
        print(json.dumps({'prepared': True, 'inputs_verified': len(inputs), 'freeze': freeze}), flush=True)
        d.close()
        return
    original = m.review_one if revalidation else m.recoverable_review

    def fresh_review(db, artifacts, campaign, frozen, row, p, arm, variant, seed, **kw):
        expected, _, _, _, _ = make_context(frozen['parent_spec'], frozen['parent_business'],
            row['basis']['offered'], row['basis']['memory'], count=kw.get('count', 1),
            feedback=arm=='feedback', selector_contract=p['selector_contract'], **row['basis']['variants'][variant])
        slot = None
        if revalidation:
            key = f"{row['pair']}:{arm}:{variant}:{seed}"
            assert digest(expected) == revalidation['input_hashes'][key]
            slot = fresh_slots.Slot('/operation/fresh-slots', {
                'corpus': args.corpus, 'campaign': campaign['id'], 'key': key,
                'context_sha256': digest(expected), 'profile': p,
            })
        while True:
            if slot:
                previous = slot.previous(lambda ids: db.rows(
                    'SELECT * FROM research_model_calls WHERE id=ANY(%s) ORDER BY id', (ids,)))
                if previous is not None:
                    return previous
            if admission:
                admission.wait(db, '/operation/admission.json', '/operation/admission-events.jsonl')
            else:
                last = db.rows("""SELECT created_at FROM research_model_calls WHERE campaign_id=%s
                    AND stage LIKE 'CANDIDATE_SELECTION_V4_%%' ORDER BY id DESC LIMIT 1""", (campaign['id'],))
                if last:
                    delay = REQUEST_INTERVAL_SECONDS-(now()-last[0]['created_at']).total_seconds()
                    if delay > 0:
                        time.sleep(min(delay, 30))
                        continue
            if revalidation:
                try:
                    snapshot = json.loads(Path('/operation/admission.json').read_text())
                except (OSError, ValueError):
                    snapshot = {}
                ready = (
                    0 <= time.time() - snapshot.get('observed_at', 0) <= 30
                    and snapshot.get('primary_running')
                    and not snapshot.get('primary_draw_paused', True)
                    and snapshot.get('primary_active_calls', 1) == 0
                    and snapshot.get('primary_next_call_headroom_seconds', 0) >= 900
                )
                if not ready:
                    time.sleep(10)
                    continue
            before = db.rows('SELECT coalesce(max(id),0) AS id FROM research_model_calls '
                             'WHERE campaign_id=%s', (campaign['id'],))[0]['id'] if slot else 0
            if slot:
                slot.begin(before)
            try:
                result = original(db, artifacts, campaign, frozen, row, p, arm, variant, seed, **kw)
            except (DomainError, RuntimeError) as exc:
                if not slot:
                    raise
                result = {'valid': False, 'correct': False, 'error': getattr(exc, 'code', type(exc).__name__),
                          'message': str(exc)[:400]}
            actual = db.rows("""SELECT * FROM research_model_calls WHERE campaign_id=%s
                AND stage=%s AND id>%s ORDER BY id DESC LIMIT 2""",
                (campaign['id'], 'CANDIDATE_SELECTION_V4_'+arm.upper(), before))
            if slot:
                assert len(actual) <= 1, 'Multiple native attempts require review, never select the latest'
            native = db.rows('SELECT * FROM research_model_calls WHERE attempt_id=%s ORDER BY id',
                             (actual[0]['attempt_id'],)) if actual else []
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
                if args.idle_admission:
                    result['scheduling_epoch'] = args.corpus+'-contract'
                if amendment:
                    result['scheduling_epoch'] = amendment['id']
                if slot:
                    slot.finish(result, 'PERFORMED', native)
                return result
            if slot:
                if not native and result.get('error', '').startswith('YIELD_'):
                    disposition = 'UNPERFORMED_ADMISSION_YIELD'
                elif fresh_slots.physical_void(native):
                    disposition = 'PHYSICAL_VOID'
                else:
                    disposition = 'REVIEW_REQUIRED'
                slot.finish(result, disposition, native)
                if disposition == 'REVIEW_REQUIRED':
                    raise RuntimeError('Unclassified or partly performed fresh slot preserved; no automatic retry')
            print(json.dumps({'physical_void': result, 'logical_choice_recorded': False}), flush=True)
            time.sleep(15)

    m.recoverable_review = fresh_review
    try:
        result = m.run_profile(d, a, header, config)
        measured = performance(d, result['study'], config)
        passed = bool(result['passed'] and measured['passed'])
        overlap, observed = [], None
        if revalidation:
            actual = d.rows("""SELECT m.id,m.created_at,m.metrics FROM research_review_selections s
                JOIN research_model_calls m ON m.id=(s.payload->'actual_call'->>'call_id')::bigint
                WHERE s.study_id=%s""", (result['study'],))
            end = max((r['created_at'].timestamp() + r['metrics'].get('wall_seconds', 0)
                       for r in actual), default=0)
            while True:
                try:
                    observed = json.loads(Path('/operation/primary-calls.json').read_text())
                except (OSError, ValueError):
                    observed = None
                if observed and observed['observed_at'] >= end:
                    break
                time.sleep(10)
            for primary in observed['calls']:
                for call in actual:
                    start = call['created_at'].timestamp()
                    if primary['start'] < start + call['metrics'].get('wall_seconds', 0) and primary['end'] > start:
                        overlap.append({'primary_call': primary['id'], 'acceptance_call': call['id']})
            passed = bool(passed and not overlap and observed['complete'])
        qualification = {'kind': 'SHORT_QWEN4_QUALIFICATION_V1', 'passed': passed,
                         'mechanism_study': result['study'], 'measurement': measured,
                         'mechanism_passed': result['passed'], 'profile_id': digest(config)}
        if revalidation:
            qualification['primary_overlaps'] = overlap
            qualification['primary_observations_complete'] = observed['complete']
        if amendment:
            qualification['scheduling_amendment'] = amendment['id']
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
