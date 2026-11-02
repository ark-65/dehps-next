CREATE TABLE qwen_selection_profiles (
 id text PRIMARY KEY, config jsonb NOT NULL, mechanism_study text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE qwen_selection_state (
 id integer PRIMARY KEY CHECK(id=1), profile_id text REFERENCES qwen_selection_profiles(id),
 reason text, retry_after timestamptz, updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO qwen_selection_state(id,reason) VALUES(1,'MECHANISM_NOT_VALIDATED');
CREATE TABLE qwen_selection_audits (
 id bigserial PRIMARY KEY, campaign_id text NOT NULL, call_id bigint, source text NOT NULL,
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX qwen_audit_recent ON qwen_selection_audits(created_at DESC);
CREATE TRIGGER immutable_qwen_profile BEFORE UPDATE OR DELETE ON qwen_selection_profiles
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_qwen_audit BEFORE UPDATE OR DELETE ON qwen_selection_audits
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
