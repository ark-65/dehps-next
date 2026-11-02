"""Actual local-model mechanism acceptance on frozen, real Next trial outcomes."""

import argparse
import copy
import hashlib
import itertools
import json
import threading
import time
from pathlib import Path

from psycopg import Error as DatabaseError
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest
from dehps_next.errors import DomainError, LeaseLost
from dehps_next.release import code_identity
from dehps_next.research import Research
from dehps_next.research_agent import request_json
from dehps_next.research_review import counts
from dehps_next.research_selection import make_context, select
from dehps_next.resources import Resources
from dehps_next.training_window import status as training_window

CORPUS = "qwen-mechanism-corpus-20261102-v2"
CONTEXT = CORPUS + "-context"
SEEDS = (1729, 43107)


def profile(model, thinking, digest_value):
    return {
        "selector_contract": "comparative-v4.4",
        "ground_output_schema": True,
        "transport": "ndjson-progress-v1",
        "repetition_guard": "8_IDENTICAL_CONSECUTIVE_256_CHARACTER_BLOCKS",
        "backend": {
            "image": "sha256:b2f0122c476bc9fe7ce679d8bb4bd555351e25e2554eefb156f61cb0a89cf429",
            "engine": "Vulkan",
            "flash_attention": True,
            "kv_cache": "q8_0",
            "cpu_threads": 4,
        },
        "model": model,
        "model_digest": digest_value,
        "think": thinking,
        "options": {
            "temperature": 0.6 if thinking else 0.7,
            "top_p": 0.95 if thinking else 0.8,
            "top_k": 20,
            "min_p": 0,
            "seed": 1729,
            "num_ctx": 40960,
            "num_predict": 32768,
        },
    }


