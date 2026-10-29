ALTER TABLE research_model_calls ADD COLUMN usage_recorded boolean NOT NULL DEFAULT false;
ALTER TABLE research_model_calls ADD COLUMN usage_input_tokens bigint;
ALTER TABLE research_model_calls ADD COLUMN usage_output_tokens bigint;
CREATE TABLE local_token_days (
 day date NOT NULL,model text NOT NULL,input_tokens bigint NOT NULL DEFAULT 0,
 output_tokens bigint NOT NULL DEFAULT 0,unreported_calls bigint NOT NULL DEFAULT 0,PRIMARY KEY(day,model)
);
CREATE TABLE local_token_totals (
 model text PRIMARY KEY,input_tokens bigint NOT NULL DEFAULT 0,output_tokens bigint NOT NULL DEFAULT 0,
 unreported_calls bigint NOT NULL DEFAULT 0
);
CREATE TABLE local_token_imports (
 id text PRIMARY KEY,model text NOT NULL,input_tokens bigint,output_tokens bigint,source jsonb NOT NULL,
 observed_at timestamptz NOT NULL,imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_token_import BEFORE UPDATE OR DELETE ON local_token_imports FOR EACH ROW EXECUTE FUNCTION immutable_fact();
UPDATE research_model_calls SET
 usage_input_tokens=CASE WHEN metrics->>'prompt_eval_count' ~ '^[0-9]+$' THEN (metrics->>'prompt_eval_count')::bigint END,
 usage_output_tokens=CASE WHEN metrics->>'eval_count' ~ '^[0-9]+$' THEN (metrics->>'eval_count')::bigint END,
 usage_recorded=true WHERE state IN ('SUCCEEDED','FAILED','UNKNOWN');
INSERT INTO local_token_days(day,model,input_tokens,output_tokens,unreported_calls)
 SELECT (created_at AT TIME ZONE 'Asia/Shanghai')::date,model,coalesce(sum(usage_input_tokens),0),coalesce(sum(usage_output_tokens),0),
 count(*) FILTER(WHERE usage_input_tokens IS NULL OR usage_output_tokens IS NULL)
 FROM research_model_calls WHERE usage_recorded GROUP BY 1,2;
INSERT INTO local_token_totals(model,input_tokens,output_tokens,unreported_calls)
 SELECT model,sum(input_tokens),sum(output_tokens),sum(unreported_calls) FROM local_token_days GROUP BY model;

ALTER TABLE resource_policy ALTER COLUMN capacity DROP NOT NULL;
ALTER TABLE resource_policy ALTER COLUMN calls DROP NOT NULL;
ALTER TABLE resource_policy ADD COLUMN accounting_mode text NOT NULL DEFAULT 'OBSERVE_ONLY_TOKENS';
INSERT INTO resource_policy_changes(policy,reason) SELECT jsonb_build_object('operation','RETIRE_LOCAL_USAGE_QUOTAS','previous_policy',to_jsonb(resource_policy),'new_mode','OBSERVE_ONLY_TOKENS'),'Owner removed local consumption/call quotas; CPU memory storage safeguards retained, token statistics only' FROM resource_policy;
UPDATE resource_policy SET capacity=NULL,calls=NULL,accounting_mode='OBSERVE_ONLY_TOKENS';
