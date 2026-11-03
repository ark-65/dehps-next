CREATE TABLE probability_rules (
 id text PRIMARY KEY, program_id text NOT NULL, contract jsonb NOT NULL,
 sha256 text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE probability_forecasts (
 rule_id text NOT NULL REFERENCES probability_rules(id), issue text NOT NULL,
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(rule_id,issue)
);
CREATE TABLE probability_settlements (
 rule_id text NOT NULL, issue text NOT NULL, payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(rule_id,issue),
 FOREIGN KEY(rule_id,issue) REFERENCES probability_forecasts(rule_id,issue)
);
CREATE TRIGGER immutable_probability_rule BEFORE UPDATE OR DELETE ON probability_rules
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_probability_forecast BEFORE UPDATE OR DELETE ON probability_forecasts
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_probability_settlement BEFORE UPDATE OR DELETE ON probability_settlements
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
