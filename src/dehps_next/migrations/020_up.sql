CREATE TABLE ark_replay_snapshots (
 snapshot_id text PRIMARY KEY CHECK (snapshot_id ~ '^[0-9a-f]{64}$'),
 rules_version text NOT NULL,
 end_issue text NOT NULL REFERENCES draws(issue),
 z smallint NOT NULL CHECK (z = 500),
 as_of timestamptz NOT NULL,
 input_manifest jsonb NOT NULL CHECK (jsonb_array_length(input_manifest) = 1500),
 periods jsonb NOT NULL CHECK (jsonb_array_length(periods) = z),
 evidence text NOT NULL DEFAULT 'HISTORICAL_REPLAY' CHECK (evidence = 'HISTORICAL_REPLAY'),
 published_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ark_replay_latest ON ark_replay_snapshots (rules_version, end_issue DESC, published_at DESC);

CREATE TABLE ark_replay_red_periods (
 rules_version text NOT NULL,
 issue text NOT NULL REFERENCES draws(issue),
 input_digest text NOT NULL CHECK (input_digest ~ '^[0-9a-f]{64}$'),
 x smallint NOT NULL CHECK (x BETWEEN 50 AND 500),
 frequency_counts smallint[] NOT NULL CHECK (cardinality(frequency_counts) = 33),
 actual_frequency_ranks bytea NOT NULL CHECK (octet_length(actual_frequency_ranks) = 6),
 rank_count_checkpoints smallint[] NOT NULL CHECK (cardinality(rank_count_checkpoints) = 33 * (1 + (x-50)/25)),
 rank_increments bytea NOT NULL CHECK (octet_length(rank_increments) = 6 * (x-50)),
 red_masks bigint[] NOT NULL CHECK (cardinality(red_masks) = x-49),
 red_hits smallint[] NOT NULL CHECK (cardinality(red_hits) = x-49),
 actual_ark_positions bytea NOT NULL CHECK (octet_length(actual_ark_positions) = 6 * (x-49)),
 actual_cutoff_offsets bytea NOT NULL CHECK (octet_length(actual_cutoff_offsets) = 6 * (x-49)),
 PRIMARY KEY (rules_version, issue, input_digest, x)
);

CREATE TABLE ark_replay_blue_periods (
 rules_version text NOT NULL,
 issue text NOT NULL REFERENCES draws(issue),
 input_digest text NOT NULL CHECK (input_digest ~ '^[0-9a-f]{64}$'),
 x smallint NOT NULL CHECK (x BETWEEN 50 AND 500),
 frequency_counts smallint[] NOT NULL CHECK (cardinality(frequency_counts) = 16),
 actual_frequency_ranks bytea NOT NULL CHECK (octet_length(actual_frequency_ranks) = 1),
 rank_count_checkpoints smallint[] NOT NULL CHECK (cardinality(rank_count_checkpoints) = 16 * (1 + (x-50)/25)),
 rank_increments bytea NOT NULL CHECK (octet_length(rank_increments) = x-50),
 blue_numbers smallint[] NOT NULL CHECK (cardinality(blue_numbers) = x-49),
 blue_hits boolean[] NOT NULL CHECK (cardinality(blue_hits) = x-49),
 actual_ark_positions bytea NOT NULL CHECK (octet_length(actual_ark_positions) = x-49),
 actual_cutoff_offsets bytea NOT NULL CHECK (octet_length(actual_cutoff_offsets) = x-49),
 PRIMARY KEY (rules_version, issue, input_digest, x)
);

CREATE TABLE ark_replay_red_summary (
 snapshot_id text NOT NULL REFERENCES ark_replay_snapshots(snapshot_id),
 x smallint NOT NULL CHECK (x BETWEEN 50 AND 500),
 y smallint NOT NULL CHECK (y BETWEEN 50 AND x),
 red_hits integer NOT NULL CHECK (red_hits BETWEEN 0 AND 3000),
 red_hit_histogram integer[] NOT NULL CHECK (cardinality(red_hit_histogram) = 7),
 actual_position_histogram integer[] NOT NULL CHECK (cardinality(actual_position_histogram) = 33),
 cutoff_offset_histogram integer[] NOT NULL CHECK (cardinality(cutoff_offset_histogram) = 24),
 PRIMARY KEY (snapshot_id, x, y)
);
CREATE INDEX ark_replay_red_rank ON ark_replay_red_summary (snapshot_id, red_hits DESC, x, y);

CREATE TABLE ark_replay_blue_summary (
 snapshot_id text NOT NULL REFERENCES ark_replay_snapshots(snapshot_id),
 x smallint NOT NULL CHECK (x BETWEEN 50 AND 500),
 y smallint NOT NULL CHECK (y BETWEEN 50 AND x),
 blue_hits integer NOT NULL CHECK (blue_hits BETWEEN 0 AND 500),
 actual_position_histogram integer[] NOT NULL CHECK (cardinality(actual_position_histogram) = 16),
 cutoff_offset_histogram integer[] NOT NULL CHECK (cardinality(cutoff_offset_histogram) = 14),
 PRIMARY KEY (snapshot_id, x, y)
);
CREATE INDEX ark_replay_blue_rank ON ark_replay_blue_summary (snapshot_id, blue_hits DESC, x, y);

CREATE TRIGGER immutable_ark_replay_snapshots BEFORE UPDATE OR DELETE ON ark_replay_snapshots
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_ark_replay_red_periods BEFORE UPDATE OR DELETE ON ark_replay_red_periods
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_ark_replay_blue_periods BEFORE UPDATE OR DELETE ON ark_replay_blue_periods
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_ark_replay_red_summary BEFORE UPDATE OR DELETE ON ark_replay_red_summary
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
CREATE TRIGGER immutable_ark_replay_blue_summary BEFORE UPDATE OR DELETE ON ark_replay_blue_summary
 FOR EACH ROW EXECUTE FUNCTION immutable_fact();
