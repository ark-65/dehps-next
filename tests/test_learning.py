import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
import torch
from conftest import draws
from fastapi.testclient import TestClient
from psycopg.errors import RaiseException

from dehps_next.api import create_app
from dehps_next.domain import now, timestamp, top_red_combinations, validate_draw
from dehps_next.errors import DomainError, LeaseLost
from dehps_next.model import Recipe, load_torch, train
from dehps_next.pipeline import Pipeline
from dehps_next.scheduler import Scheduler
from dehps_next.status import get_status
from dehps_next.worker import Worker


def make_loop(system, count=23, mode="REPLAY", epochs=2):
    db, artifacts, ingest = system
    ingest(draws(count))
    scheduler = Scheduler(db, artifacts)
    scheduler.create_loop("test", mode, 20, Recipe(window=4, hidden=16, epochs=epochs), 10)
    return scheduler


def advance(worker, count):
    for _ in range(count):
        assert worker.once()


def test_replay_consumes_new_label_and_automatically_runs_next(system):
    db, artifacts, _ = system
    make_loop(system)
    worker = Worker(db, artifacts, "test-worker")
    advance(worker, 9)  # three cycles, each TRAIN -> SEAL -> EVALUATE
    assert worker.once()  # learn the final newly observed label without inventing a forecast
    assert not worker.once()
    assert db.rows("SELECT state FROM loops")[0]["state"] == "WAITING_FOR_DATA"
    models = db.rows(
        "SELECT m.*,cy.issue,cy.purpose FROM models m JOIN cycles cy ON cy.id=m.cycle_id ORDER BY cy.draw_at,cy.created_at"
    )
    assert len(models) == 4
    assert models[1]["parent_id"] == models[0]["id"]
    for m in models:
        assert m["manifest"]["initial_weight_digest"] != m["manifest"]["weight_digest"]
        if m["purpose"] == "PREDICT":
            assert m["issue"] not in m["manifest"]["label_issues"]
        assert m["manifest"]["gradient_steps"] == 2
    new = db.rows("SELECT * FROM consumptions WHERE model_id=%s AND newly_consumed", (models[1]["id"],))
    assert [r["issue"] for r in new] == [models[0]["issue"]]
    predictions = db.rows("SELECT * FROM predictions ORDER BY issue")
    for p in predictions:
        assert p["mode"] == "REPLAY"
        assert p["sealed_at"] > p["cutoff"]  # no fabricated historical sealing time
        assert len(p["payload"]["red_top100"]) == 100
        assert type(p["payload"]["blue_top1"]) is int
        assert len({tuple(c) for c in p["payload"]["red_top100"]}) == 100
    assert len(db.rows("SELECT * FROM evaluations")) == 3
    assert get_status(db, artifacts)["loops"][0]["blue_50_percent_evidence"] == "NOT_ESTABLISHED"


def test_new_ingest_resumes_waiting_loop_without_manual_job(system):
    db, artifacts, ingest = system
    make_loop(system, count=21)
    worker = Worker(db, artifacts)
    advance(worker, 4)
    assert not worker.once()
    ingest(draws(22)[-1:])
    advance(worker, 4)
    assert db.rows("SELECT count(*) AS n FROM evaluations")[0]["n"] == 2


def test_conflict_is_atomic_and_duplicates_are_idempotent(system):
    db, _, ingest = system
    records = draws(21)
    assert ingest(records)["inserted"] == 21
    assert ingest(records)["inserted"] == 0
    bad = dict(records[0], blue=16)
    with pytest.raises(DomainError, match="Conflicting"):
        ingest([draws(22)[-1], bad])
    assert db.rows("SELECT count(*) AS n FROM draws")[0]["n"] == 21


def test_snapshot_excludes_target_and_future_labels(system):
    db, artifacts, _ = system
    make_loop(system, count=30)
    Scheduler(db, artifacts).reconcile()
    ds = db.rows("SELECT * FROM datasets")[0]
    snapshot = json.loads(artifacts.read(ds["artifact"]))
    assert len(snapshot["rows"]) == 20
    assert snapshot["rows"][-1]["issue"] == "2020020"
    assert all(timestamp(r["available_at"]) <= timestamp(snapshot["cutoff"]) for r in snapshot["rows"])


def test_predictions_and_data_cannot_be_rewritten(system):
    db, artifacts, _ = system
    make_loop(system, count=21)
    advance(Worker(db, artifacts), 3)
    with pytest.raises(RaiseException, match="immutable"), db.pool.connection() as c:
        c.execute("UPDATE predictions SET payload='{}'")
    with pytest.raises(RaiseException, match="immutable"), db.pool.connection() as c:
        c.execute("DELETE FROM draws")


