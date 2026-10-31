"""Frozen paired local-Qwen feedback study, only in a separately provisioned Next clone."""

import argparse
import hashlib
import itertools
import json
import random
import threading
import time
from pathlib import Path

import numpy as np
from psycopg import Error as DatabaseError
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest, now
from dehps_next.errors import DomainError
from dehps_next.release import code_identity, numeric_identity
from dehps_next.research import Research
from dehps_next.research_agent import request_json
from dehps_next.research_compute import close_origin_pool
from dehps_next.research_hits import measure, review
from dehps_next.research_memory import untried_specs
from dehps_next.research_review import cross_round_feedback, select
from dehps_next.resources import Resources
from dehps_next.scores import decode
from dehps_next.worker import Worker

STUDY = "feedback-paired-12-v2"
PARENT = STUDY + "-parent"
SEED = 43107


def parent(db):
    node = db.rows("SELECT * FROM research_nodes WHERE campaign_id=%s", (PARENT,))[0]
    campaign = db.rows("SELECT * FROM research_campaigns WHERE id=%s", (PARENT,))[0]
    return node, campaign


def compute(db, artifacts, campaign):
    worker = Worker(db, artifacts, role="compute", worker_id="feedback-study-compute")
    while True:
        node = db.rows("SELECT * FROM research_nodes WHERE campaign_id=%s", (campaign,))[0]
        if node["evaluation"]:
            return node
        if not worker.once():
            time.sleep(1)


def prepare(db, artifacts):
    if db.rows("SELECT 1 FROM research_review_studies WHERE id=%s", (STUDY,)):
        print("Existing frozen protocol preserved")
        return
    with db.pool.connection() as c, c.transaction():
        c.execute("UPDATE research_programs SET state='DISABLED'")
        c.execute("UPDATE jobs SET state='SNAPSHOT_EXCLUDED' WHERE state IN ('READY','RUNNING')")
        c.execute("UPDATE resource_reservations SET state='SNAPSHOT_EXCLUDED' WHERE state='ACTIVE'")
    original = json.loads((artifacts.root / "frozen-parent.json").read_text())
    Research(db, artifacts).create(
        PARENT,
        root_spec=original["spec"],
        planner="local",
        max_nodes=8,
        study_source={"id": STUDY, "purpose": "PAIRED_REVIEW_PARENT"},
    )
    node = compute(db, artifacts, PARENT)
    assert node["evaluation"]["business"] == original["evaluation"]["business"]
    _, campaign = parent(db)
    memory = cross_round_feedback(db, campaign, node)
    assert len(memory["evidence"]) >= 3 and memory["trials"] > 0
    base = node["spec"]
    local = []
    for field, values in {
        "learning_rate": [round(base["learning_rate"] * 2 ** (i / 8), 8) for i in range(-24, 25) if i],
        "weight_decay": [round(i * 0.003, 6) for i in range(1, 34)],
        "epochs": list(range(8, 101, 4)),
    }.items():
        local.extend({**base, field: value} for value in values if value != base[field])
    broad = []
    for method, window, history in itertools.product(
        ("fft", "newton"), (8, 16, 24, 32, 40, 48, 56, 64), (256, 512, 768)
    ):
        broad.append({**base, "method": method, "window": window, "train_history": history})
    local = untried_specs(db, campaign["dataset_id"], local)
    broad = untried_specs(db, campaign["dataset_id"], broad)
    rng = random.Random(SEED)
    rng.shuffle(local)
    rng.shuffle(broad)
    assert len(local) >= 36 and len(broad) >= 36
    model = next(x for x in request_json("/api/tags")["models"] if x["name"] == "qwen3:1.7b")
    protocol = {
        "id": STUDY,
        "pairs": 12,
        "pool_size": 6,
        "choices_per_arm": 2,
        "seed": SEED,
        "source_dataset": campaign["dataset_id"],
        "validation": campaign["protocol"],
        "parent_spec": base,
        "parent_business": node["evaluation"]["business"],
        "model": model["digest"],
        "code": code_identity(),
        "numeric": numeric_identity(),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "primary": "mean unchanged promotion eligibility of two chosen candidates per pool",
        "secondary": "delta_red100+delta_blue100-minus-negative-deltas-in100/50/10",
        "inference": "same model,temperature0,seed1729,4096 context;AB/BA alternation",
        "analysis": "12 paired pool units;exact one-sided sign randomization;paired percentile bootstrap;no extension after outcomes",
        "invalid_review": "record as invalid;primary eligibility0;secondary reward unavailable;no outcome-driven retry",
        "scope": "DEVELOPMENT_ONLY;SAME100_DRAW_LABELS;NO_FORWARD_OR_ADAPTIVE_SEARCH_ADJUSTMENT",
    }
    with db.pool.connection() as c, c.transaction():
        c.execute(
            "INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s)",
            (STUDY, Jsonb(protocol), digest(protocol)),
        )
        for i in range(12):
            offered = local[i * 3 : i * 3 + 3] + broad[i * 3 : i * 3 + 3]
            assert len({digest(s) for s in offered}) == 6
            basis = {
                "offered": offered,
                "memory": memory,
                "arm_order": [True, False] if i % 2 == 0 else [False, True],
            }
            c.execute(
                "INSERT INTO research_review_pairs(study_id,pair,basis,sha256) VALUES(%s,%s,%s,%s)",
                (STUDY, i, Jsonb(basis), digest(basis)),
            )
    print(
        json.dumps(
            {
                "frozen_pairs": 12,
                "unique_untried_specs": 72,
                "feedback_trials": memory["trials"],
                "protocol_digest": digest(protocol),
            }
        )
    )


