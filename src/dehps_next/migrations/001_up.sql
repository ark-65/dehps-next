CREATE TABLE sources (
    id text PRIMARY KEY, url text NOT NULL, observed_at timestamptz NOT NULL,
    artifact jsonb NOT NULL, provenance text NOT NULL
);
CREATE TABLE draws (
    issue text PRIMARY KEY CHECK (issue ~ '^[0-9]{7}$'),
    draw_at timestamptz NOT NULL UNIQUE, available_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL, red integer[] NOT NULL, blue integer NOT NULL,
    source_id text NOT NULL REFERENCES sources(id), content_digest text NOT NULL,
    CHECK (cardinality(red)=6), CHECK(blue BETWEEN 1 AND 16), CHECK(available_at>=draw_at)
);
CREATE TABLE loops (
    id text PRIMARY KEY, mode text NOT NULL CHECK(mode IN ('REPLAY','FORWARD')),
    config jsonb NOT NULL, state text NOT NULL DEFAULT 'READY',
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE targets (
    issue text PRIMARY KEY, draw_at timestamptz NOT NULL, deadline timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), CHECK(deadline<draw_at)
);
CREATE TABLE datasets (
    id text PRIMARY KEY, through_issue text NOT NULL, cutoff timestamptz NOT NULL,
    mode text NOT NULL, sample_count integer NOT NULL, artifact jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE cycles (
    id text PRIMARY KEY, loop_id text NOT NULL REFERENCES loops(id), issue text NOT NULL,
    purpose text NOT NULL DEFAULT 'PREDICT' CHECK(purpose IN ('PREDICT','REFIT')),
    draw_at timestamptz NOT NULL, cutoff timestamptz NOT NULL,
    dataset_id text NOT NULL REFERENCES datasets(id), parent_model_id text,
    state text NOT NULL DEFAULT 'TRAIN', model_id text,
    created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(loop_id,issue,purpose)
);
CREATE TABLE jobs (
    id text PRIMARY KEY, cycle_id text NOT NULL REFERENCES cycles(id),
    kind text NOT NULL CHECK(kind IN ('TRAIN','SEAL','EVALUATE')),
    state text NOT NULL DEFAULT 'READY', attempts integer NOT NULL DEFAULT 0,
    token text, lease_until timestamptz, not_before timestamptz NOT NULL DEFAULT now(),
    checkpoint jsonb, error_code text, created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(cycle_id,kind)
);
CREATE INDEX jobs_ready ON jobs(state,not_before,created_at);
CREATE TABLE attempts (
    id text PRIMARY KEY, job_id text NOT NULL REFERENCES jobs(id), state text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
    error_code text, worker text NOT NULL
);
CREATE TABLE models (
    id text PRIMARY KEY, cycle_id text NOT NULL UNIQUE REFERENCES cycles(id),
    parent_id text REFERENCES models(id), dataset_id text NOT NULL REFERENCES datasets(id),
    artifact jsonb NOT NULL, manifest jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE consumptions (
    model_id text NOT NULL REFERENCES models(id), issue text NOT NULL REFERENCES draws(issue),
    uses integer NOT NULL CHECK(uses>0), newly_consumed boolean NOT NULL,
    PRIMARY KEY(model_id,issue)
);
CREATE TABLE predictions (
    cycle_id text PRIMARY KEY REFERENCES cycles(id), model_id text NOT NULL REFERENCES models(id),
    issue text NOT NULL, mode text NOT NULL, cutoff timestamptz NOT NULL,
    sealed_at timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL, payload_digest text NOT NULL,
    baseline jsonb NOT NULL
);
CREATE TABLE evaluations (
    cycle_id text PRIMARY KEY REFERENCES predictions(cycle_id), issue text NOT NULL REFERENCES draws(issue),
    mode text NOT NULL, metrics jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE worker_status (
    id text PRIMARY KEY, heartbeat_at timestamptz NOT NULL DEFAULT now(), state text NOT NULL,
    current_job text, error_code text
);
CREATE FUNCTION immutable_fact() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable fact: %', TG_TABLE_NAME; END $$;
DO $$ DECLARE t text; BEGIN
    FOREACH t IN ARRAY ARRAY['sources','draws','targets','datasets','models','consumptions','predictions','evaluations']
    LOOP EXECUTE format('CREATE TRIGGER immutable_row BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION immutable_fact()', t);
    END LOOP;
END $$;
