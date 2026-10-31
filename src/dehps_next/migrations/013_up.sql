CREATE TABLE research_review_studies (
 id text PRIMARY KEY,protocol jsonb NOT NULL,sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE research_review_pairs (
 study_id text NOT NULL REFERENCES research_review_studies(id),pair integer NOT NULL,
 basis jsonb NOT NULL,sha256 text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(study_id,pair)
);
CREATE TABLE research_review_selections (
 study_id text NOT NULL,pair integer NOT NULL,arm text NOT NULL,
 payload jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(study_id,pair,arm),FOREIGN KEY(study_id,pair) REFERENCES research_review_pairs(study_id,pair)
);
CREATE TABLE research_review_evaluations (
 study_id text NOT NULL REFERENCES research_review_studies(id),spec_digest text NOT NULL,
 node_id text NOT NULL,payload jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(study_id,spec_digest)
);
CREATE TABLE research_review_results (
 study_id text NOT NULL REFERENCES research_review_studies(id),payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(study_id)
);
CREATE TRIGGER immutable_review_protocol BEFORE UPDATE OR DELETE ON research_review_studies
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_review_pair BEFORE UPDATE OR DELETE ON research_review_pairs
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_review_selection BEFORE UPDATE OR DELETE ON research_review_selections
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_review_evaluation BEFORE UPDATE OR DELETE ON research_review_evaluations
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_review_result BEFORE UPDATE OR DELETE ON research_review_results
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
