"""Separate observable choice positions, contract validity and semantic correctness."""

from .domain import digest

SEMANTIC_FAILURES = {
    "INVALID_COMPARATIVE_SELECTION",
    "INVALID_LOCAL_REPLY",
    "LOCAL_MODEL_TRUNCATED",
    "LOCAL_MODEL_REPETITION",
}


def observe_positions(context, reply):
    if not isinstance(reply, dict) or not isinstance(reply.get("selection"), dict):
        return []
    recipes = {r["id"]: digest(r["spec"]) for r in context["candidates"]}
    positions = []
    for group, ids in context["groups"].items():
        key = reply["selection"].get(group)
        positions.append(
            {
                "group": group,
                "position": ids.index(key) if key in ids else None,
                "options": len(ids),
                "recipe": recipes.get(key) if isinstance(key, str) else None,
            }
        )
    return positions


def mechanism_progress(db):
    studies = db.rows("""SELECT s.id,s.protocol,s.created_at,r.payload AS result
        FROM research_review_studies s LEFT JOIN research_review_results r ON r.study_id=s.id
        WHERE s.protocol->>'kind'='MECHANISM_PROFILE_V4'
        ORDER BY s.created_at DESC LIMIT 6""")
    if not studies:
        return []
    # Do not retrieve raw thinking or duplicate large provider receipts in the status API.
    rows = db.rows(
        """SELECT study_id,pair,arm,payload->'valid' AS valid,payload->'correct' AS correct,
        payload->>'error' AS error,payload->>'selected' AS selected,
        payload->'position' AS position,payload->'position_observation' AS observation,
        payload->'origin' AS origin,created_at FROM research_review_selections
        WHERE study_id=ANY(%s) ORDER BY created_at""",
        ([s["id"] for s in studies],),
    )
    output = []
    for study in studies:
        chosen = [r for r in rows if r["study_id"] == study["id"]]
        arms = {}
        for arm in ("feedback", "no_feedback"):
            trials = [r for r in chosen if r["arm"].startswith(arm + ":")]
            infrastructure = [r for r in trials if not r["valid"] and r["error"] not in SEMANTIC_FAILURES]
            performed = [r for r in trials if r not in infrastructure]
            observed = [
                p["position"]
                for r in performed
                for p in (
                    r["observation"]
                    if r["observation"] is not None
                    else ([{"position": r["position"]}] if r["valid"] else [])
                )
                if p.get("position") is not None
            ]
            correct = sum(r["correct"] is True for r in performed)
            arms[arm] = {
                "recorded_slots": len(trials),
                "infrastructure_voids": len(infrastructure),
                "performed_semantic_requests": len(performed),
                "valid_responses": sum(r["valid"] is True for r in performed),
                "semantic_correct": correct,
                "observed_accuracy": correct / len(performed) if performed else None,
                "raw_legal_choice_positions": len(observed),
                "raw_first_positions": observed.count(0),
                "raw_nonfirst_positions": sum(p > 0 for p in observed),
                "requests_without_legal_position_evidence": len(performed) - len(observed),
                "raw_first_position_fraction": observed.count(0) / len(observed) if observed else None,
                "position_scope": "PARSEABLE_LEGAL_IDS_INCLUDING_CONTRACT_INVALID_REPLIES;MISSING_POSITIONS_NOT_IMPUTED",
            }
        indexed = {(r["pair"], r["arm"]): r for r in chosen}
        matched, identical = 0, 0
        difference = 0
        for r in chosen:
            if not r["arm"].startswith("feedback:"):
                continue
            other = indexed.get((r["pair"], "no_" + r["arm"]))
            if not other or any(not t["valid"] and t["error"] not in SEMANTIC_FAILURES for t in (r, other)):
                continue
            matched += 1
            difference += int(r["correct"] is True) - int(other["correct"] is True)
            identical += bool(r["valid"] and other["valid"] and r["selected"] == other["selected"])
        profile = study["protocol"]["profile"]
        output.append(
            {
                "study_id": study["id"],
                "model": profile["model"],
                "thinking": profile["think"],
                "selector_contract": profile["selector_contract"],
                "result_state": (
                    "STOPPED_WITH_UNRUN_SLOTS"
                    if study["result"] and len(chosen) < 144
                    else ("COMPLETED" if study["result"] else "IN_PROGRESS")
                ),
                "planned_slots": 144,
                "unrecorded_slots": 144 - len(chosen),
                "passed": study["result"].get("passed") if study["result"] else None,
                "last_recorded_at": max((r["created_at"] for r in chosen), default=None),
                "source_databases": sorted({r["origin"]["database"] for r in chosen if r["origin"]}),
                "arms": arms,
                "matched_semantic_pairs": matched,
                "matched_correct_difference": difference,
                "matched_valid_identical_choices": identical,
                "scope": "DESCRIPTIVE_MECHANISM_PROGRESS;NOT_EFFECT_STUDY_OR_FORWARD_PROOF;ZERO_NEW_FITS",
            }
        )
    return output
