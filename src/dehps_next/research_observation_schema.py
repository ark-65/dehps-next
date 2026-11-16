"""Constrain a new profile to copying supplied observations before generation."""

import copy
import math

from .errors import DomainError

VERSION = "candidate-utility-enum-v1"
FACTS_VERSION = "candidate-facts-enum-v2"


def validate(profile):
    if (
        profile.get("observation_grammar") not in (VERSION, FACTS_VERSION)
        or profile.get("selector_contract") != "comparative-v4.6-grounded-short"
        or profile.get("ground_output_schema") is not True
    ):
        raise DomainError("SHORT_PROFILE_CHANGED", "Require the declared exact-observation grammar")


def bind(schema, context, profile):
    """Keep rankings free; each candidate may only copy its already supplied value."""
    validate(profile)
    result = copy.deepcopy(schema)
    records = result["properties"]["assessments"]["properties"]
    candidates = context["candidates"]
    if len(candidates) != len(records) or {row["id"] for row in candidates} != set(records):
        raise DomainError("OBSERVATION_SCHEMA_INPUT", "Require every exact candidate once")
    for row in candidates:
        value = row["known_utility"]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise DomainError("OBSERVATION_SCHEMA_INPUT", "Copy only finite observations or null")
        # The original keyed schema shares one record object across IDs. Copy
        # each record separately so mixed utilities cannot overwrite one another.
        record = copy.deepcopy(records[row["id"]])
        record["properties"]["known_utility"] = {
            **record["properties"]["known_utility"], "enum": [value],
        }
        records[row["id"]] = record
        if profile["observation_grammar"] == FACTS_VERSION and row["observed_evidence_keys"]:
            keys = row["observed_evidence_keys"]
            if not set(keys) <= {e["key"] for e in context["evidence"]}:
                raise DomainError("OBSERVATION_SCHEMA_INPUT", "Exact references must exist in supplied evidence")
            # Bind facts before generation, never edit a returned claim or rank.
            record["properties"]["evidence"] = {
                "type": "array", "minItems": 1, "maxItems": len(keys),
                "items": {"type": "string", "enum": keys},
            }
    return result
