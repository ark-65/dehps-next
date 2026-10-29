import os
from datetime import UTC, datetime, timedelta

import pytest

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.data import DataService
from dehps_next.db import Database
from dehps_next.domain import canonical


def draws(count=30):
    start = datetime(2020, 1, 1, tzinfo=UTC)
    return [
        {
            "issue": f"2020{i + 1:03d}",
            "red": sorted({(i + j * 3) % 33 + 1 for j in range(6)}),
            "blue": i % 16 + 1,
            "draw_at": (start + timedelta(days=i)).isoformat(),
            "available_at": (start + timedelta(days=i, hours=23)).isoformat(),
        }
        for i in range(count)
    ]


@pytest.fixture
def system(tmp_path):
    dsn = os.environ.get("DEHPS_NEXT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Real isolated PostgreSQL test database is required")
    from psycopg.conninfo import conninfo_to_dict

    assert conninfo_to_dict(dsn)["dbname"].startswith("dehps_next_test"), "Never reset a non-test DB"
    settings = Settings(
        dsn,
        tmp_path,
        "test-token-abcdefghijklmnopqrstuvwxyz",
        threads=1,
        lease_seconds=5,
        poll_seconds=0.05,
        quota_bytes=64 * 1024 * 1024,
    )
    db = Database(settings)
    db.migrate()
    with db.pool.connection() as c:
        c.execute("""TRUNCATE worker_status,evaluations,predictions,consumptions,models,attempts,
            jobs,cycles,datasets,targets,loops,draws,sources CASCADE""")
    artifacts = Artifacts(settings)
    service = DataService(db, artifacts)

    def ingest(records):
        return service.ingest(
            records,
            source_url="synthetic://test-only",
            raw=canonical(records).encode(),
            provenance="SYNTHETIC_TEST_NOT_PREDICTIVE_EVIDENCE",
        )

    yield db, artifacts, ingest
    db.close()