def choose(db, artifacts):
    node, campaign = parent(db)
    assert not db.rows("SELECT 1 FROM research_review_evaluations WHERE study_id=%s", (STUDY,))
    pairs = db.rows("SELECT * FROM research_review_pairs WHERE study_id=%s ORDER BY pair", (STUDY,))
    for row in pairs:
        choose_pair(db, artifacts, node, campaign, row)


def choose_pair(db, artifacts, node, campaign, row):
    if (
        db.rows(
            "SELECT count(*) AS n FROM research_review_selections WHERE study_id=%s AND pair=%s",
            (STUDY, row["pair"]),
        )[0]["n"]
        == 2
    ):
        return
    job = db.claim("feedback-paired-study", role="planning")
    while not job:
        time.sleep(5)
        job = db.claim("feedback-paired-study", role="planning")
    artifacts.reservation_token = job["token"]
    stopped = threading.Event()
    lost = []

    def heartbeat():
        while not stopped.wait(10):
            try:
                db.heartbeat(job)
            except (DatabaseError, DomainError, PoolTimeout, TimeoutError) as exc:
                lost.append(str(exc))
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    start = time.monotonic()

    def pulse():
        if lost:
            raise RuntimeError(lost)
        db.heartbeat(job)

    try:
        assert digest(row["basis"]) == row["sha256"]
        for feedback in row["basis"]["arm_order"]:
            arm = "feedback" if feedback else "no_feedback"
            if db.rows(
                "SELECT 1 FROM research_review_selections WHERE study_id=%s AND pair=%s AND arm=%s",
                (STUDY, row["pair"], arm),
            ):
                continue
            try:
                picks, receipt, proof = select(
                    db,
                    artifacts,
                    campaign,
                    job,
                    pulse,
                    node["spec"],
                    node["evaluation"]["business"],
                    row["basis"]["offered"],
                    row["basis"]["memory"],
                    with_feedback=feedback,
                )
                payload = {"valid": True, "picks": picks, "receipt": receipt, "proof": proof}
            except DomainError as exc:
                if exc.code != "INVALID_GROUNDED_REVIEW":
                    raise
                payload = {"valid": False, "error": exc.code, "details": str(exc)}
            with db.pool.connection() as c:
                c.execute(
                    "INSERT INTO research_review_selections VALUES(%s,%s,%s,%s,now())",
                    (STUDY, row["pair"], arm, Jsonb(payload)),
                )
            print(
                json.dumps(
                    {
                        "pair": row["pair"],
                        "arm": arm,
                        "valid": payload["valid"],
                        "choices": [x["candidate_id"] for x in payload.get("picks", [])],
                    }
                ),
                flush=True,
            )
        if row["pair"] == 11:
            assert (
                db.rows("SELECT count(*) AS n FROM research_review_selections WHERE study_id=%s", (STUDY,))[
                    0
                ]["n"]
                == 24
            )
            Research(db, artifacts).plan(job, Research(db, artifacts).context(job), pulse)
        else:
            db.defer(job, "YIELD_STUDY_PAIR", seconds=0)
    finally:
        stopped.set()
        thread.join(timeout=2)
        Resources(db).finish(job["token"], time.monotonic() - start, 0)
        artifacts.reservation_token = None


