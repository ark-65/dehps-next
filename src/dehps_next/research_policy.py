"""A small, genuinely trained direction-value network on bounded development feedback."""

import math

import torch
from psycopg.types.json import Jsonb
from torch import nn

from .domain import digest
from .model import encode_torch, load_torch, weight_digest

METHODS = ("raw", "fft", "ridge", "newton")


def features(spec, parent_summary):
    return [float(spec["method"] == m) for m in METHODS] + [
        spec["window"] / 64,
        spec["hidden"] / 256,
        spec["epochs"] / 200,
        math.log10(spec["learning_rate"]) / 10,
        spec["weight_decay"],
        spec["train_history"] / 1024,
        parent_summary["blue_log_loss"] / 5,
        parent_summary["red_brier"],
    ]


def train_policy(db, artifacts, campaign, job):
    from .release import numeric_identity

    contract = digest(
        [
            campaign["dataset_id"],
            campaign["protocol"]["digest"],
            numeric_identity(),
            campaign["config"]["numeric_threads"],
        ]
    )
    records = db.rows(
        """SELECT node_id,spec,payload-'period_outcomes'-'origin_provenance' AS payload FROM research_memory_events WHERE contract=%s
        AND kind='EVALUATION' AND parent_id IS NOT NULL
        AND payload->'parent_summary' IS NOT NULL ORDER BY seq DESC LIMIT 128""",
        (contract,),
    )
    examples = [
        {
            "id": r["node_id"],
            "spec": r["spec"],
            "evaluation": {"summary": r["payload"]["summary"], "business": r["payload"]["business"]},
            "parent_evaluation": {
                "summary": r["payload"]["parent_summary"],
                "business": r["payload"]["decision"].get("business", {}).get("parent"),
            },
        }
        for r in records
    ]
    examples.reverse()
    torch.manual_seed(1729)
    model = nn.Sequential(nn.Linear(12, 16), nn.Tanh(), nn.Linear(16, 1))
    previous = db.rows(
        "SELECT artifact FROM research_policy_versions WHERE metrics->>'feedback_contract'=%s ORDER BY id DESC LIMIT 1",
        (contract,),
    )
    if previous:
        model.load_state_dict(load_torch(artifacts.read(previous[0]["artifact"]))["model"])
    before = weight_digest(model)
    metrics = {
        "feedback_contract": contract,
        "seed": 1729,
        "parent_policy": previous[0]["artifact"] if previous else None,
        "examples": len(examples),
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "initial_weight_digest": before,
        "evidence": "DEVELOPMENT_FEEDBACK_ONLY",
        "generalization": "NOT_ESTABLISHED",
        "steps": 0,
        "replay_capacity": 128,
    }
    if examples:
        x = torch.tensor([features(e["spec"], e["parent_evaluation"]["summary"]) for e in examples])
        targets = []
        for e in examples:
            parent, child = e["parent_evaluation"]["summary"], e["evaluation"]["summary"]
            if campaign["protocol"]["version"] == "recent100-tail50-tail10-hits-v4":
                p = e["parent_evaluation"]["business"]["windows"]
                c = e["evaluation"]["business"]["windows"]
                deltas = {
                    k: [c[k][m] - p[k][m] for m in ("red5_rate", "blue_rate")]
                    for k in ("recent", "recent50", "recent10")
                }
                reward = sum(deltas["recent"]) - sum(max(-v, 0) for values in deltas.values() for v in values)
                metrics["reward_contract"] = "incremental_paired_red5_blue_rates;penalize_nested_declines"
            else:
                reward = (
                    parent["blue_log_loss"]
                    - child["blue_log_loss"]
                    - 5 * max(child["red_brier"] - parent["red_brier"], 0)
                )
            targets.append(max(-5, min(5, reward)))
        y = torch.tensor(targets).reshape(-1, 1)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
        metrics["training_loss_before"] = float(nn.functional.mse_loss(model(x), y).detach())
        for _ in range(128):
            optimizer.zero_grad()
            loss = nn.functional.mse_loss(model(x), y)
            loss.backward()
            optimizer.step()
        metrics.update(steps=128, training_loss_after=float(nn.functional.mse_loss(model(x), y).detach()))
    metrics.update(
        weight_digest=weight_digest(model),
        parameters_updated=weight_digest(model) != before,
        example_digest=digest([e["id"] for e in examples]),
    )
    ref = artifacts.write(
        encode_torch({"model": model.state_dict(), "metrics": metrics}), category="research/policies"
    )
    with db.pool.connection() as c, c.transaction():
        db.fence(c, job)
        c.execute(
            "INSERT INTO research_policy_versions(campaign_id,artifact,example_count,metrics) VALUES(%s,%s,%s,%s)",
            (campaign["id"], Jsonb(ref), len(examples), Jsonb(metrics)),
        )

    def value(spec, parent_summary):
        with torch.no_grad():
            return float(model(torch.tensor(features(spec, parent_summary))).item())

    return value, {"artifact": ref, **metrics}
