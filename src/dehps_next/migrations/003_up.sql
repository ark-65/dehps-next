CREATE TABLE research_model_calls (
    id bigserial PRIMARY KEY, campaign_id text NOT NULL REFERENCES research_campaigns(id),
    job_id text NOT NULL REFERENCES jobs(id), attempt_id text NOT NULL REFERENCES attempts(id),
    stage text NOT NULL, model text NOT NULL, model_digest text NOT NULL,
    request jsonb NOT NULL, response jsonb, metrics jsonb,
    state text NOT NULL DEFAULT 'RESERVED', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE research_policy_versions (
    id bigserial PRIMARY KEY, campaign_id text NOT NULL REFERENCES research_campaigns(id),
    artifact jsonb NOT NULL, example_count integer NOT NULL, metrics jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_policy_version BEFORE UPDATE OR DELETE ON research_policy_versions
    FOR EACH ROW EXECUTE FUNCTION immutable_fact();
