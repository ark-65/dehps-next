"""Read named Next container state without confusing transport errors with absence."""

import json
import subprocess
import time


class ContainerReadUnavailable(RuntimeError):
    pass


def inspect_next(name, *, attempts=6, delay_seconds=5):
    if not name.startswith("dehps-next-"):
        raise ValueError("Only explicitly named Next containers may be inspected")
    last_error = ""
    for attempt in range(attempts):
        try:
            result = subprocess.run(["docker", "inspect", name], text=True, capture_output=True, timeout=15)
            if result.returncode == 0:
                rows = json.loads(result.stdout)
                if (
                    not isinstance(rows, list) or len(rows) != 1
                    or not isinstance(rows[0], dict) or not isinstance(rows[0].get("State"), dict)
                ):
                    raise ValueError("Malformed container inspection")
                return rows[0]
            last_error = result.stderr.strip()[:400]
            message = last_error.lower()
            if "no such object:" in message or "no such container:" in message:
                return None
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
            last_error = type(exc).__name__
        if attempt + 1 < attempts:
            time.sleep(delay_seconds)
    raise ContainerReadUnavailable(f"Cannot read {name} after {attempts} attempts: {last_error}")
