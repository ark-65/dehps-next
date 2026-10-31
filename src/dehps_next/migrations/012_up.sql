CREATE TABLE research_soaks (
 id text PRIMARY KEY,started_at timestamptz NOT NULL DEFAULT now(),deadline timestamptz NOT NULL,
 next_sample timestamptz NOT NULL DEFAULT now(),interval_seconds integer NOT NULL,
 state text NOT NULL DEFAULT 'RUNNING',finished_at timestamptz,max_gap_seconds double precision NOT NULL DEFAULT 0
);
CREATE TABLE research_soak_samples (
 soak_id text NOT NULL REFERENCES research_soaks(id),sample_at timestamptz NOT NULL DEFAULT now(),
 payload jsonb NOT NULL,PRIMARY KEY(soak_id,sample_at)
);
CREATE TRIGGER immutable_soak_sample BEFORE UPDATE OR DELETE ON research_soak_samples
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
