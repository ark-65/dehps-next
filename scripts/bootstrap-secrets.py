"""Create private Next-only configuration; never read or reuse legacy credentials."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = root / ".env"
password = secrets.token_hex(24)
token = secrets.token_hex(24)
body = (
    f"DEHPS_NEXT_DB_PASSWORD={password}\n"
    f"DEHPS_NEXT_DATABASE_URL=postgresql://dehps_next:{password}@next-database:5432/dehps_next\n"
    f"DEHPS_NEXT_API_TOKEN={token}\n"
)
try:
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print("Existing private .env retained")
else:
    with os.fdopen(fd, "w") as h:
        h.write(body)
    print("Created private Next-only .env; secrets not displayed")
(root / "runtime" / "application").mkdir(parents=True, exist_ok=True, mode=0o700)
