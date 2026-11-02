"""Frozen24-pool local selection comparison; require a passed mechanism before any new fits."""

import argparse
import hashlib
import itertools
import json
import random
import time
from collections import Counter

# The mechanism runner keeps actual lease heartbeats and persists every provider receipt.
from importlib.machinery import SourceFileLoader
from pathlib import Path

import numpy as np
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest
from dehps_next.release import code_identity, numeric_identity
from dehps_next.research import Research
from dehps_next.research_compute import close_origin_pool
from dehps_next.research_hits import measure, review
from dehps_next.research_memory import untried_specs
from dehps_next.research_review import cross_round_feedback
from dehps_next.research_selection import activate
from dehps_next.scores import decode
from dehps_next.worker import Worker

mechanism = SourceFileLoader(
    "selection_mechanism", str(Path(__file__).with_name("benchmark-selection.py"))
).load_module()
SEED = 43107


def require_frozen(header):
    if (
        header["numeric"] != numeric_identity()
        or header["code"] != code_identity()
        or header["driver_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        or header["mechanism_driver_sha256"]
        != hashlib.sha256(Path(mechanism.__file__).read_bytes()).hexdigest()
    ):
        raise RuntimeError("Use the frozen effect source and both frozen drivers")


def compute(db, artifacts, name):
    worker = Worker(db, artifacts, role="compute", worker_id="selection-effect-compute")
    while True:
        node = db.rows("SELECT * FROM research_nodes WHERE campaign_id=%s", (name,))[0]
        if node["evaluation"]:
            return node
        if not worker.once():
            time.sleep(1)


def prepare(db, artifacts, study, mechanism_study):
    existing = db.rows("SELECT protocol FROM research_review_studies WHERE id=%s", (study,))
    if existing:
        require_frozen(existing[0]["protocol"])
    passed = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (mechanism_study,))[0][
        "payload"
    ]
    config = passed["profile"]
    activate(db, config, mechanism_study)  # Recomputes all four gates from144 immutable requests.
    if existing:
        return
    old = db.rows("SELECT protocol FROM research_review_studies WHERE id=%s", (mechanism_study,))[0][
        "protocol"
    ]
    corpus = db.rows("SELECT protocol FROM research_review_studies WHERE id=%s", (old["corpus"],))[0][
        "protocol"
    ]
    name = study + "-parent"
    Research(db, artifacts).create(
        name,
        planner="local",
        max_nodes=2,
        root_spec=corpus["parent_spec"],
        recovery_source={"purpose": "FROZEN_COMPARISON_PARENT"},
        recovery_dataset=corpus["source_dataset"],
        recovery_protocol=corpus["validation"],
        study_source={"id": study},
    )
    parent = compute(db, artifacts, name)
    assert parent["evaluation"]["business"] == corpus["parent_business"]
    campaign = db.rows("SELECT * FROM research_campaigns WHERE id=%s", (name,))[0]
    memory = cross_round_feedback(db, campaign, parent)
    if not memory["evidence"] or not memory["trials"]:
        raise RuntimeError("Comparable real failure feedback is required")
    base = parent["spec"]
    local = []
    for field, values in {
        "learning_rate": [round(base["learning_rate"] * 2 ** (i / 16), 8) for i in range(-64, 65) if i],
        "weight_decay": [round(i * 0.001, 6) for i in range(1, 100)],
        "epochs": list(range(8, 161, 2)),
    }.items():
        local.extend({**base, field: v} for v in values if v != base[field])
    broad = [
        {**base, "method": m, "window": w, "hidden": h, "train_history": hist}
        for m, w, h, hist in itertools.product(
            ("fft", "ridge", "newton"),
            (8, 16, 24, 32, 40, 48, 56, 64),
            (32, 64, 96, 128, 192, 256),
            (192, 256, 384, 512, 768, 1024),
        )
    ]
    local = untried_specs(db, campaign["dataset_id"], local)
    used = {digest(s) for s in local}
    broad = untried_specs(db, campaign["dataset_id"], [s for s in broad if digest(s) not in used])
    rng = random.Random(SEED)
    rng.shuffle(local)
    rng.shuffle(broad)
    assert len(local) >= 72 and len(broad) >= 72
    protocol = {
        "kind": "SELECTION_EFFECT_24_V4",
        "pairs": 24,
        "pool_size": 6,
        "choices_per_arm": 2,
        "seed": SEED,
        "profile": config,
        "mechanism_study": mechanism_study,
        "parent_campaign": name,
        "parent_spec": base,
        "parent_business": parent["evaluation"]["business"],
        "parent_scores": parent["evaluation"]["scores"],
        "parent_model": parent["evaluation"]["publication_anchor"],
        "source_dataset": campaign["dataset_id"],
        "validation": campaign["protocol"],
        "numeric": numeric_identity(),
        "code": code_identity(),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "mechanism_driver_sha256": hashlib.sha256(Path(mechanism.__file__).read_bytes()).hexdigest(),
        "primary": "mean delta_red100+delta_blue100-minus-all-negative-deltas-in100/50/10",
        "secondary": "unchanged paired100/50/10 promotion fraction",
        "analysis": "24 paired pools;one-sided exact sign-flip via integer lattice DP;fixed10000 paired bootstrap95percent;positive difference and p<=.05 only;no extension",
        "invalid_selection": "Persist invalid arm,never substitute a choice;no claim of benefit if any arm invalid",
        "scope": "HISTORICAL_DEVELOPMENT;14400_ORIGINS_SHARE100_LABELS;NOT_FORWARD",
    }
    pools = [local[3 * i : 3 * i + 3] + broad[3 * i : 3 * i + 3] for i in range(24)]
    assert len({digest(s) for p in pools for s in p}) == 144
    with db.pool.connection() as c, c.transaction():
        c.execute(
            "INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s)",
            (study, Jsonb(protocol), digest(protocol)),
        )
        for i, pool in enumerate(pools):
            basis = {
                "offered": pool,
                "memory": memory,
                "arm_order": ["feedback", "no_feedback"] if i % 2 == 0 else ["no_feedback", "feedback"],
                "variants": {"base": {"layout_seed": 1729 + i, "id_seed": SEED + i}},
            }
            c.execute(
                "INSERT INTO research_review_pairs(study_id,pair,basis,sha256) VALUES(%s,%s,%s,%s)",
                (study, i, Jsonb(basis), digest(basis)),
            )
    print(json.dumps({"frozen_pools": 24, "unique_candidates": 144, "new_candidate_fits": 0}), flush=True)


