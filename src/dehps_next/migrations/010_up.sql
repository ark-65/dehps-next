-- Owner2026-10-30: stop training at17:00 and send as soon as finalization finishes.
-- Existing forecasts/reports stay immutable. The default clock has no config/environment override.
CREATE FUNCTION report_policy_clock() RETURNS timestamptz LANGUAGE sql VOLATILE AS $$
 SELECT clock_timestamp()
$$;
CREATE OR REPLACE FUNCTION guard_final_selection() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE wall timestamptz := report_policy_clock();
BEGIN
 IF EXISTS(SELECT 1 FROM forecast_selections s WHERE s.issue=NEW.issue
   AND NOT EXISTS(SELECT 1 FROM forecast_schedule_reopenings r WHERE r.issue=s.issue)) THEN
   RAISE EXCEPTION 'existing final forecast decision cannot be superseded';
 END IF;
 IF NEW.state='MISSED' AND NOT EXISTS(
   SELECT 1 FROM targets t WHERE t.issue=NEW.issue
     AND wall>=(((t.draw_at AT TIME ZONE 'Asia/Shanghai')::date+time '17:00') AT TIME ZONE 'Asia/Shanghai')
 ) THEN
   RAISE EXCEPTION 'cannot mark an issue missing before its registered17:00 finalization';
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION validated_seal_window() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE wall timestamptz := report_policy_clock();
BEGIN
 IF EXISTS(SELECT 1 FROM cycles WHERE id=NEW.cycle_id AND loop_id='mail-validated-forward') THEN
  IF (wall AT TIME ZONE 'Asia/Shanghai')::time < time '17:00'
     OR NOT EXISTS(SELECT 1 FROM targets t WHERE t.issue=NEW.issue
       AND (t.draw_at AT TIME ZONE 'Asia/Shanghai')::date=(wall AT TIME ZONE 'Asia/Shanghai')::date
       AND wall<t.deadline AND NEW.sealed_at<t.deadline)
     OR EXISTS(SELECT 1 FROM draws WHERE issue=NEW.issue)
     OR (NEW.sealed_at AT TIME ZONE 'Asia/Shanghai')::date != (wall AT TIME ZONE 'Asia/Shanghai')::date
     OR (NEW.sealed_at AT TIME ZONE 'Asia/Shanghai')::time < time '17:00'
     OR NEW.sealed_at>wall+interval '5 seconds'
     OR EXISTS(SELECT 1 FROM jobs WHERE state='RUNNING' AND lease_until>clock_timestamp()
                AND kind IN ('TRAIN','RESEARCH_EVALUATE','RESEARCH_PLAN')) THEN
    RAISE EXCEPTION 'validated forecast requires17:00 pause/finalization within registered deadline';
  END IF;
 END IF;
 RETURN NEW;
END $$;
