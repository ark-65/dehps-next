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
