"""Rolling red and blue winning-rank selection."""

from collections import Counter
from itertools import pairwise

from .domain import now, timestamp, validate_draw
from .errors import DomainError


def _rank(counts, size):
    return sorted(range(1, size + 1), key=lambda number: (-counts[number], number))


def _counts(rows):
    return Counter(ball for row in rows for ball in row["red"]), Counter(row["blue"] for row in rows)


def _recent_frequency(rows):
    red, blue = _counts(rows)
    result = {"window": [rows[0]["issue"], rows[-1]["issue"]]}
    for color, counts, size in (("red", red, 33), ("blue", blue, 16)):
        result[color] = [
            {"number": number, "rank": rank, "count": counts[number], "frequency": counts[number] / len(rows)}
            for rank, number in enumerate(_rank(counts, size), 1)
        ]
    return result


def _history(draws, needed, as_of):
    if len(draws) < needed:
        raise DomainError("ARK_INSUFFICIENT_HISTORY", f"Need {needed} draws, got {len(draws)}")
    rows = [validate_draw(draw) for draw in draws[-needed:]]
    for row in rows:
        row["draw_at"] = timestamp(row["draw_at"])
        row["available_at"] = timestamp(row["available_at"])
        if row["available_at"] > as_of:
            raise DomainError("ARK_INSUFFICIENT_HISTORY", f"Result {row['issue']} was unavailable at cutoff")
    for previous, current in pairwise(rows):
        left, right = (int(row["issue"]) for row in (previous, current))
        if left >= right or previous["draw_at"] >= current["draw_at"]:
            raise DomainError("ARK_HISTORY_ORDER", "Draws must have unique issues in strict draw order")
        if left // 1000 == right // 1000:
            consecutive = right == left + 1
        else:
            consecutive = right // 1000 == left // 1000 + 1 and right % 1000 == 1
        if not consecutive:
            raise DomainError("ARK_INSUFFICIENT_HISTORY", f"Gap between {left} and {right}")
    return rows


def ark(draws, *, x, y, z, y2=None, mode="replay", as_of=None):
    """Run ARK on consecutive Next draw records ordered from oldest to newest.

    ``forecast`` uses the final step for the next draw. Its issue and hit fields
    are unset. Target indices are one-based within the supplied draw sequence.
    ``y2`` defaults to ``y`` and controls the separate recent number-frequency board.
    """
    if any(type(value) is not int or value < 1 for value in (x, y, z)) or y > x:
        raise DomainError("ARK_PARAMETERS", "Require positive integer x, y and z with y <= x")
    y2 = y if y2 is None else y2
    if type(y2) is not int or y2 < 1:
        raise DomainError("ARK_PARAMETERS", "Require a positive integer y2")
    if mode not in ("replay", "forecast"):
        raise DomainError("ARK_PARAMETERS", "Mode must be replay or forecast")

    forecast = mode == "forecast"
    verified = z - int(forecast)
    lookback = max(x + y, y2)
    needed = lookback + (z if verified else 0)
    cutoff = now() if as_of is None else timestamp(as_of)
    rows = _history(draws, needed, cutoff)
    offset = len(draws) - needed
    targets = set(range(lookback, lookback + verified))
    if forecast:
        targets.add(needed)

    # Each stored rank is measured using the window from before that draw.
    winning_ranks = {}
    steps = []
    for origin in range(min(targets) - y, max(targets) + 1):
        actual = rows[origin] if origin < needed else None
        is_target = origin in targets
        prior = rows[origin - x : origin]
        availability_window = max(x, y2) if is_target else x
        required = rows[origin - availability_window : origin]
        if actual is not None and max(row["available_at"] for row in required) >= actual["draw_at"]:
            raise DomainError("ARK_INSUFFICIENT_HISTORY", f"Prior results unavailable before {actual['issue']}")

        red_counts, blue_counts = _counts(prior)
        red_order = _rank(red_counts, 33)
        blue_order = _rank(blue_counts, 16)
        if is_target:
            recent = [winning_ranks[j] for j in range(origin - y, origin)]
            red_positions = _rank(Counter(rank for red, _ in recent for rank in red), 33)
            blue_positions = _rank(Counter(blue for _, blue in recent), 16)
            red = [red_order[rank - 1] for rank in red_positions[:10]]
            blue = blue_order[blue_positions[0] - 1]
            red_hits = len(set(red).intersection(actual["red"])) if actual is not None else None
            steps.append({
                "step": len(steps) + 1,
                "target_index": offset + origin + 1,
                "target_issue": actual["issue"] if actual is not None else None,
                "frequency_window": [prior[0]["issue"], prior[-1]["issue"]],
                "rank_window": [rows[origin - y]["issue"], prior[-1]["issue"]],
                "y2_frequency": _recent_frequency(rows[origin - y2 : origin]),
                "red": red,
                "blue": blue,
                "red_rank_order": red_positions,
                "blue_rank_order": blue_positions,
                "red_hits": red_hits,
                "red_coverage": red_hits / 6 if red_hits is not None else None,
                "blue_hit": blue == actual["blue"] if actual is not None else None,
                "evidence": "HISTORICAL_REPLAY" if actual is not None else "PENDING_DRAW",
            })
        if actual is not None:
            winning_ranks[origin] = (
                [red_order.index(ball) + 1 for ball in actual["red"]],
                blue_order.index(actual["blue"]) + 1,
            )

    checked = steps[:verified]
    return {
        "mode": mode,
        "y2": y2,
        "steps": steps,
        "verified_periods": verified,
        "red_coverage": sum(step["red_hits"] for step in checked) / (6 * verified) if verified else None,
        "blue_hit_rate": sum(step["blue_hit"] for step in checked) / verified if verified else None,
    }
