"""Frozen, isolated blue rank-correction study; never changes production parents."""

import argparse
import hashlib
import json
import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import torch
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from dehps_next.artifacts import Artifacts
from dehps_next.color_split import blue_spec
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest, timestamp
from dehps_next.errors import DomainError
from dehps_next.forecast import assess
from dehps_next.model import encode_torch, vectors
from dehps_next.release import numeric_identity
from dehps_next.research_compute import fit_prior
from dehps_next.research_hits import make_protocol, measure, public, review
from dehps_next.resources import Resources
from dehps_next.scores import decode
from dehps_next.training_window import status

ROOT = Path("/app/runtime/blue-residual")
STUDY = "blue-prequential-residual-v1-20261112"
ARMS = ("scalar", "aligned", "rotated", "frequency100", "uniform")


def softmax(x):
    y = np.exp(x - np.max(x))
    return y / y.sum()


def bias_fit(probabilities, labels, shift):
    bias = np.zeros(16, dtype=np.float64)
    initial = digest(bias.tolist())
    for probability, label in zip(probabilities, labels):
        predicted = softmax(np.log(probability) + bias)
        gradient = predicted + bias  # frozen L2 coefficient 1.0
        gradient[(int(label) + shift) % 16] -= 1
        bias -= 0.05 * gradient
        bias -= bias.mean()
    assert np.isfinite(bias).all() and digest(bias.tolist()) != initial
    return bias, {"initial": initial, "final": digest(bias.tolist()),
                  "bias": bias.tolist(), "steps": len(labels), "label_shift": shift}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    settings = Settings.from_env()
    primary = Database(replace(settings, database_url=make_conninfo(
        settings.database_url, options="-c default_transaction_read_only=on -c statement_timeout=8000")))
    db = Database(replace(settings, database_url=make_conninfo(
        settings.database_url, dbname="dehps_next_blue_temporal_20261110"),
        runtime=Path("/app/runtime/blue-temporal/application")))
    artifacts = Artifacts(db.settings, db)
    parent = json.loads((ROOT / "context/parent.json").read_text())

    def copied(ref):
        data = (ROOT / "context" / ref["sha256"]).read_bytes()
        assert len(data) == ref["bytes"] and hashlib.sha256(data).hexdigest() == ref["sha256"]
        return data

    assert numeric_identity() == parent["config"]["numeric_digest"]
    assert parent["config"]["numeric_threads"] == 1
    snapshot = json.loads(copied(parent["dataset_artifact"]))
    cached = decode(copied(parent["evaluation"]["scores"]))["rows"]
    copied(parent["evaluation"]["publication_anchor"])
    phases = {"earlier0": make_protocol(1625), "earlier1": make_protocol(1725),
              "current": parent["protocol"]}
    frozen = {
        "kind": "PAST_PREQUENTIAL_CLASS_RESIDUAL_V1", "parent": parent["id"],
        "parent_snapshot": digest(parent), "parent_spec": parent["spec"],
        "dataset": parent["dataset_artifact"], "scores": parent["evaluation"]["scores"],
        "numeric": numeric_identity(), "threads": 1, "seed": 1729,
        "phases": phases, "prior_scores": 64, "alphas": [.05, .1, .25, .5, .75, 1.0],
        "arms": list(ARMS), "candidate": "aligned", "learning_rate": .05,
        "l2": 1.0, "passes": 1, "label_rotation": 1,
        "update": "b=0; chronological64: b-=.05*(softmax(log(q_j)+b)-onehot(y_j)+b); center(b)",
        "scalar": "alpha minimizes prior64 genuine per-origin out-of-sample log loss; q=alpha*p+(1-alpha)/16",
        "prediction": "aligned/rotated: softmax(log(q_t)+b); frequency100=(prior100 counts+20/16)/120",
        "controls": "scalar preserves ranking; rotated trains with (label+1)%16; frequency100 omits neural scores; uniform is 1/16",
        "failure": "require original current100/50/10 joint hit promotion and probability eligibility; earlier two blocks each nonregressing and eligible; aligned must beat rotated current hits and current loss for mechanism support",
        "evidence": "PREDECLARED_HISTORICAL_REPLAY;DIAGNOSTIC_OLD_THIRD_BLOCK_NOT_VALIDATION;NO_PROTECTED_OR_FORWARD_CLAIM",
        "activation": "NONE; production parent and training continue independently",
        "driver": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    with db.pool.connection() as c:
        c.execute("INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                  (STUDY, Jsonb(frozen), digest(frozen)))
        assert c.execute("SELECT sha256 FROM research_review_studies WHERE id=%s", (STUDY,)).fetchone()["sha256"] == digest(frozen)
    (ROOT / "frozen.json").write_text(json.dumps(frozen, indent=2) + "\n")
    if args.freeze_only:
        print(json.dumps({"study": STUDY, "digest": digest(frozen), "state": "FROZEN"}))
        db.close()
        primary.close()
        return
    if db.rows("SELECT study_id FROM research_review_results WHERE study_id=%s", (STUDY,)):
        raise RuntimeError("STUDY_ALREADY_COMPLETE")
    fence = db.pool.getconn()
    assert fence.execute("SELECT pg_try_advisory_lock(740156) AS ok").fetchone()["ok"]

    def progress(**value):
        temporary = ROOT / "progress.pending"
        temporary.write_text(json.dumps(value) + "\n")
        temporary.replace(ROOT / "progress.json")

    def pulse():
        while True:
            fence.execute("SELECT 1")
            with primary.pool.connection() as c:
                window = status(c)
            reason = "PAUSED_DRAW_WINDOW" if window["paused"] else None
            if reason is None:
                try:
                    reason = Resources(primary).pressure()
                except DomainError as exc:
                    if exc.code != "HOST_TELEMETRY_UNAVAILABLE":
                        raise
                    reason = exc.code
            if reason is None:
                return
            progress(state="HOLD", reason=reason, at=time.time())
            time.sleep(5)

    matrix = vectors(snapshot["rows"])
    cache = {row["origin"]: row for row in cached}
    outer = {origin for protocol in phases.values() for origin in protocol["origins"]}
    required = {i for origin in outer for i in range(origin - 64, origin + 1)}
    saved = db.rows("SELECT payload FROM research_review_evaluations WHERE study_id=%s", (STUDY,))
    done = {r["payload"]["origin"]: r["payload"] for r in saved}
    for origin in sorted(required - set(cache)):
        if origin not in done:
            pulse()
            full = origin in outer
            spec = parent["spec"] if full else blue_spec(parent["spec"])
            red, blue, trained = fit_prior(matrix[:origin], spec, 1729 + origin, pulse)
            actual = snapshot["rows"][origin]
            target = np.zeros(33)
            target[np.array(actual["red"]) - 1] = 1
            row = {"origin": origin, "issue": actual["issue"],
                   "training_through": snapshot["rows"][origin - 1]["issue"],
                   "seed": 1729 + origin, "full_parent": full,
                   "blue_probabilities": blue.tolist(), "red_probabilities": red.tolist(),
                   "blue_log_loss": -math.log(blue[actual["blue"] - 1]),
                   "blue_hit": int(blue.argmax() + 1 == actual["blue"]),
                   "red_brier": float(np.square(red - target).mean()),
                   "parameter_updated": trained["weight_digest"] != trained["initial_weight_digest"],
                   "initial_weight_digest": trained["initial_weight_digest"],
                   "weight_digest": trained["weight_digest"],
                   "gradient_steps": trained["gradient_steps"],
                   "prior_prefix_digest": digest(snapshot["rows"][:origin]),
                   "spec": spec}
            assert row["parameter_updated"]
            if origin in (1624, 1724, 3425):
                row["anchor"] = artifacts.write(encode_torch(trained), category="blue-residual-20261112-anchors")
            with db.pool.connection() as c:
                c.execute("INSERT INTO research_review_evaluations(study_id,spec_digest,node_id,payload) VALUES(%s,%s,%s,%s)",
                          (STUDY, digest(["prior_fit", origin, frozen["parent_snapshot"]]),
                           "prequential-parent-" + str(origin), Jsonb(row)))
            done[origin] = row
        progress(state="RUNNING", phase="prior_fits", completed_fits=len(done), required_fits=len(required - set(cache)), origin=origin)
    lookup = {**done, **cache}
    evaluations = []
    for phase, protocol in phases.items():
        baseline = [lookup[i] for i in protocol["origins"]]
        base_hits = measure(baseline, snapshot, protocol)
        baseline_guard = assess(baseline, protocol, {"verdict": "ACCEPT_BASELINE"}, snapshot)
        candidates = {arm: [] for arm in ARMS}
        proofs = []
        for row in baseline:
            pulse()
            origin = row["origin"]
            prior = [lookup[j] for j in range(origin - 64, origin)]
            labels = np.array([snapshot["rows"][r["origin"]]["blue"] - 1 for r in prior])
            for past in prior:
                assert timestamp(snapshot["rows"][past["origin"]]["available_at"]) < timestamp(snapshot["rows"][origin]["draw_at"])
            probabilities = np.array([r["blue_probabilities"] for r in prior])
            losses = [float(-np.log((alpha * probabilities + (1 - alpha) / 16)[np.arange(64), labels]).mean())
                      for alpha in frozen["alphas"]]
            alpha = frozen["alphas"][int(np.argmin(losses))]
            past_q = alpha * probabilities + (1 - alpha) / 16
            q = alpha * np.array(row["blue_probabilities"]) + (1 - alpha) / 16
            aligned, aligned_proof = bias_fit(past_q, labels, 0)
            rotated, rotated_proof = bias_fit(past_q, labels, 1)
            frequency = (matrix[origin - 100:origin, 33:].sum(0).astype(np.float64) + 20 / 16) / 120
            choices = {"scalar": q, "aligned": softmax(np.log(q) + aligned),
                       "rotated": softmax(np.log(q) + rotated), "frequency100": frequency,
                       "uniform": np.ones(16) / 16}
            proof = {"origin": origin, "prior_origins": list(range(origin - 64, origin)),
                     "prior_score_digest": digest(prior), "prior_labels_digest": digest(labels.tolist()),
                     "alpha": alpha, "alpha_losses": losses,
                     "aligned": aligned_proof, "rotated": rotated_proof,
                     "outer_label_used_in_fit": False}
            with db.pool.connection() as c:
                c.execute("INSERT INTO research_review_pairs(study_id,pair,basis,sha256) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                          (STUDY, origin, Jsonb(proof), digest(proof)))
                assert c.execute("SELECT sha256 FROM research_review_pairs WHERE study_id=%s AND pair=%s", (STUDY, origin)).fetchone()["sha256"] == digest(proof)
                for arm, probability in choices.items():
                    target = snapshot["rows"][origin]["blue"] - 1
                    changed = {**row, "blue_probabilities": probability.tolist(),
                               "blue_log_loss": -math.log(probability[target]),
                               "blue_hit": int(probability.argmax() == target)}
                    assert changed["red_probabilities"] == row["red_probabilities"]
                    if arm == "scalar":
                        assert changed["blue_hit"] == row["blue_hit"]
                    c.execute("INSERT INTO research_review_selections(study_id,pair,arm,payload) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                              (STUDY, origin, arm, Jsonb(changed)))
                    old = c.execute("SELECT payload FROM research_review_selections WHERE study_id=%s AND pair=%s AND arm=%s", (STUDY, origin, arm)).fetchone()["payload"]
                    assert old == changed
                    candidates[arm].append(changed)
            proofs.append(proof)
        arms = {}
        for arm, rows in candidates.items():
            hits = measure(rows, snapshot, protocol)
            decision = review(base_hits, hits, protocol)
            guard = assess(rows, protocol, {"verdict": "ACCEPT_BASELINE"}, snapshot)
            arms[arm] = {"hits": public(hits), "decision": decision, "probability_guard": guard,
                         "top1_changes": sum(np.argmax(a["blue_probabilities"]) != np.argmax(b["blue_probabilities"]) for a, b in zip(baseline, rows)),
                         "paired_loss_delta": float(np.mean([b["blue_log_loss"] - a["blue_log_loss"] for a, b in zip(baseline, rows)]))}
            arms[arm]["top1_changes"] = int(arms[arm]["top1_changes"])
        evaluations.append({"phase": phase, "parent": {"hits": public(base_hits), "guard": baseline_guard},
                            "arms": arms, "proof_digest": digest(proofs)})
        progress(state="RUNNING", phase=phase, completed_outer_origins=len(evaluations) * 100)
    current = evaluations[-1]["arms"]
    candidate = current["aligned"]
    historical_ok = all(e["arms"]["aligned"]["probability_guard"]["eligible"] and
                        e["arms"]["aligned"]["decision"]["business"]["non_regression_all_windows"]
                        for e in evaluations[:-1])
    mechanism = (candidate["hits"]["windows"]["recent"]["blue_hits"] > current["rotated"]["hits"]["windows"]["recent"]["blue_hits"] and
                 candidate["probability_guard"]["windows"]["recent"]["blue_log_loss"] < current["rotated"]["probability_guard"]["windows"]["recent"]["blue_log_loss"])
    success = (candidate["decision"]["verdict"] == "ACCEPT_IMPROVEMENT" and
               candidate["probability_guard"]["eligible"] and historical_ok and mechanism)
    result = {"study": STUDY, "complete": True, "frozen_digest": digest(frozen),
              "evaluations": evaluations, "candidate_validated": success,
              "mechanism_support": mechanism, "historical_replications_passed": historical_ok,
              "production_activated": False, "cached_parent_origins": len(cache),
              "new_prior_fits": len(done), "new_prior_gradient_steps": sum(r["gradient_steps"] for r in done.values()),
              "new_bias_models": 600, "new_bias_steps": 38400,
              "unique_outer_origins": len(outer), "evidence": frozen["evidence"]}
    with db.pool.connection() as c:
        c.execute("INSERT INTO research_review_results(study_id,payload) VALUES(%s,%s)", (STUDY, Jsonb(result)))
    (ROOT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    progress(state="COMPLETE", candidate_validated=success, activated=False)
    db.pool.putconn(fence)
    db.close()
    primary.close()


if __name__ == "__main__":
    main()
