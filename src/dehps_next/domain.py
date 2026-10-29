import hashlib
import json
import math
from datetime import UTC, datetime

from .errors import DomainError


def now():
    return datetime.now(UTC)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp(value):
    result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise DomainError("INVALID_TIME", "Timezone is required")
    return result.astimezone(UTC)


def validate_draw(record):
    try:
        issue = record["issue"]
        red = record["red"]
        blue = record["blue"]
        if not isinstance(issue, str) or not issue.isdigit() or len(issue) != 7:
            raise ValueError("issue must be a seven-digit string")
        if not isinstance(red, list) or len(red) != 6 or any(type(v) is not int for v in red):
            raise ValueError("red must contain six integers")
        if len(set(red)) != 6 or not all(1 <= v <= 33 for v in red):
            raise ValueError("invalid red balls")
        if type(blue) is not int or not 1 <= blue <= 16:
            raise ValueError("invalid blue ball")
        at = timestamp(record["available_at"])
        draw_at = timestamp(record["draw_at"])
        if at < draw_at:
            raise ValueError("label availability precedes the draw")
        return {
            "issue": issue,
            "red": sorted(red),
            "blue": blue,
            "draw_at": draw_at.isoformat(),
            "available_at": at.isoformat(),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("INVALID_DRAW", str(exc)) from exc


def top_red_combinations(probabilities, count=100):
    """Top-K fixed-cardinality subsets by marginal log-odds, not a joint probability."""
    if len(probabilities) != 33 or not all(math.isfinite(p) and 0 < p < 1 for p in probabilities):
        raise DomainError("INVALID_PROBABILITY", "Expected 33 finite probabilities in (0,1)")
    best = [[] for _ in range(7)]
    best[0] = [(0.0, ())]
    for ball, p in enumerate(probabilities, 1):
        score = math.log(p) - math.log1p(-p)
        for size in range(min(6, ball), 0, -1):
            candidates = best[size] + [(s + score, c + (ball,)) for s, c in best[size - 1]]
            best[size] = sorted(candidates, key=lambda pair: (-pair[0], pair[1]))[:count]
    return [list(c) for _, c in best[6]]


def evaluate(prediction, actual, baseline):
    red_p, blue_p = prediction["red_probabilities"], prediction["blue_probabilities"]
    actual_red = set(actual["red"])
    scores = [len(set(c) & actual_red) for c in prediction["red_top100"]]
    baseline_red = [len(set(c) & actual_red) for c in baseline["red_top100"]]
    random_red = [len(set(c) & actual_red) for c in baseline["random_red_top100"]]
    return {
        "blue_top1_hit": int(prediction["blue_top1"] == actual["blue"]),
        "blue_log_loss": -math.log(max(blue_p[actual["blue"] - 1], 1e-12)),
        "baseline_blue_top1_hit": int(baseline["blue_top1"] == actual["blue"]),
        "baseline_blue_log_loss": -math.log(max(baseline["blue_probabilities"][actual["blue"] - 1], 1e-12)),
        "red_brier": sum((p - int(i + 1 in actual_red)) ** 2 for i, p in enumerate(red_p)) / 33,
        "red_max_matches": max(scores),
        "red_four_plus_tickets": sum(s >= 4 for s in scores),
        "red_hit_distribution": {str(i): scores.count(i) for i in range(7)},
        "baseline_red_max_matches": max(baseline_red),
        "baseline_red_four_plus_tickets": sum(s >= 4 for s in baseline_red),
        "random_red_max_matches": max(random_red),
        "random_red_four_plus_tickets": sum(s >= 4 for s in random_red),
        "random_blue_top1_reference": 1 / 16,
    }