def evaluate(db, artifacts):
    assert (
        db.rows("SELECT count(*) AS n FROM research_review_selections WHERE study_id=%s", (STUDY,))[0]["n"]
        == 24
    )
    pairs = db.rows("SELECT * FROM research_review_pairs WHERE study_id=%s ORDER BY pair", (STUDY,))
    reference, campaign = parent(db)
    snapshot = json.loads(
        artifacts.read(
            db.rows("SELECT artifact FROM datasets WHERE id=%s", (campaign["dataset_id"],))[0]["artifact"]
        )
    )
    parent_business = measure(
        decode(artifacts.read(reference["evaluation"]["scores"]))["rows"], snapshot, campaign["protocol"]
    )
    planner = Worker(db, artifacts, role="planning")

    def drain_planning():
        while db.rows("SELECT 1 FROM jobs WHERE kind='RESEARCH_PLAN' AND state IN ('READY','RUNNING')"):
            if not planner.once():
                time.sleep(5)

    drain_planning()
    for pair in pairs:
        for index, spec in enumerate(pair["basis"]["offered"]):
            key = digest(spec)
            if db.rows(
                "SELECT 1 FROM research_review_evaluations WHERE study_id=%s AND spec_digest=%s", (STUDY, key)
            ):
                continue
            name = f"feedback-eval-{pair['pair']:02d}-{index}"
            existing = db.rows("SELECT config FROM research_campaigns WHERE id=%s", (name,))
            if existing:
                old = db.rows("SELECT spec FROM research_nodes WHERE campaign_id=%s", (name,))
                assert len(old) == 1 and old[0]["spec"] == spec
                assert existing[0]["config"]["study_source"]["id"] == STUDY
                assert existing[0]["config"]["code_digest"] == code_identity()
            else:
                Research(db, artifacts).create(
                    name,
                    root_spec=spec,
                    max_nodes=2,
                    study_source={
                        "id": STUDY,
                        "pair": pair["pair"],
                        "candidate": index,
                        "source": "FROZEN_BEFORE_OUTCOMES",
                    },
                )
            n = compute(db, artifacts, name)
            child = measure(
                decode(artifacts.read(n["evaluation"]["scores"]))["rows"], snapshot, campaign["protocol"]
            )
            decision = review(parent_business, child, campaign["protocol"])
            deltas = decision["business"]["paired_windows"]
            reward = sum(deltas["recent"].values()) - sum(
                max(-v, 0) for window in deltas.values() for v in window.values()
            )
            payload = {
                "spec": spec,
                "business": n["evaluation"]["business"],
                "decision": decision,
                "reward": reward,
                "execution": n["evaluation"]["execution"],
            }
            with db.pool.connection() as c:
                c.execute(
                    "INSERT INTO research_review_evaluations VALUES(%s,%s,%s,%s,now())",
                    (STUDY, key, n["id"], Jsonb(payload)),
                )
            # Explicit study completion never exposes an experiment as a recommendation.
            drain_planning()
            print(
                json.dumps(
                    {
                        "pair": pair["pair"],
                        "candidate": index,
                        "verdict": decision["verdict"],
                        "reward": reward,
                        "fresh_origins": payload["execution"]["origin_fits_executed_this_attempt"],
                    }
                ),
                flush=True,
            )
    close_origin_pool()


