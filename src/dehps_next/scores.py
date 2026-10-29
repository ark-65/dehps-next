"""Column arrays, compressed once per bounded block; legacy JSON remains readable."""

import io
import json

import numpy as np


def encode(rows, identity=""):
    columns = {key: np.asarray([r[key] for r in rows]) for key in rows[0]} if rows else {}
    columns["__identity"] = np.asarray(identity)
    output = io.BytesIO()
    np.savez_compressed(output, **columns)
    return output.getvalue()


def decode(data):
    if not data.startswith(b"PK"):
        value = json.loads(data)
        return value if isinstance(value, dict) else {"rows": value}
    with np.load(io.BytesIO(data), allow_pickle=False) as columns:
        identity = str(columns["__identity"].item())
        keys = [k for k in columns.files if not k.startswith("__")]
        values = {k: columns[k].tolist() for k in keys}
        count = len(values[keys[0]]) if keys else 0
    return {"identity": identity, "rows": [{k: values[k][i] for k in keys} for i in range(count)]}
