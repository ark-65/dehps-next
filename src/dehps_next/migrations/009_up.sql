-- Owner correction:17:00 starts preparation;19:00 is the final mail time.
-- Prior immutable mail/selection facts remain intact, including the early MISSED decision.
CREATE TABLE forecast_schedule_reopenings (
 issue text PRIMARY KEY REFERENCES forecast_selections(issue),
 previous_report text NOT NULL REFERENCES mail_reports(id),
 policy text NOT NULL,reason text NOT NULL,created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_schedule_reopening BEFORE UPDATE OR DELETE ON forecast_schedule_reopenings
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE FUNCTION guard_schedule_reopening() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.policy!='evening-preparation-v3' OR NOT EXISTS(
   SELECT 1 FROM forecast_selections s JOIN targets t ON t.issue=s.issue
   JOIN mail_reports r ON r.id=NEW.previous_report AND r.issue=s.issue
   WHERE s.issue=NEW.issue AND s.state='MISSED' AND s.cycle_id IS NULL
     AND s.evidence->>'reason'='NO_VALIDATED_FORECAST_AT_17'
     AND r.kind='PRE' AND r.evidence='STATUS' AND r.cycle_id IS NULL
     AND (t.draw_at AT TIME ZONE 'Asia/Shanghai')::date=(clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date
     AND clock_timestamp()<t.deadline
     AND (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::time<time '19:00'
 ) OR EXISTS(SELECT 1 FROM draws WHERE issue=NEW.issue) THEN
   RAISE EXCEPTION 'only an unresolved early17:00 missing decision may reopen before the new final cutoff';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER enforce_schedule_reopening BEFORE INSERT ON forecast_schedule_reopenings
 FOR EACH ROW EXECUTE FUNCTION guard_schedule_reopening();
INSERT INTO forecast_schedule_reopenings(issue,previous_report,policy,reason)
 SELECT s.issue,r.id,'evening-preparation-v3',
 'Owner correction2026-10-29:17:00 starts preparation; old status retained; final decision at19:00'
 FROM forecast_selections s JOIN targets t ON t.issue=s.issue
 JOIN mail_reports r ON r.issue=s.issue AND r.kind='PRE' AND r.evidence='STATUS' AND r.cycle_id IS NULL
 WHERE s.state='MISSED' AND s.cycle_id IS NULL AND s.evidence->>'reason'='NO_VALIDATED_FORECAST_AT_17'
 AND (t.draw_at AT TIME ZONE 'Asia/Shanghai')::date=(clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date
 AND clock_timestamp()<t.deadline
 AND (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::time<time '19:00'
 AND NOT EXISTS(SELECT 1 FROM draws d WHERE d.issue=s.issue);

CREATE TABLE forecast_final_selections (
 issue text PRIMARY KEY,cycle_id text UNIQUE REFERENCES cycles(id),
 state text NOT NULL CHECK(state IN ('MISSED','SEALED_VALIDATED_DEVELOPMENT')),
 evidence jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 CHECK((state='MISSED')=(cycle_id IS NULL))
);
CREATE TRIGGER immutable_final_selection BEFORE UPDATE OR DELETE ON forecast_final_selections
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE FUNCTION guard_final_selection() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM forecast_selections s WHERE s.issue=NEW.issue
   AND NOT EXISTS(SELECT 1 FROM forecast_schedule_reopenings r WHERE r.issue=s.issue)) THEN
   RAISE EXCEPTION 'existing final forecast decision cannot be superseded';
 END IF;
 IF NEW.state='MISSED' AND (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::time<time '19:00' THEN
   RAISE EXCEPTION 'preparation cannot mark an issue missing before19:00';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER enforce_final_selection BEFORE INSERT ON forecast_final_selections
 FOR EACH ROW EXECUTE FUNCTION guard_final_selection();
CREATE VIEW effective_forecast_selections AS
 SELECT * FROM forecast_final_selections
 UNION ALL
 SELECT s.* FROM forecast_selections s
 WHERE NOT EXISTS(SELECT 1 FROM forecast_final_selections f WHERE f.issue=s.issue)
 AND NOT EXISTS(SELECT 1 FROM forecast_schedule_reopenings r WHERE r.issue=s.issue);

CREATE OR REPLACE FUNCTION validated_seal_window() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM cycles WHERE id=NEW.cycle_id AND loop_id='mail-validated-forward') THEN
  IF (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::time < time '18:50'
     OR (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::time >= time '19:00'
     OR NOT EXISTS(SELECT 1 FROM targets t WHERE t.issue=NEW.issue
       AND (t.draw_at AT TIME ZONE 'Asia/Shanghai')::date=(clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date
       AND clock_timestamp()<t.deadline)
     OR EXISTS(SELECT 1 FROM draws WHERE issue=NEW.issue)
     OR (NEW.sealed_at AT TIME ZONE 'Asia/Shanghai')::date != (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date
     OR (NEW.sealed_at AT TIME ZONE 'Asia/Shanghai')::time < time '18:50'
     OR (NEW.sealed_at AT TIME ZONE 'Asia/Shanghai')::time >= time '19:00' THEN
    RAISE EXCEPTION 'validated forecast outside registered18:50-19:00 seal window';
  END IF;
 END IF;
 RETURN NEW;
END $$;
