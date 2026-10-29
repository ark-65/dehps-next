CREATE TABLE numeric_releases (
 release_digest text PRIMARY KEY,numeric_digest text NOT NULL,reason text NOT NULL,
 reviewed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_numeric_release BEFORE UPDATE OR DELETE ON numeric_releases FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TABLE research_recipe_memory (
 dataset_id text NOT NULL REFERENCES datasets(id),numeric_digest text NOT NULL,spec_digest text NOT NULL,
 spec jsonb NOT NULL,verdict text,summary jsonb,last_seen_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(dataset_id,numeric_digest,spec_digest)
);
CREATE INDEX recipe_memory_recent ON research_recipe_memory(last_seen_at DESC);
