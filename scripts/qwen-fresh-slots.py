"""Durable fresh-slot receipts; unknown or partly performed attempts never resample."""

import json
import os
import time
from pathlib import Path

from dehps_next.domain import digest
from dehps_next.research_selection_evidence import SEMANTIC_FAILURES

PHYSICAL_FAILURES = {'LOCAL_INFERENCE_UNAVAILABLE', 'LOCAL_STREAM_INCOMPLETE', 'LOCAL_STREAM_STALLED'}


def physical_void(native):
    if not native:
        return False
    for call in native:
        metrics = call.get('metrics') or {}
        if call['state'] != 'FAILED' or metrics.get('failure_code') not in PHYSICAL_FAILURES:
            return False
        observations = [metrics]
        if isinstance(metrics.get('phase_progress'), dict):
            observations.append(metrics['phase_progress'])
        first = metrics.get('thinking_receipt', {}).get('metrics')
        if first:
            observations.append(first)
        # Absence of a counter is not an observed zero. Every native phase must
        # have an actual zero-stream receipt and no generated text or tokens.
        if not any(type(m.get('stream_bytes_observed')) is int and m['stream_bytes_observed'] == 0
                   for m in observations):
            return False
        for m in observations:
            if (m.get('raw_thinking') or m.get('raw_completion')
                or m.get('provider_error_code') in SEMANTIC_FAILURES
                or (m.get('eval_count') is not None and m['eval_count'] != 0)
                or (m.get('stream_bytes_observed') is not None and m['stream_bytes_observed'] != 0)):
                return False
    return True


def immutable(path, value):
    with path.open('x') as output:
        json.dump(value, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    sync_directory(path.parent)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Slot:
    def __init__(self, root, identity):
        self.root = Path(root) / digest(identity)
        self.root.mkdir(parents=True, exist_ok=True)
        sync_directory(self.root.parent)
        sync_directory(self.root.parent.parent)
        self.identity = identity
        self.attempt = 1

    def previous(self, native_lookup=None):
        while True:
            intent = self.root / f'{self.attempt}-started.json'
            outcome = self.root / f'{self.attempt}-outcome.json'
            if not intent.exists():
                assert not outcome.exists(), 'Outcome without its original intent requires review'
                return None
            assert json.loads(intent.read_text())['identity'] == self.identity
            if not outcome.exists():
                raise RuntimeError('Started fresh slot lacks a durable outcome; audit native records, never resample')
            saved = json.loads(outcome.read_text())
            assert saved['identity'] == self.identity
            assert digest(saved['payload']) == saved['payload_sha256']
            if native_lookup:
                native = native_lookup(saved['native_ids'])
                assert native_identity(native) == saved['native_sha256'], 'Native evidence changed; require review'
                if saved['disposition'] == 'PHYSICAL_VOID':
                    assert physical_void(native), 'A missing or changed receipt is never a physical void'
            if saved['disposition'] == 'PERFORMED':
                return saved['payload']
            if saved['disposition'] not in ('PHYSICAL_VOID', 'UNPERFORMED_ADMISSION_YIELD'):
                raise RuntimeError('Preserved unclassified fresh-slot failure requires review; never resample')
            self.attempt += 1

    def begin(self, before_native_id):
        immutable(self.root / f'{self.attempt}-started.json',
                  {'at': time.time(), 'identity': self.identity, 'before_native_id': before_native_id})

    def finish(self, payload, disposition, native):
        assert disposition in ('PERFORMED', 'PHYSICAL_VOID', 'UNPERFORMED_ADMISSION_YIELD', 'REVIEW_REQUIRED')
        if disposition == 'PHYSICAL_VOID':
            assert physical_void(native)
        if disposition == 'UNPERFORMED_ADMISSION_YIELD':
            assert not native and payload.get('error', '').startswith('YIELD_')
        immutable(self.root / f'{self.attempt}-outcome.json',
                  {'at': time.time(), 'identity': self.identity, 'disposition': disposition,
                   'native_ids': [r['id'] for r in native], 'native_sha256': native_identity(native),
                   'payload_sha256': digest(payload), 'payload': payload})


def native_identity(native):
    # Exclude mutable usage-accounting columns and driver datetime objects.
    return digest([{key: row.get(key) for key in
                    ('id', 'state', 'stage', 'model_digest', 'request', 'response', 'metrics')}
                   for row in native])
