"""Bounded real-history CPU calibration; run in the isolated Next development container."""

import concurrent.futures
import json
import multiprocessing
import time

import numpy as np
import torch

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.model import vectors
from dehps_next.research import ROOT_SPEC
from dehps_next.research_compute import fit_prior


def work(matrix, threads):
    torch.set_num_threads(threads)
    started = time.monotonic()
    cpu = time.process_time()
    hashes = []
    probabilities = []
    # Identical work and seeds for every concurrency configuration.
    for i in range(8):
        red, blue, payload = fit_prior(
            matrix, {**ROOT_SPEC, "method": ("raw", "fft", "ridge", "newton")[i % 4]}, 1729 + i, lambda: None
        )
        assert np.isfinite(red).all() and abs(float(blue.sum()) - 1) < 1e-5
        hashes.append(payload["weight_digest"])
        probabilities.append(np.concatenate([red, blue]).tolist())
    return {
        "seconds": time.monotonic() - started,
        "process_cpu_seconds": time.process_time() - cpu,
        "hashes": hashes,
        "probabilities": probabilities,
    }


def main():
    settings = Settings.from_env()
    db = Database(settings)
    artifacts = Artifacts(settings, db)
    row = db.rows("SELECT artifact FROM datasets ORDER BY sample_count DESC LIMIT 1")[0]
    # One existing Next snapshot, a bounded prior suffix for all fits.
    matrix = vectors(json.loads(artifacts.read(row["artifact"]))["rows"])[-512:]
    results = []
    reference = None
    start = time.monotonic()
    for processes, threads in ((1, 1), (1, 2), (1, 4), (1, 8), (2, 1), (2, 2), (4, 1), (4, 2)):
        if time.monotonic() - start > 120:
            break
        before = time.monotonic()
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=processes, mp_context=multiprocessing.get_context("spawn")
        ) as pool:
            tasks = [pool.submit(work, matrix, threads) for _ in range(4)]
            values = [f.result(timeout=60) for f in tasks]
        assert all(v["hashes"] == values[0]["hashes"] for v in values)
        if reference is None:
            reference = np.array(values[0]["probabilities"])
        deviation = max(float(np.max(np.abs(np.array(v["probabilities"]) - reference))) for v in values)
        assert deviation < 1e-5
        hot_wall = sum(v["seconds"] for v in values) / min(processes, 4)
        results.append(
            {
                "processes": processes,
                "threads": threads,
                "fits": 32,
                "cold_wall_seconds": time.monotonic() - before,
                "hot_wall_upper_seconds": hot_wall,
                "process_cpu_seconds": sum(v["process_cpu_seconds"] for v in values),
                "same_configuration_hashes_match": True,
                "max_probability_difference_from_reference": deviation,
            }
        )
        print(json.dumps(results[-1]), flush=True)
    report = {
        "workload": "32 identical causal neural+FFT/ridge/Newton fits on a 512-row existing Next suffix",
        "container_limits": "6CPU/6GiB; no legacy reads; 120-second launch budget and finite tasks",
        "results": results,
        "elapsed_seconds": time.monotonic() - start,
        "scope": "calibration only; joint inference telemetry captured during live program acceptance",
    }
    (settings.runtime / "p3-benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
    db.close()


if __name__ == "__main__":
    main()
