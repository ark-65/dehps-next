"""Resume the exact frozen calibration driver with a recoverable physical guard.

Only its pulse function is replaced. All recipe, seed, scoring, checkpoint and
frozen-driver hashing statements execute unchanged from the original file.
"""

import argparse
import ast
import hashlib
import json
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    driver = args.driver.resolve()
    receipt = args.receipt.resolve()
    root = Path("/app/runtime/blue-temporal")
    if not driver.is_relative_to(root) or not receipt.is_relative_to(root):
        raise SystemExit("Use the isolated Next blue-temporal runtime")
    source = driver.read_bytes()
    if hashlib.sha256(source).hexdigest() != args.sha256:
        raise SystemExit("Frozen driver digest mismatch")
    tree = ast.parse(source, filename=str(driver))
    pulses = [i for i, node in enumerate(tree.body) if isinstance(node, ast.FunctionDef) and node.name == "pulse"]
    if len(pulses) != 1:
        raise SystemExit("Expected exactly one frozen top-level pulse")
    boundary = pulses[0]
    scope = {"__name__": "__main__", "__file__": str(driver)}
    exec(compile(ast.Module(body=tree.body[:boundary], type_ignores=[]), str(driver), "exec"), scope)
    from dehps_next.domain import digest
    from dehps_next.errors import DomainError
    from psycopg.types.json import Jsonb

    db, study = scope["d"], scope["STUDY"]
    existing = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (study,))
    if existing:
        raise SystemExit("Frozen study already complete; do not rerun")
    counts = {
        "baseline": db.rows("SELECT spec_digest,payload FROM research_review_evaluations WHERE study_id=%s ORDER BY spec_digest", (study,)),
        "inner": db.rows("SELECT pair,basis,sha256 FROM research_review_pairs WHERE study_id=%s ORDER BY pair", (study,)),
    }
    amendment = {
        "kind": "OPERATIONAL_RECOVERY_ONLY",
        "study": study,
        "frozen_driver": args.sha256,
        "frozen_protocol": digest(scope["h"]),
        "runner": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rules": "replace pulse only; wait for fresh complete telemetry and original draw/resource guards; retain fence; reuse immutable completed origin records; no numerical or eligibility changes",
    }
    amendment_id = study + ":recovery:" + digest(amendment)[:16]
    with db.pool.connection() as c:
        c.execute("INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (amendment_id, Jsonb(amendment), digest(amendment)))
        assert c.execute("SELECT sha256 FROM research_review_studies WHERE id=%s", (amendment_id,)).fetchone()["sha256"] == digest(amendment)
    started = time.time()
    proof = {"amendment": amendment, "amendment_id": amendment_id, "started_at": started,
             "reused_baseline": len(counts["baseline"]), "reused_inner": len(counts["inner"]),
             "baseline_checkpoint_digest": digest(counts["baseline"]), "inner_checkpoint_digest": digest(counts["inner"])}

    def write(value):
        temporary = receipt.with_suffix(".pending")
        temporary.write_text(json.dumps({**proof, **value}, sort_keys=True) + "\n")
        temporary.replace(receipt)

    def pulse():
        held = False
        while True:
            scope["fence"].execute("SELECT 1")  # A lost DB session fails; never reacquire silently.
            with scope["primary"].pool.connection() as c:
                window = scope["status"](c)
            reason = "PAUSED_DRAW_WINDOW" if window["paused"] else None
            if reason is None:
                try:
                    reason = scope["Resources"](scope["primary"]).pressure()
                except DomainError as exc:
                    if exc.code != "HOST_TELEMETRY_UNAVAILABLE":
                        raise
                    reason = exc.code
            if reason is None:
                if held:
                    write({"state": "RUNNING", "resumed_at": time.time()})
                return
            held = True
            write({"state": "HOLD", "reason": reason, "observed_at": time.time()})
            time.sleep(5)

    scope["pulse"] = pulse
    write({"state": "RUNNING"})
    try:
        exec(compile(ast.Module(body=tree.body[boundary + 1 :], type_ignores=[]), str(driver), "exec"), scope)
    except Exception as exc:
        write({"state": "FAILED", "error": type(exc).__name__, "code": getattr(exc, "code", None)})
        raise
    write({"state": "COMPLETE", "finished_at": time.time(), "elapsed_seconds": time.time() - started})


if __name__ == "__main__":
    main()
