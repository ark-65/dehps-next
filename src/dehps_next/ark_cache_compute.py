"""Batched ARK ranks and rolling summaries for the fixed replay grid."""

import numpy as np

X_MIN = 50
X_MAX = 500
PERIODS = 500
CHECKPOINT = 25
X_VALUES = range(X_MIN, X_MAX + 1)
COMBINATIONS = sum(x - X_MIN + 1 for x in X_VALUES)
HISTORY = 2 * X_MAX + PERIODS
GRID = [(x, y) for x in X_VALUES for y in range(X_MIN, x + 1)]
RULES = "ark-replay-v1"
SIZES = {"red": 33, "blue": 16}
WIDTHS = {"red": 6, "blue": 1}
CUTOFFS = {"red": 10, "blue": 3}
TAKE = {"red": 10, "blue": 1}


class ReplayGrid:
    def __init__(self, rows):
        self.indices = {
            "red": np.array([sorted(row["red"]) for row in rows], dtype=np.int16) - 1,
            "blue": np.array([[row["blue"]] for row in rows], dtype=np.int16) - 1,
        }
        self.number_prefix = {}
        for color, actual in self.indices.items():
            events = np.zeros((len(rows), SIZES[color]), dtype=np.int16)
            np.put_along_axis(events, actual, 1, axis=1)
            self.number_prefix[color] = self._prefix(events)

    @staticmethod
    def _prefix(events):
        prefix = np.zeros((len(events) + 1, events.shape[1]), dtype=np.int16)
        np.cumsum(events, axis=0, dtype=np.int16, out=prefix[1:])
        return prefix

    def calculate(self, targets):
        result = {color: {target: [] for target in targets} for color in SIZES}
        indices = np.array(targets)
        for x in X_VALUES:
            origin = indices - x
            y_values = np.arange(X_MIN, x + 1)
            for color, size in SIZES.items():
                number_prefix = self.number_prefix[color]
                frequency = number_prefix[x:-1] - number_prefix[: -(x + 1)]
                number_order = np.argsort(-frequency, axis=1, kind="stable")
                inverse = np.empty_like(frequency)
                np.put_along_axis(inverse, number_order, np.arange(size, dtype=np.int16), axis=1)
                ranks = np.take_along_axis(inverse, self.indices[color][x:], axis=1)
                events = np.zeros_like(frequency)
                np.put_along_axis(events, ranks, 1, axis=1)
                prefix = self._prefix(events)
                counts = prefix[origin, None] - prefix[origin[:, None] - y_values]
                rank_order = np.argsort(-counts, axis=2, kind="stable")
                order_inverse = np.empty_like(counts)
                np.put_along_axis(order_inverse, rank_order, np.arange(1, size + 1, dtype=np.int16), axis=2)
                actual = np.take_along_axis(order_inverse, ranks[origin, None], axis=2)
                offsets = np.maximum(actual - CUTOFFS[color], 0)
                chosen = np.take_along_axis(
                    number_order[origin, None], rank_order[:, :, : TAKE[color]], axis=2
                )
                if color == "red":
                    selected = np.bitwise_or.reduce(np.left_shift(np.int64(1), chosen), axis=2)
                    hits = (actual <= TAKE[color]).sum(axis=2)
                else:
                    selected = chosen[:, :, 0] + 1
                    hits = actual[:, :, 0] == 1

                increases = ranks[origin[:, None] - y_values[1:]] + 1
                for i, target in enumerate(targets):
                    result[color][target].append(
                        (
                            x,
                            frequency[origin[i]].tolist(),
                            (ranks[origin[i]] + 1).astype("u1").tobytes(),
                            counts[i, ::CHECKPOINT].ravel().tolist(),
                            increases[i].astype("u1").tobytes(),
                            selected[i].tolist(),
                            hits[i].tolist(),
                            actual[i].astype("u1").tobytes(),
                            offsets[i].astype("u1").tobytes(),
                        )
                    )
        return result


class ReplaySummary:
    def __init__(self, color):
        self.color = color
        self.total = np.zeros(COMBINATIONS, dtype=np.int32)
        self.positions = np.zeros((COMBINATIONS, SIZES[color]), dtype=np.int32)
        self.offsets = np.zeros((COMBINATIONS, SIZES[color] - CUTOFFS[color] + 1), dtype=np.int32)
        self.hits = np.zeros((COMBINATIONS, 7), dtype=np.int32) if color == "red" else None
        self.index = np.arange(COMBINATIONS)

    def apply(self, rows, sign):
        totals = np.fromiter((hit for hits, _, _ in rows for hit in hits), dtype=np.int16, count=COMBINATIONS)
        positions = np.frombuffer(b"".join(row[1] for row in rows), dtype="u1").reshape(COMBINATIONS, -1)
        offsets = np.frombuffer(b"".join(row[2] for row in rows), dtype="u1").reshape(COMBINATIONS, -1)
        self.total += sign * totals
        np.add.at(self.positions, (self.index[:, None], positions - 1), sign)
        np.add.at(self.offsets, (self.index[:, None], offsets), sign)
        if self.hits is not None:
            self.hits[self.index, totals] += sign

    def load(self, rows):
        count = 0
        for i, (expected, row) in enumerate(zip(GRID, rows, strict=True)):
            x, y, total, positions, offsets, *hits = row
            if (x, y) != expected:
                raise ValueError("ARK summary grid differs")
            self.total[i], self.positions[i], self.offsets[i] = total, positions, offsets
            if self.hits is not None:
                self.hits[i] = hits[0]
            count += 1
        if count != COMBINATIONS:
            raise ValueError("ARK summary is incomplete")

    def validate(self):
        expected = WIDTHS[self.color] * PERIODS
        if any(np.any(matrix < 0) for matrix in (self.positions, self.offsets, self.total)):
            raise ValueError("Negative ARK replay summary")
        if not np.all(self.positions.sum(axis=1) == expected) or not np.all(
            self.offsets.sum(axis=1) == expected
        ):
            raise ValueError("ARK histograms do not cover the full snapshot")
        cutoff = CUTOFFS[self.color]
        if not np.array_equal(
            self.offsets[:, 0], self.positions[:, :cutoff].sum(axis=1)
        ) or not np.array_equal(self.offsets[:, 1:], self.positions[:, cutoff:]):
            raise ValueError("ARK cutoff offsets differ from actual positions")
        if not np.array_equal(self.total, self.positions[:, : TAKE[self.color]].sum(axis=1)):
            raise ValueError("ARK hit totals differ from actual positions")
        if self.hits is not None and (
            np.any(self.hits < 0)
            or not np.all(self.hits.sum(axis=1) == PERIODS)
            or not np.array_equal(self.hits @ np.arange(7), self.total)
        ):
            raise ValueError("ARK red hit histogram is inconsistent")

    def records(self, snapshot_id):
        for i, (x, y) in enumerate(GRID):
            result = (
                snapshot_id,
                x,
                y,
                int(self.total[i]),
                self.positions[i].tolist(),
                self.offsets[i].tolist(),
            )
            yield result if self.hits is None else (*result, self.hits[i].tolist())