def prepare(d, a):
    old = d.rows("SELECT protocol FROM research_review_studies WHERE id='feedback-paired-12-v2'")[0][
        "protocol"
    ]
    header = {
        "kind": "MECHANISM_CORPUS_V4",
        "source": "feedback-paired-12-v2",
        "cases": 12,
        "variants": ["base", "display", "identifier"],
        "seeds": SEEDS,
        "arms": ["feedback", "no_feedback"],
        "gate": {"accuracy": 0.9, "stability": 0.8, "first_position_max": 0.5, "feedback_lift": 0.2},
        "futility": "Stop a profile only when even every remaining feedback request correct cannot reach90percent;unexecuted requests remain NOT_RUN. No positive early stopping.",
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "controller_source": code_identity(),
        "scope": "HISTORICAL_REASONING_PROBE;ZERO_NEW_FITS;NOT_FORWARD",
        "parent_spec": old["parent_spec"],
        "parent_business": old["parent_business"],
        "source_dataset": old["source_dataset"],
        "validation": old["validation"],
    }
    existing = d.rows("SELECT protocol FROM research_review_studies WHERE id=%s", (CORPUS,))
    if existing and (
        existing[0]["protocol"].get("driver_sha256") != header["driver_sha256"]
        or existing[0]["protocol"].get("controller_source") != header["controller_source"]
    ):
        raise RuntimeError("Use the frozen driver/source or a new explicitly linked recovery corpus")
    if not existing:
        outcomes = {
            r["spec_digest"]: r["payload"]
            for r in d.rows(
                "SELECT * FROM research_review_evaluations WHERE study_id='feedback-paired-12-v2'"
            )
        }
        bases = []
        for row in d.rows(
            "SELECT pair,basis FROM research_review_pairs WHERE study_id='feedback-paired-12-v2' ORDER BY pair"
        ):
            groups = [row["basis"]["offered"][:3], row["basis"]["offered"][3:]]
            chosen = None
            for groupindex in (row["pair"] % 2, 1 - row["pair"] % 2):
                values = [round(outcomes[digest(s)]["reward"] * 200) for s in groups[groupindex]]
                if values.count(max(values)) == 1:
                    chosen = groups[groupindex]
                    break
            assert chosen
            utilities = {digest(s): round(outcomes[digest(s)]["reward"] * 200) / 200 for s in chosen}
            best = max(utilities, key=utilities.get)
            memory = {
                "evidence": [
                    {
                        "key": "f" + str(i),
                        "node": "recorded-study:" + digest(s),
                        "spec": s,
                        "hits": counts(outcomes[digest(s)]["business"]),
                        "verdict": outcomes[digest(s)]["decision"]["verdict"],
                        "known_utility": utilities[digest(s)],
                    }
                    for i, s in enumerate(chosen)
                ],
                "families": [],
                "trials": 3,
                "scope": "THREE_COMPLETED_REAL_TRIALS",
            }
            for offered in itertools.permutations(chosen):
                _, _, cs, gs, _ = make_context(
                    old["parent_spec"], old["parent_business"], offered, memory, count=1
                )
                correct = next(k for k, s in cs.items() if digest(s) == best)
                if gs["choose"].index(correct) == row["pair"] % 3:
                    break
            else:
                raise AssertionError("No balanced presentation")
            displayseed = 1730
            while True:
                _, _, _, gs2, _ = make_context(
                    old["parent_spec"],
                    old["parent_business"],
                    offered,
                    memory,
                    count=1,
                    layout_seed=displayseed,
                )
                if gs2["choose"].index(correct) == (row["pair"] % 3 + 1) % 3:
                    break
                displayseed += 1
            bases.append(
                {
                    "offered": list(offered),
                    "memory": memory,
                    "oracle_spec_digest": best,
                    "utilities": utilities,
                    "variants": {
                        "base": {"layout_seed": 1729, "id_seed": 1729},
                        "display": {"layout_seed": displayseed, "id_seed": 1729},
                        "identifier": {"layout_seed": 1729, "id_seed": 43107},
                    },
                    "scope": "REAL_RECORDED_OUTCOMES;BALANCED_BEST_POSITION",
                }
            )
        with d.pool.connection() as c, c.transaction():
            c.execute(
                "INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s)",
                (CORPUS, Jsonb(header), digest(header)),
            )
            for i, b in enumerate(bases):
                c.execute(
                    "INSERT INTO research_review_pairs(study_id,pair,basis,sha256) VALUES(%s,%s,%s,%s)",
                    (CORPUS, i, Jsonb(b), digest(b)),
                )
    Research(d, a).create(
        CONTEXT,
        planner="local",
        root_spec=old["parent_spec"],
        max_nodes=8,
        recovery_source={"purpose": "INFERENCE_ONLY_MECHANISM"},
        recovery_dataset=old["source_dataset"],
        recovery_protocol=old["validation"],
        study_source={"id": CORPUS},
    )
    node = d.rows("SELECT id FROM research_nodes WHERE campaign_id=%s", (CONTEXT,))[0]
    with d.pool.connection() as c:
        c.execute(
            "UPDATE jobs SET state='SNAPSHOT_EXCLUDED' WHERE research_node_id=%s AND kind='RESEARCH_EVALUATE'",
            (node["id"],),
        )
        Research.job(c, node["id"], "RESEARCH_PLAN")
    return d.rows("SELECT protocol FROM research_review_studies WHERE id=%s", (CORPUS,))[0]["protocol"]


def review_one(d, a, campaign, header, row, config, arm, variant, seed, *, count=1):
    job = d.claim("qwen-mechanism-v4", role="planning")
    while not job:
        time.sleep(5)
        job = d.claim("qwen-mechanism-v4", role="planning")
    owner = d.rows("SELECT campaign_id FROM research_nodes WHERE id=%s", (job["research_node_id"],))[0]
    if owner["campaign_id"] != campaign["id"]:
        d.defer(job, "YIELD_OTHER_STUDY", seconds=15)
        Resources(d).finish(job["token"], 0, 0)
        raise DomainError("STUDY_CONTEXT_COLLISION", "Finish the other isolated planning study first")
    a.reservation_token = job["token"]
    stop = threading.Event()
    lost = []

    def pulse():
        if lost:
            raise LeaseLost()
        with d.pool.connection() as c:
            if training_window(c)["paused"]:
                raise DomainError("YIELD_DRAW_PAUSE", "Resume only after complete official verification")
        d.heartbeat(job)

    def keep():
        while not stop.wait(10):
            try:
                d.heartbeat(job)
            except (DatabaseError, DomainError, PoolTimeout, TimeoutError) as e:
                lost.append(type(e).__name__)
                return

    t = threading.Thread(target=keep, daemon=True)
    t.start()
    start = time.monotonic()
    try:
        p = copy.deepcopy(config)
        p["options"]["seed"] = seed
        basis = row["basis"]
        layout = basis["variants"][variant]
        try:
            picks, receipt, proof = select(
                d,
                a,
                campaign,
                job,
                pulse,
                header["parent_spec"],
                header["parent_business"],
                basis["offered"],
                basis["memory"],
                p,
                count=count,
                feedback=arm == "feedback",
                **layout,
            )
            selected = digest(picks[0]["spec"])
            payload = {
                "valid": True,
                "correct": selected == basis.get("oracle_spec_digest") if count == 1 else None,
                "selected": selected,
                "selected_specs": [p["spec"] for p in picks],
                "position": proof["positions"][0]["position"],
                "receipt": receipt,
                "proof": proof,
            }
        except (DomainError, RuntimeError) as e:
            if isinstance(e, DomainError) and (e.code.startswith("YIELD_") or e.code == "LEASE_LOST"):
                if e.code != "LEASE_LOST":
                    d.defer(job, e.code, seconds=15)
                raise
            payload = {
                "valid": False,
                "correct": False,
                "error": getattr(e, "code", type(e).__name__),
                "message": str(e)[:400],
                "position_observation": getattr(e, "position_observation", None),
            }
        d.defer(job, "YIELD_MECHANISM_REQUEST", seconds=0)
        return payload
    finally:
        stop.set()
        t.join(2)
        Resources(d).finish(job["token"], time.monotonic() - start, 0)
        a.reservation_token = None


