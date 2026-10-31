-- Durable, exact memory is independent of optional research graph/artifact retention.
CREATE TABLE research_memory_events (
 seq bigserial PRIMARY KEY, event_key text NOT NULL UNIQUE, contract text NOT NULL,
 dataset_id text NOT NULL, numeric_digest text NOT NULL, protocol_digest text NOT NULL,
 numeric_threads integer NOT NULL, node_id text, parent_id text, spec jsonb,
 kind text NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX memory_contract_cursor ON research_memory_events(contract,seq);
CREATE INDEX memory_node ON research_memory_events(node_id);
CREATE INDEX memory_kind_cursor ON research_memory_events(contract,kind,seq DESC);
CREATE INDEX memory_improvements ON research_memory_events(contract,seq DESC)
 WHERE kind='EVALUATION' AND payload->>'verdict'='ACCEPT_IMPROVEMENT';
CREATE TRIGGER immutable_memory_event BEFORE UPDATE OR DELETE ON research_memory_events
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TABLE research_memory_snapshots (
 contract text NOT NULL, version bigint NOT NULL, cursor bigint NOT NULL,
 source_count bigint NOT NULL, payload jsonb NOT NULL, sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(contract,version)
);
CREATE TRIGGER immutable_memory_snapshot BEFORE UPDATE OR DELETE ON research_memory_snapshots
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TABLE research_memory_heads (
 contract text PRIMARY KEY, version bigint NOT NULL, cursor bigint NOT NULL,
 FOREIGN KEY(contract,version) REFERENCES research_memory_snapshots(contract,version)
);
CREATE TABLE research_search_batches (
 id bigserial PRIMARY KEY, dataset_id text NOT NULL, numeric_digest text NOT NULL,
 topic text NOT NULL, generation bigint NOT NULL, candidates jsonb NOT NULL,
 basis jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(dataset_id,numeric_digest,topic,generation)
);
CREATE TRIGGER immutable_search_batch BEFORE UPDATE OR DELETE ON research_search_batches
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TABLE research_recoveries (
 old_job_id text PRIMARY KEY, new_campaign_id text NOT NULL, new_node_id text NOT NULL,
 evidence jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_recovery BEFORE UPDATE OR DELETE ON research_recoveries
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
