CREATE TABLE research_campaigns (
    id text PRIMARY KEY, config jsonb NOT NULL, dataset_id text NOT NULL REFERENCES datasets(id),
    protocol jsonb NOT NULL, status text NOT NULL DEFAULT 'READY', selected_node text,
    selected_anchor jsonb, created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE research_nodes (
    id text PRIMARY KEY, campaign_id text NOT NULL REFERENCES research_campaigns(id),
    path text NOT NULL, parent_id text REFERENCES research_nodes(id), spec jsonb NOT NULL,
    hypothesis jsonb NOT NULL, status text NOT NULL DEFAULT 'READY',
    evaluation jsonb, anchor jsonb, decision jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
    UNIQUE(campaign_id,path)
);
CREATE TABLE research_decisions (
    id bigserial PRIMARY KEY, campaign_id text NOT NULL REFERENCES research_campaigns(id),
    node_id text REFERENCES research_nodes(id), action text NOT NULL, evidence jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_research_decision BEFORE UPDATE OR DELETE ON research_decisions
    FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TABLE release_adoptions (
    id bigserial PRIMARY KEY, loop_id text NOT NULL REFERENCES loops(id), old_digest text NOT NULL,
    new_digest text NOT NULL, reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_release_adoption BEFORE UPDATE OR DELETE ON release_adoptions
    FOR EACH ROW EXECUTE FUNCTION immutable_fact();
ALTER TABLE jobs ALTER COLUMN cycle_id DROP NOT NULL;
ALTER TABLE jobs ADD COLUMN research_node_id text REFERENCES research_nodes(id);
ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN
    ('TRAIN','SEAL','EVALUATE','RESEARCH_EVALUATE','RESEARCH_PLAN'));
ALTER TABLE jobs ADD CONSTRAINT jobs_one_owner CHECK
    ((cycle_id IS NOT NULL)::int + (research_node_id IS NOT NULL)::int = 1);
CREATE UNIQUE INDEX research_job_identity ON jobs(research_node_id,kind) WHERE research_node_id IS NOT NULL;

