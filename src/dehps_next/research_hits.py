"""Chronological100/50/10 replay and incremental paired red5+/blueTop1 progress."""

from functools import lru_cache

from .domain import digest, timestamp, top_red_combinations
from .errors import DomainError
from .research_protocol import _interval

VERSION = "recent100-tail50-tail10-hits-v4"
WINDOWS = ("recent", "recent50", "recent10")


def make_protocol(size):
    if size <= 228:
        raise DomainError("RESEARCH_DATA_BUDGET", "Need100 validation periods with sufficient prior history")
    origins = list(range(size - 100, size))
    protocol = {
        "version": VERSION,
        "origins": origins,
        "recent": origins,
        "recent50": origins[-50:],
        "recent10": origins[-10:],
        "random_historical": [],
        "reserve": [],
        "seed": 1729,
        "minimum_history": 128,
        "primary": "paired_red5_top100_and_blue_top1_rates",
        "red_minimum_matches": 5,
        "blue50": "LONG_TERM_REFERENCE_NOT_IMPROVEMENT_GATE",
        "regression_margin": 0.02,
        "red_brier_tolerance": 0.01,
        "bootstrap_replicates": 1000,
        "block_length": 5,
        "sampling": "chronological_last100_with_nested50_and10;no_random_historical_origins",
        "training_start": "fresh_common_seed_for_each_origin_and_candidate",
        "reserve_policy": "none;repeating_the_same_periods_is_not_more_independent_evidence",
        "promotion": "one_recent100_hit_rate_increases;both_non_decreasing_in100_50_10",
        "evidence": "OBSERVED_PAIRED_DEVELOPMENT_REPLAY;NOT_SIGNIFICANT_OR_FORWARD_PROOF",
    }
    protocol["digest"] = digest(protocol)
    return protocol


@lru_cache(maxsize=256)
def _red_hits(probabilities, actual):
    tickets = top_red_combinations(list(probabilities))
    matches = [len(set(ticket) & set(actual)) for ticket in tickets]
    return max(matches), sum(n >= 5 for n in matches), digest(tickets)


def measure(rows, snapshot, protocol):
    if digest({k: v for k, v in protocol.items() if k != "digest"}) != protocol["digest"]:
        raise DomainError("VALIDATION_PROTOCOL_CORRUPT", "Protocol changed after freezing")
    expected = protocol["origins"]
    if sorted(r["origin"] for r in rows) != expected:
        raise DomainError("INCOMPLETE_HIT_VALIDATION", "Exactly the frozen100 unique origins are required")
    periods = {}
    for row in rows:
        i = row["origin"]
        actual, prior = snapshot["rows"][i], snapshot["rows"][i - 1]
        if (
            row["issue"] != actual["issue"]
            or row["training_through"] != prior["issue"]
            or timestamp(prior["available_at"]) >= timestamp(actual["draw_at"])
        ):
            raise DomainError("VALIDATION_BOUNDARY_CHANGED", "Hit evidence must use the legal prior prefix")
        blue = row["blue_probabilities"]
        hit = int(blue.index(max(blue)) + 1 == actual["blue"])
        if hit != row["blue_hit"]:
            raise DomainError("VALIDATION_SCORE_CHANGED", "Blue hit differs from frozen probabilities")
        maximum, five_tickets, top_digest = _red_hits(tuple(row["red_probabilities"]), tuple(actual["red"]))
        periods[i] = {
            "issue": actual["issue"],
            "red5_hit": int(maximum >= 5),
            "max_red": maximum,
            "red5_tickets": five_tickets,
            "blue_hit": hit,
            "top100_digest": top_digest,
        }
    windows = {}
    for key in WINDOWS:
        chosen = [periods[i] for i in protocol[key]]
        red = sum(p["red5_hit"] for p in chosen)
        blue = sum(p["blue_hit"] for p in chosen)
        windows[key] = {
            "n": len(chosen),
            "red5_periods": red,
            "red5_rate": red / len(chosen),
            "blue_hits": blue,
            "blue_rate": blue / len(chosen),
        }
    return {
        "windows": windows,
        "periods": periods,
        "periods_digest": digest(periods),
        "red5_issues": [p["issue"] for p in periods.values() if p["red5_hit"]],
        "definition": "An issue counts once if any of its100 frozen red combinations hits5 or6;one blueTop1 per issue",
        "evidence": protocol["evidence"],
    }


def public(metrics):
    return {k: v for k, v in metrics.items() if k != "periods"}


def review(parent, child, protocol):
    deltas = {}
    for key in WINDOWS:
        p, c = parent["windows"][key], child["windows"][key]
        deltas[key] = {
            "red5_rate": c["red5_rate"] - p["red5_rate"],
            "blue_rate": c["blue_rate"] - p["blue_rate"],
        }
    intervals = {
        key: _interval(
            [child["periods"][i][key] - parent["periods"][i][key] for i in protocol["recent"]], protocol
        )
        for key in ("red5_hit", "blue_hit")
    }
    non_regression = all(v >= 0 for window in deltas.values() for v in window.values())
    progress = any(v > 0 for v in deltas["recent"].values())
    confirmed_regression = any(v[1] < 0 for v in intervals.values())
    verdict = (
        "ACCEPT_IMPROVEMENT"
        if progress and non_regression
        else "PRUNE_REGRESSION"
        if confirmed_regression
        else "INCONCLUSIVE"
    )
    return {
        "verdict": verdict,
        "protocol_digest": protocol["digest"],
        "business": {
            "parent": public(parent),
            "child": public(child),
            "paired_windows": deltas,
            "recent100_paired_interval95": intervals,
            "nested_windows_not_independent": True,
            "non_regression_all_windows": non_regression,
            "observed_recent_progress": progress,
            "statistically_confirmed": False,
            "multiple_search_adjusted": False,
            "development_interval_excludes_zero": progress
            and non_regression
            and all(
                v[0] > 0
                for k, v in intervals.items()
                if deltas["recent"]["red5_rate" if k == "red5_hit" else "blue_rate"] > 0
            ),
        },
        "reserve_used": False,
        "n_unique": 100,
        "evidence": "OBSERVED_PAIRED_DEVELOPMENT_PROGRESS;INSPECT_INTERVALS;NOT_FORWARD_PROOF",
    }
