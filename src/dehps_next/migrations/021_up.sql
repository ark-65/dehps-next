-- Retain the exact verdict priority and sequence order of continuation seeds.
CREATE INDEX IF NOT EXISTS memory_search_seeds ON research_memory_events
 (dataset_id,numeric_digest,((payload->>'verdict')='ACCEPT_IMPROVEMENT') DESC,seq DESC)
 WHERE kind='EVALUATION' AND payload->'business' IS NOT NULL
   AND payload->>'verdict' IN ('ACCEPT_IMPROVEMENT','INCONCLUSIVE');