def test_claim_is_exclusive_and_expired_attempt_is_fenced(system):
    db, artifacts, _ = system
    scheduler = make_loop(system, count=21)
    scheduler.reconcile()
    with ThreadPoolExecutor(2) as executor:
        claims = list(executor.map(db.claim, ["one", "two"]))
    assert sum(j is not None for j in claims) == 1
    old = next(j for j in claims if j)
    with db.pool.connection() as c:
        c.execute("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (old["id"],))
    new = db.claim("replacement")
    assert new["token"] != old["token"]
    with pytest.raises(LeaseLost), db.pool.connection() as c, c.transaction():
        db.complete(c, old)
    assert db.rows("SELECT state FROM attempts WHERE id=%s", (old["token"],))[0]["state"] == "LOST"
    Pipeline(db, artifacts).execute(new, lambda: None)
    advance(Worker(db, artifacts), 2)
    assert db.rows("SELECT count(*) AS n FROM models")[0]["n"] == 1


def test_checkpoint_resume_produces_same_weights(system):
    db, artifacts, _ = system
    recipe = Recipe(window=4, hidden=16, epochs=10)
    scheduler = make_loop(system, count=21)
    scheduler.reconcile()
    ds = db.rows("SELECT * FROM datasets")[0]
    data = artifacts.read(ds["artifact"])
    checkpoints = []
    torch.set_num_threads(1)
    reference, expected = train(
        data, recipe, None, None, lambda b, e: checkpoints.append((b, e)), lambda: None
    )
    resumed, actual = train(data, recipe, None, checkpoints[0][0], lambda *_: None, lambda: None)
    assert actual["resumed_epoch"] == 5
    assert actual["weight_digest"] == expected["weight_digest"]
    assert all(
        torch.equal(v, load_torch(resumed)["model"][k]) for k, v in load_torch(reference)["model"].items()
    )


def test_storage_backpressure_and_symlink_rejection(system, tmp_path):
    db, artifacts, _ = system
    make_loop(system, count=21)
    artifacts.settings = replace(db.settings, quota_bytes=1)
    with pytest.raises(DomainError) as caught:
        Scheduler(db, artifacts).reconcile()
    assert caught.value.code == "STORAGE_QUOTA"
    assert not db.rows("SELECT * FROM jobs")
    (artifacts.root / "escape").symlink_to(tmp_path.parent)
    with pytest.raises(DomainError):
        artifacts.path("escape/outside")


def test_crashed_task_resumes_committed_checkpoint_after_lease_takeover(system, monkeypatch):
    db, artifacts, _ = system
    scheduler = make_loop(system, count=21, epochs=10)
    scheduler.reconcile()
    old = db.claim("crashing-worker")

    class PowerLoss(BaseException):
        pass

    def crashing_train(snapshot, recipe, parent, checkpoint, save, pulse):
        def save_then_crash(data, epoch):
            save(data, epoch)
            raise PowerLoss()

        return train(snapshot, recipe, parent, checkpoint, save_then_crash, pulse)

    monkeypatch.setattr("dehps_next.pipeline.train", crashing_train)
    with pytest.raises(PowerLoss):
        Pipeline(db, artifacts).execute(old, lambda: None)
    assert db.rows("SELECT checkpoint FROM jobs WHERE id=%s", (old["id"],))[0]["checkpoint"]
    with db.pool.connection() as c:
        c.execute("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (old["id"],))
    monkeypatch.setattr("dehps_next.pipeline.train", train)
    replacement = db.claim("recovery-worker")
    Pipeline(db, artifacts).execute(replacement, lambda: None)
    model = db.rows("SELECT manifest FROM models")[0]["manifest"]
    assert model["resumed_epoch"] == 5
    assert db.rows("SELECT state FROM attempts WHERE id=%s", (old["token"],))[0]["state"] == "LOST"
    assert db.rows("SELECT state FROM jobs WHERE id=%s", (old["id"],))[0]["state"] == "SUCCEEDED"


def test_no_retroactive_forward_seal(system, monkeypatch):
    db, artifacts, _ = system
    scheduler = make_loop(system, count=21, mode="FORWARD")
    scheduler.expect(
        "2020999", (now() + timedelta(hours=2)).isoformat(), (now() + timedelta(hours=1)).isoformat()
    )
    worker = Worker(db, artifacts)
    assert worker.once()  # train
    deadline = db.rows("SELECT deadline FROM targets WHERE issue='2020999'")[0]["deadline"]
    monkeypatch.setattr("dehps_next.pipeline.now", lambda: deadline + timedelta(seconds=1))
    job = db.claim("test")
    with pytest.raises(DomainError) as caught:
        Pipeline(db, artifacts).execute(job, lambda: None)
    assert caught.value.code == "MISSED_DEADLINE"
    assert not db.rows("SELECT * FROM predictions")


def test_api_is_readonly_authenticated_and_exposes_real_evidence(system):
    db, artifacts, _ = system
    make_loop(system, count=21)
    advance(Worker(db, artifacts), 3)
    with TestClient(create_app(db.settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.get("/status").status_code == 401
        headers = {"Authorization": "Bearer " + db.settings.api_token}
        response = client.get("/status", headers=headers)
        assert response.status_code == 200
        assert response.json()["models"] == 1
        assert client.post("/status", headers=headers).status_code == 405
        evidence = client.get("/evidence/test", headers=headers).json()
        assert evidence[0]["mode"] == "REPLAY"


def test_illegal_balls_and_top100_legality():
    with pytest.raises(DomainError):
        validate_draw(dict(draws(1)[0], red=[1, 1, 2, 3, 4, 5]))
    with pytest.raises(DomainError):
        validate_draw(dict(draws(1)[0], blue=True))
    combinations = top_red_combinations([0.2] * 33)
    assert len(combinations) == 100
    assert len({tuple(c) for c in combinations}) == 100
    assert all(len(set(c)) == 6 and c == sorted(c) and 1 <= min(c) < max(c) <= 33 for c in combinations)