def choose(db, artifacts, study):
    header = db.rows("SELECT protocol FROM research_review_studies WHERE id=%s", (study,))[0]["protocol"]
    require_frozen(header)
    assert not db.rows("SELECT 1 FROM research_review_evaluations WHERE study_id=%s", (study,))
    campaign = db.rows("SELECT * FROM research_campaigns WHERE id=%s", (header["parent_campaign"],))[0]
    parent = db.rows("SELECT * FROM research_nodes WHERE campaign_id=%s", (header["parent_campaign"],))[0]
    with db.pool.connection() as c:
        if c.execute("SELECT 1 FROM jobs WHERE kind='RESEARCH_PLAN' AND state='RUNNING' LIMIT 1").fetchone():
            raise RuntimeError("Finish the active isolated inference study before locking effect choices")
        c.execute(
            """UPDATE jobs SET state='SNAPSHOT_EXCLUDED'
            WHERE kind='RESEARCH_PLAN' AND state='READY' AND research_node_id!=%s""",
            (parent["id"],),
        )
        c.execute(
            "UPDATE jobs SET state='READY',not_before=now() WHERE research_node_id=%s AND kind='RESEARCH_PLAN'",
            (parent["id"],),
        )
    for row in db.rows("SELECT * FROM research_review_pairs WHERE study_id=%s ORDER BY pair", (study,)):
        assert digest(row["basis"]) == row["sha256"]
        for arm in row["basis"]["arm_order"]:
            if db.rows(
                "SELECT 1 FROM research_review_selections WHERE study_id=%s AND pair=%s AND arm=%s",
                (study, row["pair"], arm),
            ):
                continue
            # Identical presentation, model, context and sampling seed in both arms.
            payload = mechanism.recoverable_review(
                db, artifacts, campaign, header, row, header["profile"], arm, "base", 1729, count=2
            )
            with db.pool.connection() as c:
                c.execute(
                    "INSERT INTO research_review_selections(study_id,pair,arm,payload) VALUES(%s,%s,%s,%s)",
                    (study, row["pair"], arm, Jsonb(payload)),
                )
            print(json.dumps({"pool": row["pair"], "arm": arm, "valid": payload["valid"]}), flush=True)


