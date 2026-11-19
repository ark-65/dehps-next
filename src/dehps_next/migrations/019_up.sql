CREATE TABLE dlt_draws (
    issue text PRIMARY KEY,
    draw_date date NOT NULL UNIQUE,
    front smallint[] NOT NULL,
    back smallint[] NOT NULL,
    source_url text NOT NULL,
    observed_at timestamptz NOT NULL,
    CHECK (issue ~ '^[0-9]{5}$' AND left(issue, 2) = to_char(draw_date, 'YY') AND right(issue, 3) <> '000'),
    CHECK ((array_dims(front) = '[1:5]' AND front[1] >= 1 AND front[1] < front[2]
        AND front[2] < front[3] AND front[3] < front[4] AND front[4] < front[5] AND front[5] <= 35) IS TRUE),
    CHECK ((array_dims(back) = '[1:2]' AND back[1] >= 1 AND back[1] < back[2] AND back[2] <= 12) IS TRUE),
    CHECK (draw_date <= (observed_at AT TIME ZONE 'Asia/Shanghai')::date)
);

CREATE TRIGGER immutable_dlt_draw BEFORE UPDATE OR DELETE ON dlt_draws
    FOR EACH ROW EXECUTE FUNCTION immutable_fact();
