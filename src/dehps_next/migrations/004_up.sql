CREATE TABLE research_programs (
 id text PRIMARY KEY, config jsonb NOT NULL, state text NOT NULL DEFAULT 'READY',
 generation integer NOT NULL DEFAULT 0, current_campaign text, next_due timestamptz NOT NULL DEFAULT now(),
 completed jsonb NOT NULL DEFAULT '[]', last_dataset text, champion_spec jsonb,
 launch_day date, launched_today integer NOT NULL DEFAULT 0,
 last_reason text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE research_campaigns ADD COLUMN program_id text REFERENCES research_programs(id);
ALTER TABLE research_campaigns ADD COLUMN topic text;
ALTER TABLE research_campaigns ADD COLUMN identity text;
CREATE UNIQUE INDEX program_topic_identity ON research_campaigns(program_id,identity) WHERE program_id IS NOT NULL;
CREATE TABLE artifact_catalog (
 path text PRIMARY KEY, ref jsonb NOT NULL, category text NOT NULL,
 state text NOT NULL DEFAULT 'LIVE', created_at timestamptz NOT NULL DEFAULT now(),
 writer_until timestamptz NOT NULL DEFAULT now()+interval '5 minutes',
 candidate_at timestamptz, deleted_at timestamptz, reason text,
 pin_until timestamptz
);
CREATE TABLE gc_receipts (
 id bigserial PRIMARY KEY, path text NOT NULL, sha256 text NOT NULL, bytes bigint NOT NULL,
 action text NOT NULL, reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE research_rollups (
 topic text PRIMARY KEY, campaigns bigint NOT NULL DEFAULT 0, nodes bigint NOT NULL DEFAULT 0,
 decisions bigint NOT NULL DEFAULT 0, failures bigint NOT NULL DEFAULT 0,
 retired_bytes bigint NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE source_batches (id text PRIMARY KEY, source_id text NOT NULL REFERENCES sources(id));
CREATE TABLE research_score_cache (
 id text PRIMARY KEY, artifact jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE resource_days (
 day date PRIMARY KEY, spent double precision NOT NULL DEFAULT 0,
 reserved double precision NOT NULL DEFAULT 0, calls integer NOT NULL DEFAULT 0
);
CREATE TABLE resource_reservations (
 token text PRIMARY KEY, job_id text NOT NULL, day date NOT NULL,
 lane text NOT NULL, cpu_cap double precision NOT NULL, wall_cap double precision NOT NULL,
 cpu_reserved double precision NOT NULL, write_reserved bigint NOT NULL,
 written bigint NOT NULL DEFAULT 0, wall_seconds double precision, process_cpu_seconds double precision,
 charged double precision, state text NOT NULL DEFAULT 'ACTIVE',
 created_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz
);
CREATE TABLE resource_state (id integer PRIMARY KEY CHECK(id=1), payload jsonb NOT NULL);
CREATE TABLE resource_policy (id integer PRIMARY KEY CHECK(id=1),capacity double precision NOT NULL,calls integer NOT NULL);
INSERT INTO resource_policy VALUES(1,7200,24);
CREATE TABLE resource_policy_changes(id bigserial PRIMARY KEY,policy jsonb NOT NULL,reason text NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE maintenance_state (id integer PRIMARY KEY CHECK(id=1), payload jsonb NOT NULL);
CREATE TABLE resource_totals (id integer PRIMARY KEY CHECK(id=1), charged double precision NOT NULL DEFAULT 0,
 calls bigint NOT NULL DEFAULT 0, deleted_artifact_bytes bigint NOT NULL DEFAULT 0);
INSERT INTO resource_totals(id) VALUES(1);
ALTER TABLE jobs ADD COLUMN failures integer NOT NULL DEFAULT 0;
UPDATE jobs SET failures=(SELECT count(*) FROM attempts a WHERE a.job_id=jobs.id AND a.state IN ('FAILED','LOST'));

-- Only obsolete research detail may be retired by the lifecycle transaction.
-- Core facts remain immutable even in maintenance mode.
CREATE OR REPLACE FUNCTION immutable_fact() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('research_decisions','research_policy_versions')
    AND current_setting('dehps_next.retirement',true)='on' THEN RETURN OLD; END IF;
 RAISE EXCEPTION 'immutable fact: %', TG_TABLE_NAME;
END $$;
