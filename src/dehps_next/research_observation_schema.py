"""Constrain a new profile to copying supplied observations before generation."""

import copy
import math

from .errors import DomainError

VERSION = "candidate-utility-enum-v1"


def validate(profile):
    if (
        profile.get("observation_grammar") != VERSION
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
    return result