def evaluate(db, artifacts, study):
    locked = db.rows("SELECT count(*) AS n FROM research_review_selections WHERE study_id=%s", (study,))[0][
        "n"
    ]
    assert locked == 48
    header = db.rows("SELECT protocol FROM research_review_studies WHERE id=%s", (study,))[0]["protocol"]
    require_frozen(header)
    snapshot = json.loads(
        artifacts.read(
            db.rows("SELECT artifact FROM datasets WHERE id=%s", (header["source_dataset"],))[0]["artifact"]
        )
    )
    parent_business = measure(
        decode(artifacts.read(header["parent_scores"]))["rows"], snapshot, header["validation"]
    )
    planner = Worker(db, artifacts, role="planning", worker_id="selection-effect-finalize")

    def finish_study_planning():
        while db.rows(
            """SELECT 1 FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id
            JOIN research_campaigns r ON r.id=n.campaign_id
            WHERE r.config->'study_source'->>'id'=%s AND j.kind='RESEARCH_PLAN'
            AND j.state IN ('READY','RUNNING') LIMIT 1""",
            (study,),
        ):
            if not planner.once():
                time.sleep(1)

    finish_study_planning()
    for row in db.rows("SELECT * FROM research_review_pairs WHERE study_id=%s ORDER BY pair", (study,)):
        for i, spec in enumerate(row["basis"]["offered"]):
            identity = digest(spec)
            if db.rows(
                "SELECT 1 FROM research_review_evaluations WHERE study_id=%s AND spec_digest=%s",
                (study, identity),
            ):
                continue
            name = study + f"-eval-{row['pair']:02d}-{i}"
            Research(db, artifacts).create(
                name,
                root_spec=spec,
                max_nodes=2,
                recovery_source={"purpose": "FROZEN144_EVALUATION"},
                recovery_dataset=header["source_dataset"],
                recovery_protocol=header["validation"],
                study_source={"id": study, "pair": row["pair"], "candidate": i},
            )
            node = compute(db, artifacts, name)
            child_business = measure(
                decode(artifacts.read(node["evaluation"]["scores"]))["rows"], snapshot, header["validation"]
            )
            decision = review(parent_business, child_business, header["validation"])
            deltas = decision["business"]["paired_windows"]
            reward = sum(deltas["recent"].values()) - sum(
                max(-v, 0) for w in deltas.values() for v in w.values()
            )
            payload = {
                "spec": spec,
                "business": node["evaluation"]["business"],
                "decision": decision,
                "reward": reward,
                "execution": node["evaluation"]["execution"],
                "evidence": node["evaluation"],
            }
            with db.pool.connection() as c:
                c.execute(
                    "INSERT INTO research_review_evaluations(study_id,spec_digest,node_id,payload) VALUES(%s,%s,%s,%s)",
                    (study, identity, node["id"], Jsonb(payload)),
                )
            finish_study_planning()
            print(
                json.dumps(
                    {"pool": row["pair"], "candidate": i, "reward": reward, "verdict": decision["verdict"]}
                ),
                flush=True,
            )


