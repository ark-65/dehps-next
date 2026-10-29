"""Owner-authorized SELECT-only export. Writes solely under Next/runtime/imports.

Run on the remote host, not inside the training container. No credentials are copied.
The source is limited to at most 5000 tiny draw facts, never training artifacts/tables.
"""

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

query = """BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SELECT coalesce(json_agg(x ORDER BY draw_date,issue),'[]'::json) FROM
 (SELECT issue,draw_date,red_numbers,blue_number,source FROM public.ssq_history
  ORDER BY draw_date,issue LIMIT 5001) x;
COMMIT;"""
result = subprocess.run(
    [
        "docker",
        "exec",
        "ark-dehps-postgres",
        "sh",
        "-c",
        'exec psql -X -qAt -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "$1"',
        "readonly-export",
        query,
    ],
    capture_output=True,
    check=True,
    timeout=15,
)
rows = json.loads(result.stdout)
if not rows or len(rows) > 5000:
    raise SystemExit("Unexpected history size; nothing exported")
records = []
for r in rows:
    day = datetime.strptime(r["draw_date"], "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    records.append(
        {
            "issue": r["issue"],
            "red": r["red_numbers"],
            "blue": r["blue_number"],
            "draw_at": day.isoformat(),
            "available_at": day.replace(hour=23, minute=59, second=59).isoformat(),
        }
    )
root = Path(__file__).resolve().parents[1]
directory = root / "runtime" / "imports"
directory.mkdir(parents=True, exist_ok=True, mode=0o700)
path = directory / "legacy-draws.json"
body = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
if len(body) > 2 * 1024 * 1024:
    raise SystemExit("Export exceeds 2MiB; nothing written")
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "wb") as h:
    h.write(body)
print(
    json.dumps(
        {
            "count": len(records),
            "first": records[0]["issue"],
            "last": records[-1]["issue"],
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "legacy_transaction": "READ ONLY",
            "destination": str(path),
        }
    )
)