def collect(db, artifacts):
    outcomes = {
        r["spec_digest"]: r["payload"]
        for r in db.rows("SELECT * FROM research_review_evaluations WHERE study_id=%s", (STUDY,))
    }
    assert len(outcomes) == 72
    selections = db.rows(
        "SELECT * FROM research_review_selections WHERE study_id=%s ORDER BY pair,arm", (STUDY,)
    )
    scores = {}
    rewards = {}
    valid = {}
    chosen = {}
    for s in selections:
        p = s["payload"]
        ids = [digest(x["spec"]) for x in p.get("picks", [])]
        chosen[(s["pair"], s["arm"])] = ids
        scores[(s["pair"], s["arm"])] = (
            sum(outcomes[k]["decision"]["verdict"] == "ACCEPT_IMPROVEMENT" for k in ids) / 2
        )
        rewards[(s["pair"], s["arm"])] = sum(outcomes[k]["reward"] for k in ids) / 2 if p["valid"] else None
        valid[(s["pair"], s["arm"])] = p["valid"]
    differences = np.asarray([scores[(i, "feedback")] - scores[(i, "no_feedback")] for i in range(12)])
    signs = np.asarray(list(itertools.product((-1, 1), repeat=12)))
    pvalue = float(np.mean((signs * differences).mean(1) >= differences.mean() - 1e-12))
    rng = np.random.default_rng(SEED)
    boot = rng.choice(differences, (10000, 12), replace=True).mean(1)
    comparison = {
        "primary_paired_difference": float(differences.mean()),
        "primary_interval95": np.quantile(boot, [0.025, 0.975]).tolist(),
        "one_sided_exact_p": pvalue,
        "feedback_better_in_this_study": bool(differences.mean() > 0 and pvalue <= 0.05),
        "paired_reward_differences": [
            None
            if rewards[(i, "feedback")] is None or rewards[(i, "no_feedback")] is None
            else rewards[(i, "feedback")] - rewards[(i, "no_feedback")]
            for i in range(12)
        ],
    }
    report = {
        "study": STUDY,
        "protocol_digest": db.rows("SELECT sha256 FROM research_review_studies WHERE id=%s", (STUDY,))[0][
            "sha256"
        ],
        "collection_driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evaluation_code_digests": [
            r["code"]
            for r in db.rows(
                """SELECT DISTINCT config->>'code_digest' AS code FROM research_campaigns
                WHERE config->'study_source'->>'id'=%s AND id LIKE 'feedback-eval-%%'""",
                (STUDY,),
            )
        ],
        "numeric_digest": numeric_identity(),
        "at": now().isoformat(),
        "scope": "FROZEN_DEVELOPMENT_COMPARISON;12_POOL_PAIRS;100_DRAW_LABELS;NOT_FORWARD_OR_SEARCH_ADJUSTED",
        "pairs": 12,
        "candidates_evaluated": 72,
        "unique_draw_labels": 100,
        "valid_reviews": {a: sum(valid[(i, a)] for i in range(12)) for a in ("feedback", "no_feedback")},
        "promotion_rates": {
            a: sum(scores[(i, a)] for i in range(12)) / 12 for a in ("feedback", "no_feedback")
        },
        "mean_rewards": {
            a: float(np.mean([rewards[(i, a)] for i in range(12) if rewards[(i, a)] is not None]))
            for a in ("feedback", "no_feedback")
        },
        "identical_pair_choices": sum(
            set(chosen[(i, "feedback")]) == set(chosen[(i, "no_feedback")]) for i in range(12)
        ),
        "fresh_origins": sum(o["execution"]["origin_fits_executed_this_attempt"] for o in outcomes.values()),
        "actual_gradient_steps": sum(
            o["execution"]["gradient_steps_executed_this_attempt"] for o in outcomes.values()
        ),
        "comparison": comparison,
        "mail_attempts_created_during_study": db.rows(
            """SELECT count(*) AS n FROM mail_attempts WHERE started_at>=
            (SELECT created_at FROM research_review_studies WHERE id=%s)""",
            (STUDY,),
        )[0]["n"],
    }
    with db.pool.connection() as c:
        c.execute(
            "INSERT INTO research_review_results(study_id,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (STUDY, Jsonb(report)),
        )
    (artifacts.root / "feedback-study-result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


def main():
    args = argparse.ArgumentParser()
    args.add_argument("phase", choices=["prepare", "choose", "evaluate", "collect"])
    command = args.parse_args().phase
    s = Settings.from_env()
    assert conninfo_to_dict(s.database_url)["dbname"].startswith("dehps_next_feedback_")
    assert s.runtime.name == "feedback-case"
    db = Database(s)
    artifacts = Artifacts(s, db)
    db.migrate()
    try:
        globals()[command](db, artifacts)
    finally:
        close_origin_pool()
        db.close()


if __name__ == "__main__":
    main()