def collect(db, artifacts, study):
    header = db.rows("SELECT protocol FROM research_review_studies WHERE id=%s", (study,))[0]["protocol"]
    require_frozen(header)
    outcomes = {
        r["spec_digest"]: r["payload"]
        for r in db.rows("SELECT * FROM research_review_evaluations WHERE study_id=%s", (study,))
    }
    assert len(outcomes) == 144
    rows = db.rows("SELECT * FROM research_review_selections WHERE study_id=%s", (study,))
    assert len(rows) == 48
    progress = db.rows(
        """SELECT coalesce(sum((m.payload->>'new_origins')::bigint),0) AS origins,
        coalesce(sum((m.payload->>'gradient_steps')::bigint),0) AS steps
        FROM research_memory_events m WHERE m.kind='FIT_PROGRESS' AND m.node_id IN
        (SELECT node_id FROM research_review_evaluations WHERE study_id=%s)""",
        (study,),
    )[0]
    chosen = {}
    arm_valid = {}
    rewards = {}
    promotion = {}
    valid = True
    for r in rows:
        p = r["payload"]
        valid = valid and p["valid"]
        arm_valid[r["pair"], r["arm"]] = p["valid"]
        ids = [digest(s) for s in p.get("selected_specs", [])]
        chosen[r["pair"], r["arm"]] = ids
        rewards[r["pair"], r["arm"]] = sum(outcomes[k]["reward"] for k in ids) / 2 if p["valid"] else None
        promotion[r["pair"], r["arm"]] = (
            sum(outcomes[k]["decision"]["verdict"] == "ACCEPT_IMPROVEMENT" for k in ids) / 2
            if p["valid"]
            else None
        )
    comparison = {"feedback_better_in_this_study": False, "reason": "INVALID_ARM"}
    if valid:
        differences = np.asarray([rewards[i, "feedback"] - rewards[i, "no_feedback"] for i in range(24)])
        # Mean of two rewards, each a .01-rate lattice: multiply by200 exactly.
        ticks = np.rint(differences * 200).astype(int)
        assert np.allclose(ticks / 200, differences, atol=1e-10, rtol=0)
        counts = Counter({0: 1})
        for x in ticks:
            nxt = Counter()
            for value, n in counts.items():
                nxt[value + int(x)] += n
                nxt[value - int(x)] += n
            counts = nxt
        pvalue = sum(n for total, n in counts.items() if total >= int(ticks.sum())) / 2**24
        boot = np.random.default_rng(SEED).choice(differences, (10000, 24), replace=True).mean(1)
        comparison = {
            "primary_paired_difference": float(differences.mean()),
            "primary_interval95": np.quantile(boot, [0.025, 0.975]).tolist(),
            "paired_reward_differences": differences.tolist(),
            "one_sided_exact_p": pvalue,
            "feedback_better_in_this_study": bool(differences.mean() > 0 and pvalue <= 0.05),
            "secondary_promotion_rates": {
                arm: sum(promotion[i, arm] for i in range(24)) / 24 for arm in ("feedback", "no_feedback")
            },
        }
    result = {
        "kind": "SELECTION_EFFECT_24_V4",
        "study": study,
        "pairs": 24,
        "candidates_evaluated": 144,
        "historical_origins": 14400,
        "unique_draw_labels": 100,
        "valid_all_arms": valid,
        "invalid_arms": sum(not v for v in arm_valid.values()),
        "identical_pair_choices": sum(
            arm_valid[i, "feedback"]
            and arm_valid[i, "no_feedback"]
            and set(chosen[i, "feedback"]) == set(chosen[i, "no_feedback"])
            for i in range(24)
        ),
        "fresh_origin_fits": progress["origins"],
        "historical_origin_gradient_steps": progress["steps"],
        "gradient_steps_last_successful_attempt_only": sum(
            o["execution"]["gradient_steps_executed_this_attempt"] for o in outcomes.values()
        ),
        "execution_count_scope": "UNIQUE_COMMITTED_ORIGIN_PREFIXES_ACROSS_ALL_RESUMED_ATTEMPTS;ANCHOR_STEPS_SEPARATE",
        "comparison": comparison,
        "scope": "DEVELOPMENT_ONLY;NOT_FORWARD",
    }
    with db.pool.connection() as c:
        c.execute(
            "INSERT INTO research_review_results(study_id,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (study, Jsonb(result)),
        )
    (artifacts.root / (study + "-result.json")).write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "choose", "evaluate", "collect"])
    parser.add_argument("--study", required=True)
    parser.add_argument("--mechanism-study")
    args = parser.parse_args()
    s = Settings.from_env()
    if (
        conninfo_to_dict(s.database_url).get("dbname") != "dehps_next_parent_acceptance"
        or s.runtime.name != "parent-case"
    ):
        raise SystemExit("Refusing anything except the named isolated Next acceptance clone/runtime")
    if not args.study or len(args.study) > 50:
        raise SystemExit("Study ID must contain1..50 characters")
    db = Database(s)
    a = Artifacts(s, db)
    db.migrate()
    try:
        if args.phase == "prepare":
            if not args.mechanism_study:
                raise SystemExit("A completed passing mechanism study is required")
            prepare(db, a, args.study, args.mechanism_study)
        else:
            globals()[args.phase](db, a, args.study)
    finally:
        close_origin_pool()
        db.close()


if __name__ == "__main__":
    main()
