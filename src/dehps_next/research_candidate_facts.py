"""A separately frozen input view: preserve all facts, make identity joins explicit."""

import json
from .errors import DomainError

VERSION = "candidate-facts-last-v1"
COMPACT_VERSION = "candidate-facts-compact-v2"


def validate(profile):
    if (profile.get("input_rendering") not in (VERSION, COMPACT_VERSION)
            or profile.get("observation_grammar") != "candidate-facts-enum-v2"
            or profile.get("selector_contract") != "comparative-v4.6-grounded-short"
            or profile.get("ground_output_schema") is not True):
        raise DomainError("SHORT_PROFILE_CHANGED", "Require the frozen candidate-facts input view")


def messages(context, schema, profile):
    """No sorting, computed ranks, score changes, omissions or outcome-dependent hints."""
    validate(profile)
    rows = context["candidates"]
    candidates = {row["id"]: row for row in rows}
    ids = [key for group in context["groups"].values() for key in group]
    if len(ids) != len(candidates) or set(ids) != set(candidates):
        raise DomainError("OBSERVATION_SCHEMA_INPUT", "Each real candidate must belong to one group")
    # Keep the original JSON object and every value: existing receipts can still
    # verify the exact logical input after removing output_contract. Only object
    # field presentation changes; group and candidate array order stays frozen.
    compact = profile["input_rendering"] == COMPACT_VERSION
    contract = {
        "assessments": "One object per exact candidate ID; fields assessment, evidence, known_utility. "
                       "assessment:8-96 character comparison of utility or risk, never only an ID or verdict. "
                       "evidence:array of exact evidence keys. known_utility:copy its own supplied number or null.",
        "rankings": "One array per group; every group candidate ID exactly once, best first.",
        "selection": "One ID per group, identical to the FIRST ID in that group's ranking.",
    } if compact else schema
    presented = {"output_contract": contract}
    presented.update({key: value for key, value in context.items() if key != "candidates"})
    presented["candidates"] = [
        {key: row[key] for key in ("id", "known_utility", "observed_evidence_keys", "changes", "spec")}
        for row in rows
    ]
    system = (
            "Compare the candidates, then reply in English JSON: assessments, rankings, selection. "
            "Start reasoning with the candidate facts, not a restatement of the input or output format. "
            "Keep each candidate ID attached to its own score and evidence. "
            "A larger signed utility is better when trials are known; null means unknown, never zero. "
            "For unknown trials compare supplied failures and risks without inventing outcomes. "
            "IDs, input positions and evidence key names imply no preference."
    )
    if compact:
        system = (
            "Compare candidates, then output JSON with assessments, rankings, selection in that order. "
            "Begin reasoning by comparing utilities, not restating the format. "
            "For completed trials rank by DESCENDING known_utility: larger is better. "
            "Among negative numbers, the smaller absolute value is larger; zero exceeds any negative. "
            "Keep each candidate ID attached to its own utility and exact evidence keys. "
            "For null utilities compare supplied failure/risk evidence; null is unknown, never zero. "
            "Each assessment must compare utility or risk, not merely repeat an ID or verdict. "
            "Before answering check every group has every ID once and selection equals its FIRST ranked ID. "
            "IDs and input positions imply no preference. Never invent future outcomes."
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(
            presented, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        )},
    ]