def recoverable_review(*args, **kwargs):
    """Retry only an unperformed infrastructure slot, with identical frozen input/seed."""
    while True:
        try:
            return review_one(*args, **kwargs)
        except DomainError as exc:
            if not exc.code.startswith("YIELD_") and exc.code != "LEASE_LOST":
                raise
            print(
                json.dumps({"infrastructure_deferred": exc.code, "logical_choice_recorded": False}),
                flush=True,
            )
            time.sleep(15)


def run_profile(d, a, header, config):
    identity = digest(config)
    study = "qwen-mechanism-" + digest([CORPUS, identity])[:16]
    total = 72
    if d.rows("SELECT 1 FROM research_review_results WHERE study_id=%s", (study,)):
        return d.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (study,))[0]["payload"]
    protocol = {
        "kind": "MECHANISM_PROFILE_V4",
        "profile": config,
        "profile_id": identity,
        "corpus": CORPUS,
        "context_campaign": CONTEXT,
        "corpus_sha": d.rows("SELECT sha256 FROM research_review_studies WHERE id=%s", (CORPUS,))[0][
            "sha256"
        ],
        "futility": header["futility"],
        "scope": "NO_NEW_FITS",
    }
    with d.pool.connection() as c:
        c.execute(
            "INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
            (study, Jsonb(protocol), digest(protocol)),
        )
        for r in d.rows("SELECT * FROM research_review_pairs WHERE study_id=%s ORDER BY pair", (CORPUS,)):
            c.execute(
                "INSERT INTO research_review_pairs(study_id,pair,basis,sha256) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (study, r["pair"], Jsonb(r["basis"]), r["sha256"]),
            )
    campaign = d.rows("SELECT * FROM research_campaigns WHERE id=%s", (CONTEXT,))[0]
    stopped = False
    for row in d.rows("SELECT * FROM research_review_pairs WHERE study_id=%s ORDER BY pair", (CORPUS,)):
        for vi, variant in enumerate(header["variants"]):
            for si, seed in enumerate(SEEDS):
                arms = (
                    ["feedback", "no_feedback"]
                    if (row["pair"] + vi + si) % 2 == 0
                    else ["no_feedback", "feedback"]
                )
                for arm in arms:
                    key = arm + ":" + variant + ":" + str(seed)
                    if not d.rows(
                        "SELECT 1 FROM research_review_selections WHERE study_id=%s AND pair=%s AND arm=%s",
                        (study, row["pair"], key),
                    ):
                        payload = recoverable_review(d, a, campaign, header, row, config, arm, variant, seed)
                        with d.pool.connection() as c:
                            c.execute(
                                "INSERT INTO research_review_selections(study_id,pair,arm,payload) VALUES(%s,%s,%s,%s)",
                                (study, row["pair"], key, Jsonb(payload)),
                            )
                        print(
                            json.dumps(
                                {
                                    "study": study,
                                    "model": config["model"],
                                    "think": config["think"],
                                    "case": row["pair"],
                                    "variant": variant,
                                    "seed": seed,
                                    "arm": arm,
                                    "valid": payload["valid"],
                                    "correct": payload["correct"],
                                    "error": payload.get("error"),
                                }
                            ),
                            flush=True,
                        )
                    feedback = d.rows(
                        "SELECT payload FROM research_review_selections WHERE study_id=%s AND arm LIKE 'feedback:%%'",
                        (study,),
                    )
                    errors = sum(not r["payload"]["correct"] for r in feedback)
                    if total - errors < 0.9 * total:
                        stopped = True
                        break
                if stopped:
                    break
            if stopped:
                break
        if stopped:
            break
    allrows = d.rows("SELECT * FROM research_review_selections WHERE study_id=%s", (study,))
    fb = [r for r in allrows if r["arm"].startswith("feedback:")]
    nf = [r for r in allrows if r["arm"].startswith("no_feedback:")]
    acc = sum(r["payload"]["correct"] for r in fb) / total
    control = sum(r["payload"]["correct"] for r in nf) / total
    valid = [r for r in fb if r["payload"]["valid"]]
    first = sum(r["payload"].get("position") == 0 for r in valid) / len(valid) if valid else None
    same = 0
    den = 0
    for case in range(12):
        for seed in SEEDS:
            values = [
                next(
                    (
                        r["payload"].get("selected")
                        for r in fb
                        if r["pair"] == case and r["arm"] == "feedback:" + v + ":" + str(seed)
                    ),
                    None,
                )
                for v in header["variants"]
            ]
            for v in values[1:]:
                den += 1
                same += int(v is not None and v == values[0])
    stability = same / den
    result = {
        "kind": "MECHANISM_PROFILE_V4",
        "study": study,
        "profile_id": identity,
        "profile": config,
        "semantic_accuracy": acc,
        "observed_feedback_accuracy": sum(r["payload"]["correct"] for r in fb) / len(fb) if fb else None,
        "observed_no_feedback_accuracy": sum(r["payload"]["correct"] for r in nf) / len(nf) if nf else None,
        "maximum_possible_feedback_accuracy": (total - sum(not r["payload"]["correct"] for r in fb)) / total,
        "no_feedback_accuracy": control,
        "accuracy_feedback_lift": acc - control,
        "first_position_fraction": first,
        "recipe_stability": stability,
        "executed_feedback": len(fb),
        "executed_no_feedback": len(nf),
        "planned_per_arm": total,
        "stopped_for_impossible_accuracy": stopped,
        "not_run": 144 - len(allrows),
        "valid_feedback": sum(r["payload"]["valid"] for r in fb),
        "passed": not stopped and acc >= 0.9 and stability >= 0.8 and first <= 0.5 and acc - control >= 0.2,
        "scope": "HISTORICAL_REASONING_MECHANISM;NOT_PREDICTIVE_PROOF;ZERO_NEW_FITS",
    }
    with d.pool.connection() as c:
        c.execute(
            "INSERT INTO research_review_results(study_id,payload) VALUES(%s,%s)", (study, Jsonb(result))
        )
    print(json.dumps({"PROFILE_RESULT": result}), flush=True)
    return result


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--corpus", required=True, help="New immutable corpus ID, at most60 characters")
    chosen = args.parse_args()
    if not chosen.corpus or len(chosen.corpus) > 60:
        raise SystemExit("Choose a new bounded corpus ID")
    global CORPUS, CONTEXT
    CORPUS, CONTEXT = chosen.corpus, chosen.corpus + "-context"
    s = Settings.from_env()
    if (
        conninfo_to_dict(s.database_url).get("dbname") != "dehps_next_parent_acceptance"
        or s.runtime.name != "parent-case"
    ):
        raise SystemExit("Refusing anything except the named isolated Next acceptance clone/runtime")
    d = Database(s)
    a = Artifacts(s, d)
    d.migrate()
    assert d.rows("SELECT current_database() AS n")[0]["n"] == "dehps_next_parent_acceptance"
    header = prepare(d, a)
    inventory = {m["name"]: m["digest"] for m in request_json("/api/tags")["models"]}
    for model in ("qwen3:1.7b", "qwen3:4b", "qwen3:8b"):
        if model not in inventory:
            raise SystemExit(f"Install the next official local model before continuing: {model}")
        for thinking in (False, True):
            result = run_profile(d, a, header, profile(model, thinking, inventory[model]))
            if result["passed"]:
                (a.root / "passed-qwen-profile.json").write_text(json.dumps(result, indent=2))
                d.close()
                return
    d.close()


if __name__ == "__main__":
    main()
