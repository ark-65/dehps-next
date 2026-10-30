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
    return digest(
        {
            "files": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names},
            "torch": str(torch.__version__),
            "numpy": np.__version__,
            "contract": "prior-fit-v2-single-blas",
            "blas_threads": 1,
        }
    )
