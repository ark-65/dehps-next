"""A separately frozen input view: preserve all facts, make identity joins explicit."""

import json
from .errors import DomainError

VERSION = "candidate-facts-last-v1"


def validate(profile):
    if (profile.get("input_rendering") != VERSION
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
    presented = {"output_contract": schema}
    presented.update({key: value for key, value in context.items() if key != "candidates"})
    presented["candidates"] = [
        {key: row[key] for key in ("id", "known_utility", "observed_evidence_keys", "changes", "spec")}
        for row in rows
    ]
    return [
        {"role": "system", "content": (
            "Compare the candidates, then reply in English JSON: assessments, rankings, selection. "
            "Start reasoning with the candidate facts, not a restatement of the input or output format. "
            "Keep each candidate ID attached to its own score and evidence. "
            "A larger signed utility is better when trials are known; null means unknown, never zero. "
            "For unknown trials compare supplied failures and risks without inventing outcomes. "
            "IDs, input positions and evidence key names imply no preference."
        )},
        {"role": "user", "content": json.dumps(
            presented, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        )},
    ]
