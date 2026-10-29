-- Append-only transition: old early acceptance forecasts remain truthful immutable records.
CREATE TABLE forecast_selections (
 issue text PRIMARY KEY, cycle_id text UNIQUE REFERENCES cycles(id),
 state text NOT NULL, evidence jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_forecast_selection BEFORE UPDATE OR DELETE ON forecast_selections
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TABLE forecast_exclusions (
 cycle_id text PRIMARY KEY REFERENCES predictions(cycle_id), reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_forecast_exclusion BEFORE UPDATE OR DELETE ON forecast_exclusions
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
INSERT INTO forecast_exclusions(cycle_id,reason)
 SELECT p.cycle_id,'Early acceptance forecast: retained as historical evidence; superseded for official 17:00 reporting by owner policy 2026-10-29'
 FROM predictions p JOIN cycles cy ON cy.id=p.cycle_id WHERE cy.loop_id='mail-forward';
CREATE FUNCTION validated_seal_window() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM cycles WHERE id=NEW.cycle_id AND loop_id='mail-validated-forward') THEN
  IF (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::time < time '16:59'
     OR (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::time >= time '17:00'
     OR NOT EXISTS(SELECT 1 FROM targets t WHERE t.issue=NEW.issue
       AND (t.draw_at AT TIME ZONE 'Asia/Shanghai')::date=(clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date
       AND clock_timestamp()<t.deadline)
     OR EXISTS(SELECT 1 FROM draws WHERE issue=NEW.issue)
     OR (NEW.sealed_at AT TIME ZONE 'Asia/Shanghai')::date != (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date
     OR (NEW.sealed_at AT TIME ZONE 'Asia/Shanghai')::time < time '16:59'
     OR (NEW.sealed_at AT TIME ZONE 'Asia/Shanghai')::time >= time '17:00' THEN
    RAISE EXCEPTION 'validated forecast outside registered 16:59-17:00 seal window';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER enforce_validated_seal BEFORE INSERT ON predictions FOR EACH ROW EXECUTE FUNCTION validated_seal_window();
