"""Select validated research anchors at the final minute, without retraining or early sealing."""

import json
import math

from psycopg.types.json import Jsonb

from .calendar import ZONE
from .data import DataService
from .domain import digest, now, timestamp
from .errors import DomainError
from .model import historical_baseline, load_torch
from .release import code_identity
from .research_compute import predict_anchor
from .research_protocol import summary
from .scores import decode

LOOP = "mail-validated-forward"


def assess(rows, protocol, decision, snapshot=None):
    """Fixed replay guards; development eligibility is never a 50% capability declaration."""
    if protocol.get("version") != "recent100-tail10-random-v2" or len(protocol["recent"]) != 100:
        raise DomainError("OLD_VALIDATION_PROTOCOL", "Require frozen recent100/tail10 protocol")
    if digest({k: v for k, v in protocol.items() if k != "digest"}) != protocol["digest"]:
        raise DomainError("VALIDATION_PROTOCOL_CORRUPT", "Frozen protocol checksum differs")
    if snapshot is not None:
        for row in rows:
            origin = row["origin"]
            actual = snapshot["rows"][origin]
            prior = snapshot["rows"][origin - 1]
            if (
                row["issue"] != actual["issue"]
                or row["training_through"] != prior["issue"]
                or timestamp(prior["available_at"]) >= timestamp(actual["draw_at"])
            ):
                raise DomainError(
                    "VALIDATION_BOUNDARY_CHANGED", "Score origin does not match the legal prior prefix"
                )
            blue, red = row["blue_probabilities"], row["red_probabilities"]
            if (
                len(blue) != 16
                or len(red) != 33
                or not all(math.isfinite(v) and 0 < v < 1 for v in blue + red)
                or abs(sum(blue) - 1) > 1e-6
            ):
                raise DomainError("INVALID_VALIDATION_PROBABILITIES", "Invalid probability evidence")
            loss = -math.log(max(blue[actual["blue"] - 1], 1e-12))
            brier = sum((v - int(i + 1 in actual["red"])) ** 2 for i, v in enumerate(red)) / 33
            hit = int(blue.index(max(blue)) + 1 == actual["blue"])
            if (
                abs(loss - row["blue_log_loss"]) > 1e-6
                or abs(brier - row["red_brier"]) > 1e-6
                or hit != row["blue_hit"]
                or not row["parameter_updated"]
            ):
                raise DomainError(
                    "VALIDATION_SCORE_CHANGED", "Recomputed metrics differ from recorded evidence"
                )
    expected = set(protocol["origins"] + protocol["reserve"])
    if (
        not set(protocol["origins"]).issubset({r["origin"] for r in rows})
        or not {r["origin"] for r in rows}.issubset(expected)
        or len(rows) != len({r["origin"] for r in rows})
    ):
        raise DomainError("INCOMPLETE_VALIDATION", "Every frozen origin must have exactly one score")
    groups = {k: summary(rows, protocol[k]) for k in ("recent", "recent10", "random_historical")}
    # Same pre-registered tolerances for every candidate; ten points are a guard, not reliable proof.
    reasons = []
    if decision["verdict"] not in ("ACCEPT_BASELINE", "ACCEPT_IMPROVEMENT"):
        reasons.append("PARENT_REVIEW_NOT_ACCEPTED")
    for key, metrics in groups.items():
        tolerance = 0.10 if key == "recent10" else 0.02
        if metrics["blue_log_loss"] > math.log(16) + tolerance:
            reasons.append(key.upper() + "_BLUE_BASELINE_REGRESSION")
        if metrics["red_brier"] > (6 / 33) * (1 - 6 / 33) + 0.01:
            reasons.append(key.upper() + "_RED_BASELINE_REGRESSION")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "windows": groups,
        "uniform_blue_loss": math.log(16),
        "protocol_digest": protocol["digest"],
        "protocol": protocol,
        "parent_review": decision,
        "goal50": "UNPROVEN_DEVELOPMENT_REPLAY_CANNOT_ESTABLISH_FORWARD_CAPABILITY",
        "evidence": protocol["evidence"],
    }


