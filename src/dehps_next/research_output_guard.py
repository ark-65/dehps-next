"""Reject short generation loops without editing or resampling model answers."""

import hashlib
import re
from pathlib import Path

from .errors import DomainError

VERSION = "short-output-loop-guard-v1"


def identity():
    root = Path(__file__).parent
    h = hashlib.sha256()
    for name in ("research_output_guard.py", "research_stream.py", "research_short_thinking.py",
                 "research_agent.py", "qwen_recovery.py", "research_selection.py"):
        h.update(name.encode())
        h.update((root / name).read_bytes())
    return h.hexdigest()


def repetition(text):
    # JSON whitespace/punctuation must not disguise a repeated word or number.
    tail = text[-1024:]
    compact = "".join(c for c in tail if c.isalnum())
    for width in range(1, 33):
        span = max(48, 12 * width)
        span = ((span + width - 1) // width) * width
        if len(compact) >= span:
            unit = compact[-width:]
            if unit * (span // width) == compact[-span:]:
                return {"kind": "CONSECUTIVE_UNIT", "unit_characters": width,
                        "repeated_characters": span}
    # Mixed We/Okay/Hmm loops evade exact-block tests. Require a long tail with
    # almost no lexical diversity; six ordinary candidate assessments do not.
    tokens = re.findall(r"[A-Z]?[a-z]+|[A-Z]+|[\u4e00-\u9fff]", tail)[-64:]
    if len(tokens) == 64 and len(set(tokens)) <= 3:
        return {"kind": "LEXICAL_COLLAPSE", "tokens_observed": 64,
                "distinct_tokens": len(set(tokens))}
    return None


def check(text):
    evidence = repetition(text)
    if evidence:
        raise DomainError("LOCAL_MODEL_REPETITION", "Short output contains a demonstrated generation loop")

