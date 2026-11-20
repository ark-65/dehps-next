"""Constrain a new profile to copying supplied observations before generation."""

import copy
import math
from itertools import permutations, product

from .errors import DomainError

VERSION = "candidate-utility-enum-v1"
FACTS_VERSION = "candidate-facts-enum-v2"
RANKING_VERSION = "group-permutation-enum-v1"
LINKED_RANKING_VERSION = "group-permutation-linked-selection-v2"


def validate(profile):
    if (
        profile.get("observation_grammar") not in (VERSION, FACTS_VERSION)
        or profile.get("selector_contract") != "comparative-v4.6-grounded-short"
        or profile.get("ground_output_schema") is not True
        or ("ranking_grammar" in profile
            and profile["ranking_grammar"] not in (RANKING_VERSION, LINKED_RANKING_VERSION))
    ):
        raise DomainError("SHORT_PROFILE_CHANGED", "Require the declared exact-observation grammar")


def bind(schema, context, profile):
    """Bind supplied facts and, when declared, all legal rank orders before generation."""
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
    ranking_version = profile.get("ranking_grammar")
    if ranking_version not in (RANKING_VERSION, LINKED_RANKING_VERSION):
        return result

    groups = context["groups"]
    properties = result["properties"]
    rankings = properties["rankings"]
    orders = {group: [list(order) for order in permutations(ids)] for group, ids in groups.items()}
    if ranking_version == RANKING_VERSION:
        rankings["properties"] = {group: {"enum": allowed} for group, allowed in orders.items()}
        return result

    # Each branch permits all rank orders with its chosen first IDs and requires
    # those same IDs in selection. The union permits every valid model choice.
    alternatives = []
    for first_ids in product(*groups.values()):
        selected = dict(zip(groups, first_ids, strict=True))
        branch_rankings = {
            group: {"enum": [order for order in orders[group] if order[0] == first]}
            for group, first in selected.items()
        }
        branch_selection = {group: {"enum": [first]} for group, first in selected.items()}
        alternatives.append({
            **result,
            "properties": {
                **properties,
                "rankings": {**rankings, "properties": branch_rankings},
                "selection": {**properties["selection"], "properties": branch_selection},
            },
        })
    return {"anyOf": alternatives}
