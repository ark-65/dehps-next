"""Replay actual immutable outputs in isolated Next; no generation or activation."""

import hashlib
import importlib.util
import json
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest
from dehps_next.release import code_identity, numeric_identity
from dehps_next.research_output_guard import VERSION, identity, repetition


def first_trigger(text, check):
    return next((i for i in range(1, len(text) + 1) if check(text[:i])), None)


def main():
    operation = Path('/operation')
    source = json.loads((operation / 'symbol-guard-source.json').read_text())
    frozen = json.loads((operation / 'symbol-guard-freeze.json').read_text())
    assert digest(source) == frozen['source_sha256']
    assert VERSION == 'short-output-loop-guard-v2'
    settings = Settings.from_env()
    assert conninfo_to_dict(settings.database_url)['dbname'] == 'dehps_next_qwen_latency_20261113'
    assert settings.runtime.name == 'qwen-latency-case'
    root = Path(__import__('dehps_next').__file__).parent
    assert hashlib.sha256((root / 'research_output_guard.py').read_bytes()).hexdigest() == frozen['guard_sha256']
    prior_path = operation / 'symbol-guard-original-v1.py'
    assert hashlib.sha256(prior_path.read_bytes()).hexdigest() == frozen['prior_guard_sha256']
    spec = importlib.util.spec_from_file_location('dehps_next.original_guard', prior_path)
    prior = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prior)
    assert prior.VERSION == 'short-output-loop-guard-v1'
    assert source['accepted_result']['passed'] and len(source['accepted_slots']) == 144
    assert source['accepted_profile_id'] == source['accepted_result']['profile_id']
    rejected, negative = [], []
    for row in source['accepted_slots']:
        assert digest(row['payload']) == row['payload_sha256']
        payload = row['payload']
        if not payload['valid']:
            continue
        metrics = payload['actual_call']['metrics']
        for phase, text in [('thinking', metrics['thinking_receipt']['metrics']['raw_thinking']),
                            ('answer', metrics['raw_completion'])]:
            at = first_trigger(text, repetition)
            if at:
                rejected.append({'pair': row['pair'], 'arm': row['arm'], 'phase': phase,
                                 'trigger_character': at})
    for row in source['negative_calls']:
        assert digest(row['native']) == row['native_sha256']
        native = row['native']
        assert native['state'] == 'FAILED' and native['stage'] == 'SHORT_THINKING_PREFIX'
        metrics = native['metrics']
        assert metrics['failure_code'] == 'LOCAL_INFERENCE_UNAVAILABLE'
        text = metrics['raw_completion']
        at = first_trigger(text, repetition)
        previous = first_trigger(text, prior.repetition)
        negative.append({'call_id': native['id'], 'original_failure_code_preserved': metrics['failure_code'],
                         'original_guard_trigger': previous, 'new_guard_trigger_character': at,
                         'new_guard_evidence': repetition(text[:at]) if at else None,
                         'retained_characters': len(text), 'retained_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                         'provider_counts_missing': metrics.get('prompt_eval_count') is None or metrics.get('eval_count') is None})
    passed = not rejected and len(negative) == 2 and all(
        r['original_guard_trigger'] is None and r['new_guard_trigger_character'] for r in negative)
    protocol = {'kind': 'QWEN_SYMBOL_GUARD_RECORDED_OUTPUT_ACCEPTANCE_V1',
                'source_export_sha256': digest(source), 'accepted_study': source['accepted_study'],
                'accepted_profile_id': source['accepted_profile_id'], 'guard_identity': identity(),
                'guard_version': VERSION, 'freeze_sha256': digest(frozen), 'source': code_identity(),
                'numeric': numeric_identity(), 'scope': 'ACTUAL_IMMUTABLE_OUTPUT_REPLAY;ZERO_GENERATION;NO_ACTIVATION'}
    result = {'passed': passed, 'protocol_sha256': digest(protocol), 'source_slots': 144,
              'source_valid_slots': sum(bool(r['payload']['valid']) for r in source['accepted_slots']),
              'source_invalid_slots_preserved': sum(not r['payload']['valid'] for r in source['accepted_slots']),
              'previous_valid_rejected': len(rejected), 'rejections': rejected, 'negative_calls': negative,
              'model_requests': 0, 'latency_qualification_credit': False,
              'production_source_changed': False, 'production_recovery_certificate': False}
    db = Database(settings)
    try:
        with db.pool.connection() as connection, connection.transaction():
            connection.execute('INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) '
                               'ON CONFLICT DO NOTHING', (frozen['study'], Jsonb(protocol), digest(protocol)))
            assert connection.execute('SELECT sha256 FROM research_review_studies WHERE id=%s',
                                      (frozen['study'],)).fetchone()['sha256'] == digest(protocol)
            connection.execute('INSERT INTO research_review_results(study_id,payload) VALUES(%s,%s) '
                               'ON CONFLICT DO NOTHING', (frozen['study'], Jsonb(result)))
            assert connection.execute('SELECT payload FROM research_review_results WHERE study_id=%s',
                                      (frozen['study'],)).fetchone()['payload'] == result
        receipt = operation / 'symbol-guard-acceptance.json'
        with receipt.open('x') as output:
            json.dump({'protocol': protocol, 'result': result}, output, indent=2)
        print(json.dumps(result), flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    main()
