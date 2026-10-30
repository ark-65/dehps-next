import hashlib
from functools import cache
from pathlib import Path


@cache
def code_identity():
    root = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.suffix in (".py", ".sql"):
            h.update(str(path.relative_to(root)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


@cache
def numeric_identity():
    import numpy as np
    import torch

    from .domain import digest

    root = Path(__file__).resolve().parent
    names = [
        "domain.py",
        "model.py",
        "research_compute.py",
        "research_math.py",
        "research_protocol.py",
        "scores.py",
    ]
    # Exact orchestration source audited against the unchanged v2 fitter, scores, anchors and RNG.
    # Unknown future edits get a new numeric identity; no blanket compatibility mapping.
    equivalent_compute = {
        "4d6ac973f26418215fee5e15432df5a424135028126ebc53ef87aaec14bdadba": "4e6efa00349cdbb4da980ffab37b2b24c4c6d7c9cfa40b6e885424c8a9d38d78",
    }
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    hashes["research_compute.py"] = equivalent_compute.get(
        hashes["research_compute.py"], hashes["research_compute.py"]
    )
    return digest(
        {
            "files": hashes,
            "torch": str(torch.__version__),
            "numpy": np.__version__,
            "contract": "prior-fit-v2-single-blas",
            "blas_threads": 1,
        }
    )
