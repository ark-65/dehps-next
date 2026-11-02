CREATE TABLE retained_parent_versions (
 id text PRIMARY KEY, program_id text NOT NULL, previous_version text,
 snapshot jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE retained_parent_heads (
 program_id text PRIMARY KEY, version_id text NOT NULL REFERENCES retained_parent_versions(id),
 previous_version text REFERENCES retained_parent_versions(id), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE parent_fallback_seals (
 issue text PRIMARY KEY, version_id text NOT NULL REFERENCES retained_parent_versions(id),
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE parent_fallback_settlements (
 issue text PRIMARY KEY REFERENCES parent_fallback_seals(issue), payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE report_model_evidence (
 report_id text PRIMARY KEY REFERENCES mail_reports(id), payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_parent_version BEFORE UPDATE OR DELETE ON retained_parent_versions
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_parent_seal BEFORE UPDATE OR DELETE ON parent_fallback_seals
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_parent_settlement BEFORE UPDATE OR DELETE ON parent_fallback_settlements
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_report_model_evidence BEFORE UPDATE OR DELETE ON report_model_evidence
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
