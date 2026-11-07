-- Keep oldest-undelivered batch lookup independent of unrelated training-memory volume.
CREATE INDEX memory_qwen_feedback ON research_memory_events
 (contract, (payload->'review_evidence'->>'profile_id'), seq)
 WHERE kind='EVALUATION' AND parent_id IS NOT NULL
 AND payload->'review_evidence'->>'selection_source'='QWEN_COMPARATIVE';
