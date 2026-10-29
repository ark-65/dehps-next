"""Frozen historical-origin sampling and paired development-evidence decisions."""

import math
import random

import numpy as np

from .domain import digest
from .errors import DomainError


def make_protocol(size, recent=60, historical=200, seed=1729, minimum=128):
    if size <= minimum + recent or not 4 <= recent <= 120 or not 4 <= historical <= 400:
        raise DomainError("RESEARCH_DATA_BUDGET", "Insufficient history or invalid validation budget")
    rng = random.Random(seed)
    eligible = list(range(minimum, size))
    recent_origins = eligible[-recent:]
    strata = np.array_split(np.array(eligible), 10)
    sampled = []
    for i, stratum in enumerate(strata):
        count = historical // 10 + int(i < historical % 10)
        sampled.extend(rng.sample(stratum.tolist(), min(count, len(stratum))))
    origins = sorted(set(recent_origins + sampled))
    remaining = [i for i in eligible if i not in set(origins)]
    reserve = sorted(rng.sample(remaining, min(40, len(remaining))))
    protocol = {
        "recent": recent_origins,
        "random_historical": sorted(sampled),
        "origins": origins,
        "reserve": reserve,
        "seed": seed,
        "minimum_history": minimum,
        "primary": "blue_log_loss",
        "regression_margin": 0.02,
        "red_brier_tolerance": 0.01,
        "bootstrap_replicates": 1000,
        "block_length": 5,
        "evidence": "DEVELOPMENT_REPLAY_NOT_FORWARD_OR_PROTECTED_HOLDOUT",
        "training_start": "fresh_common_seed_for_each_origin_and_candidate",
        "sampling": "ten_time_strata_without_replacement;never_condition_on_outcomes",
        "reserve_policy": "precomputed_bounded_development_recheck;not_independent_final_evidence",
    }
    protocol["digest"] = digest(protocol)
    return protocol


def summary(rows, origins):
    lookup = {r["origin"]: r for r in rows}
    chosen = [lookup[i] for i in origins]
    return {
        "n": len(chosen),
        "blue_log_loss": float(np.mean([r["blue_log_loss"] for r in chosen])),
        "red_brier": float(np.mean([r["red_brier"] for r in chosen])),
        "blue_top1_hits": sum(r["blue_hit"] for r in chosen),
        "blue_top1_rate": sum(r["blue_hit"] for r in chosen) / len(chosen),
    }


def _interval(values, protocol):
    values = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(protocol["seed"])
    block = min(protocol["block_length"], len(values))
    starts = rng.integers(
        0, len(values), size=(protocol["bootstrap_replicates"], math.ceil(len(values) / block))
    )
    indices = (starts[:, :, None] + np.arange(block)) % len(values)
    means = values[indices.reshape(len(starts), -1)[:, : len(values)]].mean(axis=1)
    return [float(v) for v in np.quantile(means, [0.025, 0.975])]


def review(parent, child, protocol):
    p = {r["origin"]: r for r in parent}
    c = {r["origin"]: r for r in child}
    expected = set(protocol["origins"] + protocol["reserve"])
    if set(p) != expected or set(c) != expected:
        raise DomainError("VALIDATION_LIST_CHANGED", "Parent and child must use the same frozen origin list")
    for origin in expected:
        if (
            p[origin]["issue"] != c[origin]["issue"]
            or p[origin]["training_through"] != c[origin]["training_through"]
        ):
            raise DomainError("VALIDATION_BOUNDARY_CHANGED", "Origin or training boundary differs")
    recent = float(np.mean([c[i]["blue_log_loss"] - p[i]["blue_log_loss"] for i in protocol["recent"]]))
    historical = float(
        np.mean([c[i]["blue_log_loss"] - p[i]["blue_log_loss"] for i in protocol["random_historical"]])
    )
    result = {}
    for use_reserve in (False, True):
        origins = sorted(expected if use_reserve else protocol["origins"])
        delta = [c[i]["blue_log_loss"] - p[i]["blue_log_loss"] for i in origins]
        red_delta = float(np.mean([c[i]["red_brier"] - p[i]["red_brier"] for i in origins]))
        lower, upper = _interval(delta, protocol)
        margin = protocol["regression_margin"]
        if lower > margin and recent > 0 and historical > 0:
            verdict = "PRUNE_REGRESSION"
        elif (
            upper < -margin
            and recent < margin
            and historical < margin
            and red_delta <= protocol["red_brier_tolerance"]
        ):
            verdict = "ACCEPT_IMPROVEMENT"
        else:
            verdict = "INCONCLUSIVE"
        result = {
            "verdict": verdict,
            "paired_mean_blue_loss_delta": float(np.mean(delta)),
            "paired_development_interval95": [lower, upper],
            "recent_delta": recent,
            "random_historical_delta": historical,
            "red_brier_delta": red_delta,
            "n_unique": len(origins),
            "reserve_used": use_reserve,
            "protocol_digest": protocol["digest"],
            "evidence": protocol["evidence"],
        }
        if verdict != "INCONCLUSIVE" or not protocol["reserve"]:
            break
    return result