class Forecast:
    def __init__(self, db, artifacts):
        self.db, self.artifacts = db, artifacts

    def candidates(self):
        latest = self.db.rows(
            "SELECT issue FROM effective_draws WHERE available_at<=now() AND observed_at<=now() ORDER BY draw_at DESC LIMIT 1"
        )[0]["issue"]
        found = self.db.rows(
            """SELECT n.*,r.dataset_id,r.config,r.protocol,ds.artifact AS data_artifact,ds.through_issue
            FROM research_campaigns r JOIN research_nodes n ON n.id=r.selected_node
            JOIN datasets ds ON ds.id=r.dataset_id
            WHERE r.config->>'code_digest'=%s AND ds.through_issue=%s
              AND r.protocol->>'version'='recent100-tail10-random-v2'
              AND n.anchor IS NOT NULL ORDER BY n.completed_at DESC LIMIT 64""",
            (code_identity(), latest),
        )
        candidates, snapshots = [], {}
        for node in found:
            rows = decode(self.artifacts.read(node["evaluation"]["scores"]))["rows"]
            if node["dataset_id"] not in snapshots:
                snapshots[node["dataset_id"]] = json.loads(self.artifacts.read(node["data_artifact"]))
            gate = assess(rows, node["protocol"], node["decision"], snapshots[node["dataset_id"]])
            candidates.append((node, gate))
        return sorted(
            candidates,
            key=lambda pair: (not pair[1]["eligible"], pair[1]["windows"]["recent"]["blue_log_loss"]),
        )

    def preview(self):
        candidates = self.candidates()
        return {
            "state": "ELIGIBLE_DEVELOPMENT"
            if candidates and candidates[0][1]["eligible"]
            else "NO_ELIGIBLE_CANDIDATE",
            "evaluated_candidates": len(candidates),
            "candidate": candidates[0][0]["id"] if candidates else None,
            "gate": candidates[0][1] if candidates else None,
            "sealed": False,
        }

    def for_report(self, target, missing_evidence):
        # Serialize the 17:00 report with the final sealing transaction. A seal that is
        # committing at the boundary must never be mistaken for a missing prediction.
        with self.db.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740142)")
            prediction = c.execute(
                """SELECT p.*,cy.dataset_id,ds.through_issue FROM forecast_selections s
                JOIN predictions p ON p.cycle_id=s.cycle_id JOIN cycles cy ON cy.id=p.cycle_id
                JOIN datasets ds ON ds.id=cy.dataset_id WHERE s.issue=%s""",
                (target["issue"],),
            ).fetchone()
            if prediction:
                return prediction
            c.execute(
                "INSERT INTO forecast_selections(issue,state,evidence) VALUES(%s,'MISSED',%s) ON CONFLICT DO NOTHING",
                (target["issue"], Jsonb(missing_evidence)),
            )
        return None

    def seal(self, target):
        clock = now().astimezone(ZONE)
        if not target["seal_time"] <= clock < target["mail_time"]:
            raise DomainError(
                "WAITING_FINAL_SEAL_WINDOW", "Only seal 16:59 <= Shanghai time < 17:00 on the draw day"
            )
        if self.db.rows("SELECT 1 FROM forecast_selections WHERE issue=%s", (target["issue"],)):
            return "ALREADY_DECIDED"
        candidates = self.candidates()
        if not candidates or not candidates[0][1]["eligible"]:
            return "WAITING_VALIDATED_CANDIDATE"
        node, gate = candidates[0]
        publication_ref = node["evaluation"]["publication_anchor"]
        anchor_bytes = self.artifacts.read(publication_ref)
        anchor = load_torch(anchor_bytes)
        snapshot = json.loads(self.artifacts.read(node["data_artifact"]))
        if any(
            timestamp(r["available_at"]) > now() or timestamp(r["draw_at"]) >= target["draw_time"]
            for r in snapshot["rows"]
        ):
            raise DomainError("FORECAST_DATA_BOUNDARY", "Anchor contains unavailable or target-period labels")
        prediction = predict_anchor(anchor_bytes, snapshot["rows"])
        baseline = historical_baseline(snapshot["rows"])
        # Formal copies remain rooted independently of eventual research-detail GC.
        model_ref = self.artifacts.write(anchor_bytes, category="models")
        score_ref = self.artifacts.write(
            self.artifacts.read(node["evaluation"]["scores"]), category="forecast-evidence"
        )
        evidence = {
            **gate,
            "candidate_node": node["id"],
            "path": node["path"],
            "spec": node["spec"],
            "code_digest": code_identity(),
            "dataset_id": node["dataset_id"],
            "scores": score_ref,
            "anchor_sha256": publication_ref["sha256"],
            "research_recovery_anchor_sha256": node["anchor"]["sha256"],
            "publication_training": node["evaluation"]["publication_training"],
            "supersedes_early_acceptance": True,
        }
        cycle = digest([LOOP, target["issue"]])
        with self.db.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740142)")
            if c.execute("SELECT 1 FROM forecast_selections WHERE issue=%s", (target["issue"],)).fetchone():
                return "ALREADY_DECIDED"
            if not target["seal_time"] <= now().astimezone(ZONE) < target["mail_time"]:
                raise DomainError("MISSED_FINAL_SEAL_WINDOW", "Do not publish after 17:00")
            latest = c.execute(
                "SELECT issue FROM effective_draws WHERE available_at<=now() AND observed_at<=now() ORDER BY draw_at DESC LIMIT 1"
            ).fetchone()
            if (
                latest["issue"] != node["through_issue"]
                or c.execute("SELECT 1 FROM draws WHERE issue=%s", (target["issue"],)).fetchone()
            ):
                raise DomainError(
                    "FORECAST_DATA_CHANGED", "Candidate no longer covers the current legal boundary"
                )
            cutoff = now()
            formal_data = DataService(self.db, self.artifacts).snapshot(
                c, cutoff=cutoff, target_draw_at=target["draw_time"], mode="FORWARD"
            )
            formal_snapshot = json.loads(self.artifacts.read(formal_data["artifact"]))
            if formal_snapshot["rows"] != snapshot["rows"]:
                raise DomainError(
                    "FORECAST_DATA_CHANGED", "Forward-observed rows differ from the validated anchor input"
                )
            config = {"code_digest": code_identity(), "externally_sealed": True}
            c.execute(
                "INSERT INTO loops(id,mode,config) VALUES(%s,'FORWARD',%s) ON CONFLICT DO NOTHING",
                (LOOP, Jsonb(config)),
            )
            c.execute(
                "INSERT INTO cycles(id,loop_id,issue,draw_at,cutoff,dataset_id,state,model_id) VALUES(%s,%s,%s,%s,%s,%s,'EVALUATE',%s)",
                (
                    cycle,
                    LOOP,
                    target["issue"],
                    target["draw_time"],
                    cutoff,
                    formal_data["id"],
                    model_ref["sha256"],
                ),
            )
            manifest = {
                "purpose": "VALIDATED_FORMAL_ANCHOR",
                "code_digest": code_identity(),
                "through_issue": node["through_issue"],
                "spec": node["spec"],
                "weight_digest": anchor["weight_digest"],
                "gradient_steps": anchor["gradient_steps"],
                "validation": evidence,
            }
            c.execute(
                "INSERT INTO models(id,cycle_id,dataset_id,artifact,manifest) VALUES(%s,%s,%s,%s,%s)",
                (model_ref["sha256"], cycle, formal_data["id"], Jsonb(model_ref), Jsonb(manifest)),
            )
            start = max(node["spec"]["window"], len(snapshot["rows"]) - node["spec"]["train_history"])
            # Newton's prior-only calibration tail is not counted as a neural gradient label.
            end = len(snapshot["rows"]) - (
                min(32, (len(snapshot["rows"]) - start) // 4) if node["spec"]["method"] == "newton" else 0
            )
            for row in snapshot["rows"][start:end]:
                c.execute(
                    "INSERT INTO consumptions VALUES(%s,%s,%s,true)",
                    (model_ref["sha256"], row["issue"], node["spec"]["epochs"]),
                )
            c.execute(
                "INSERT INTO predictions(cycle_id,model_id,issue,mode,cutoff,payload,payload_digest,baseline) VALUES(%s,%s,%s,'FORWARD',%s,%s,%s,%s)",
                (
                    cycle,
                    model_ref["sha256"],
                    target["issue"],
                    cutoff,
                    Jsonb(prediction),
                    digest(prediction),
                    Jsonb(baseline),
                ),
            )
            c.execute(
                "INSERT INTO forecast_selections(issue,cycle_id,state,evidence) VALUES(%s,%s,'SEALED_VALIDATED_DEVELOPMENT',%s)",
                (target["issue"], cycle, Jsonb(evidence)),
            )
        return "SEALED_VALIDATED_DEVELOPMENT"
