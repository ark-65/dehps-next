import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    runtime: Path
    api_token: str
    threads: int = 2
    poll_seconds: float = 2
    lease_seconds: int = 120
    quota_bytes: int = 256 * 1024 * 1024
    artifact_bytes: int = 16 * 1024 * 1024
    training_threads: int = 2

    @classmethod
    def from_env(cls):
        root = Path.cwd().resolve()
        project = tomllib.loads((root / "pyproject.toml").read_text())
        if project.get("project", {}).get("name") != "dehps-next":
            raise ValueError("Run inside the dehps-next repository")
        runtime = Path(os.getenv("DEHPS_NEXT_RUNTIME", str(root / "runtime"))).resolve()
        if not runtime.is_relative_to(root / "runtime"):
            raise ValueError("DEHPS_NEXT_RUNTIME must be inside this repository's runtime directory")
        dsn = os.environ["DEHPS_NEXT_DATABASE_URL"]
        from psycopg.conninfo import conninfo_to_dict

        dbname = conninfo_to_dict(dsn).get("dbname", "")
        if not dbname.startswith("dehps_next"):
            raise ValueError("Refusing a database outside the dehps_next namespace")
        result = cls(
            dsn,
            runtime,
            os.getenv("DEHPS_NEXT_API_TOKEN", ""),
            int(os.getenv("DEHPS_NEXT_THREADS", "2")),
            float(os.getenv("DEHPS_NEXT_POLL_SECONDS", "2")),
            int(os.getenv("DEHPS_NEXT_LEASE_SECONDS", "120")),
            int(os.getenv("DEHPS_NEXT_QUOTA_MIB", "1024")) * 1024 * 1024,
            training_threads=int(
                os.getenv("DEHPS_NEXT_TRAINING_THREADS", os.getenv("DEHPS_NEXT_THREADS", "2"))
            ),
        )
        if not 1 <= result.training_threads <= 8:
            raise ValueError("Invalid training thread count")
        if not 1 <= result.threads <= 8 or not 5 <= result.lease_seconds <= 3600:
            raise ValueError("Invalid CPU or lease limits")
        if result.poll_seconds < 0.05 or result.quota_bytes < 32 * 1024 * 1024:
            raise ValueError("Invalid polling or storage limits")
        return result
