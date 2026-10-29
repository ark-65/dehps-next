CREATE TABLE official_publications (
 issue text PRIMARY KEY REFERENCES draws(issue),source_id text NOT NULL REFERENCES sources(id),
 first_verified_at timestamptz NOT NULL, provenance text NOT NULL
);
CREATE TRIGGER immutable_publication BEFORE UPDATE OR DELETE ON official_publications FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TABLE mail_reports (
 id text PRIMARY KEY,kind text NOT NULL,issue text NOT NULL,cycle_id text REFERENCES cycles(id),
 evidence text NOT NULL,payload jsonb NOT NULL,digest text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(kind,issue)
);
CREATE TRIGGER immutable_mail_report BEFORE UPDATE OR DELETE ON mail_reports FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TABLE mail_deliveries (
 id text PRIMARY KEY,report_id text NOT NULL REFERENCES mail_reports(id),recipient_hash text NOT NULL,
 state text NOT NULL DEFAULT 'READY',attempts integer NOT NULL DEFAULT 0,token text,lease_until timestamptz,
 not_before timestamptz NOT NULL DEFAULT now(),message_id text NOT NULL,last_error text,
 accepted_at timestamptz,created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(report_id,recipient_hash)
);
CREATE TABLE mail_attempts (
 id text PRIMARY KEY,delivery_id text NOT NULL REFERENCES mail_deliveries(id),state text NOT NULL,
 started_at timestamptz NOT NULL DEFAULT now(),ended_at timestamptz,code text
);
CREATE TABLE report_state (id integer PRIMARY KEY CHECK(id=1),payload jsonb NOT NULL);
CREATE TABLE program_release_adoptions(id bigserial PRIMARY KEY,program_id text NOT NULL,
 old_digest text NOT NULL,new_digest text NOT NULL,reason text NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE TRIGGER immutable_program_release BEFORE UPDATE OR DELETE ON program_release_adoptions FOR EACH ROW EXECUTE FUNCTION immutable_fact();

CREATE VIEW effective_draws AS SELECT d.issue,d.draw_at,least(d.available_at,coalesce(p.first_verified_at,d.available_at)) AS available_at,
 d.observed_at,d.red,d.blue,d.source_id,d.content_digest FROM draws d LEFT JOIN official_publications p ON p.issue=d.issue;
