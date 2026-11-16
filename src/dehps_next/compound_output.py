"""Versioned seven-red/two-blue Top10 output; official labels remain six-red plus one-blue."""

import math
import os
from itertools import combinations

from .domain import digest
from .errors import DomainError

CONTRACT = "seven-red-top10-blue-top2-v1"
LEGACY = "six-red-top100-blue-top1-v1"


def selected():
    value = os.getenv("DEHPS_NEXT_OUTPUT_CONTRACT", LEGACY)
    if value not in (LEGACY, CONTRACT):
        raise DomainError("OUTPUT_CONTRACT_UNKNOWN", "Require an explicit registered output contract")
    return value


def tickets(probabilities):
    if len(probabilities) != 33 or not all(math.isfinite(p) and 0 < p < 1 for p in probabilities):
        raise DomainError("INVALID_PROBABILITY", "Require33 finite red marginal probabilities")
    best = [[] for _ in range(8)]
    best[0] = [(0.0, ())]
    for ball, p in enumerate(probabilities, 1):
        score = math.log(p) - math.log1p(-p)
        for size in range(min(7, ball), 0, -1):
            candidates = best[size] + [(s + score, c + (ball,)) for s, c in best[size - 1]]
            best[size] = sorted(candidates, key=lambda x: (-x[0], x[1]))[:10]
    return [list(c) for _, c in best[7]]


def make(probabilities, blue_probabilities):
    if (len(blue_probabilities) != 16 or not all(math.isfinite(p) and 0 < p < 1 for p in blue_probabilities)
        or abs(sum(blue_probabilities) - 1) > 1e-6):
        raise DomainError("INVALID_BLUE", "Require16 normalized blue probabilities")
    ranked = sorted(range(1, 17), key=lambda b: (-blue_probabilities[b - 1], b))
    blue, blues = ranked[0], sorted(ranked[:2])
    groups = tickets(probabilities)
    expanded = {tuple(c) for group in groups for c in combinations(group, 6)}
    return {"contract": CONTRACT, "tickets": groups, "blue": blue, "blues": blues,
            "groups": 10, "red_per_group": 7, "expanded_single_entries": 140,
            "unique_red_single_entries": len(expanded), "unique_single_entries": 2 * len(expanded),
            "ranking": "sum_of_marginal_log_odds;not_joint_probability",
            "digest": digest([CONTRACT, groups, blue, blues])}


def attach(prediction):
    if selected() == CONTRACT:
        prediction = {**prediction, "compound_output": make(prediction["red_probabilities"], prediction["blue_probabilities"])}
    return prediction


def validate(output):
    groups = output.get("tickets", [])
    if (output.get("contract") != CONTRACT or len(groups) != 10
        or len({tuple(t) for t in groups}) != 10
        or any(len(t) != 7 or t != sorted(set(t)) or any(type(v) is not int or not 1 <= v <= 33 for v in t) for t in groups)
        or type(output.get("blue")) is not int or not 1 <= output["blue"] <= 16
        or len(output.get("blues", [])) != 2 or output["blues"] != sorted(set(output["blues"]))
        or any(type(v) is not int or not 1 <= v <= 16 for v in output["blues"])
        or output["blue"] not in output["blues"]
        or output.get("digest") != digest([CONTRACT, groups, output["blue"], output["blues"]])):
        raise DomainError("INVALID_COMPOUND_SEAL", "Require exact sealed Top10 seven-red groups")
    expanded = {tuple(c) for t in groups for c in combinations(t, 6)}
    if output.get("expanded_single_entries") != 140 or output.get("unique_red_single_entries") != len(expanded) or output.get("unique_single_entries") != 2 * len(expanded):
        raise DomainError("INVALID_COMPOUND_COVERAGE", "Expanded coverage differs from seal")
    return output


def settle(output, actual):
    validate(output)
    red = set(actual["red"])
    matches = [len(set(t) & red) for t in output["tickets"]]
    expanded = {tuple(c) for t in output["tickets"] for c in combinations(t, 6)}
    return {"contract": CONTRACT, "seal_digest": output["digest"],
            "red_max_matches": max(matches), "red5_hit": int(max(matches) >= 5),
            "blue_top2_hit": int(actual["blue"] in output["blues"]),
            "group_hit_distribution": {str(i): matches.count(i) for i in range(7)},
            "unique_red_single_entries": len(expanded), "unique_single_entries": 2 * len(expanded),
            "unique_single_hit_distribution": {str(i): sum(len(set(t) & red) == i for t in expanded) for i in range(7)}}


def mail_fields(output):
    validate(output)
    return {"tickets": output["tickets"], "blue": output["blue"], "blues": output["blues"], "compound_output": output,
            "output_contract": CONTRACT}


def description(output):
    validate(output)
    return (f"Top10复式：10组7红＋2蓝，共用蓝球{'、'.join(f'{v:02d}' for v in output['blues'])}；展开140注，"
            f"去重覆盖{output['unique_single_entries']}注（{output['unique_red_single_entries']}组红球×2蓝）。新口径独立统计，旧Top100成绩不作为新格式成绩。")
