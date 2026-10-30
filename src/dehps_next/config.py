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
    inference_threads: int = 12
    inference_busy_threads: int = 4
    cpu_pool: str = "0-19"
    inference_backend: str = "cpu"
    origin_processes: int = 1
    research_agent: str = "legacy"
    research_pipeline_depth: int = 1
    research_validation: str = "recent-random-v2"

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
            inference_threads=int(os.getenv("DEHPS_NEXT_INFERENCE_THREADS", "12")),
            inference_busy_threads=int(os.getenv("DEHPS_NEXT_INFERENCE_BUSY_THREADS", "4")),
            cpu_pool=os.getenv("DEHPS_NEXT_CPU_POOL", "0-19"),
            inference_backend=os.getenv("DEHPS_NEXT_INFERENCE_BACKEND", "cpu"),
            origin_processes=int(os.getenv("DEHPS_NEXT_ORIGIN_PROCESSES", "1")),
            research_agent=os.getenv("DEHPS_NEXT_RESEARCH_AGENT", "legacy"),
            research_pipeline_depth=int(os.getenv("DEHPS_NEXT_RESEARCH_PIPELINE_DEPTH", "1")),
            research_validation=os.getenv("DEHPS_NEXT_RESEARCH_VALIDATION", "recent-random-v2"),
        )
        if result.research_validation not in ("recent-random-v2", "recent-windows-v4"):
            raise ValueError("Unknown frozen validation policy")
        if result.research_agent not in ("legacy", "candidates-v2"):
            raise ValueError("Unknown research proposal policy")
        if result.research_pipeline_depth not in (1, 2):
            raise ValueError("Research queue must have depth1 or2")
        if result.research_agent == "legacy" and result.research_pipeline_depth != 1:
            raise ValueError("The legacy controller supports serial planning only")
        if not 1 <= result.origin_processes <= 8:
            raise ValueError("Expected1..8 isolated origin fitters")
        if result.origin_processes > 1 and result.training_threads not in (1, 2, 4, 8):
            raise ValueError("Parallel origin fitters require an audited thread count")
        if result.inference_backend not in ("cpu", "vulkan"):
            raise ValueError("Invalid local inference backend")
        if result.cpu_pool != "0-19" or set(os.sched_getaffinity(0)) != set(range(20)):
            raise ValueError("Next must run in the registered CPU0-19 pool; reserve20-21 for the host")
        if any(
            os.getenv(k, "1") != "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
        ):
            raise ValueError("Use single BLAS/OMP defaults; predictor Torch threads are selected explicitly")
        if not 1 <= result.inference_busy_threads <= result.inference_threads <= 12:
            raise ValueError("Invalid local inference thread count")
        if not 1 <= result.training_threads <= 16:
            raise ValueError("Invalid training thread count")
        if not 1 <= result.threads <= 16 or not 5 <= result.lease_seconds <= 3600:
            raise ValueError("Invalid CPU or lease limits")
        if result.poll_seconds < 0.05 or result.quota_bytes < 32 * 1024 * 1024:
            raise ValueError("Invalid polling or storage limits")
        return result
