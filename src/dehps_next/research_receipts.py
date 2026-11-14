"""Keep unrepresentable provider text as opaque evidence, never as a repaired answer."""

import hashlib

from .research_output_guard import unsafe_text


class ReceiptMetrics:
    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.saved = {}
        self.write_errors = {}

    def store(self, data):
        sha = hashlib.sha256(data).hexdigest()
        if sha in self.write_errors:
            raise self.write_errors[sha][1]
        if sha not in self.saved:
            try:
                self.saved[sha] = self.artifacts.write(data, category="research/inference")
            except Exception as exc:
                self.write_errors[sha] = ({"sha256": sha, "bytes": len(data),
                                          "failure_code": getattr(exc, "code", type(exc).__name__)}, exc)
                raise
        return self.saved[sha]

    def __call__(self, value):
        return self.encode(value, persist=True)

    def failure(self, value):
        # Failure recording cannot retry a failed write or mask the original
        # resource guard with another JSONB error. Missing bytes remain explicit.
        result = self.encode(value, persist=False)
        if self.write_errors:
            result = {**result, "unwritten_provider_evidence": [r[0] for r in self.write_errors.values()]}
        return result

    def reference(self, data, *, persist):
        sha = hashlib.sha256(data).hexdigest()
        if persist:
            return {"ref": self.store(data)}
        if sha in self.saved:
            return {"ref": self.saved[sha]}
        return {"ref": None, "sha256": sha, "bytes": len(data), "raw_evidence_available": False}

    def encode(self, value, *, persist):
        if isinstance(value, bytes):
            return {"kind": "RAW_PROVIDER_FRAME_EVIDENCE_V1", "encoding": "binary",
                    **self.reference(value, persist=persist)}
        if isinstance(value, str) and unsafe_text(value):
            # This reversible encoding preserves NUL and isolated surrogate code
            # points. Ordinary UTF-8 provider text and every valid reply stay unchanged.
            data = value.encode("utf-8", "surrogatepass")
            return {
                "kind": "UNSAFE_PROVIDER_TEXT_EVIDENCE_V1",
                "encoding": "utf-8-surrogatepass",
                **self.reference(data, persist=persist),
                "characters": len(value),
                "contains_nul": "\x00" in value,
                "contains_surrogate": any(0xD800 <= ord(c) <= 0xDFFF for c in value),
            }
        if isinstance(value, dict):
            return {key: self.encode(item, persist=persist) for key, item in value.items()}
        if isinstance(value, list):
            return [self.encode(item, persist=persist) for item in value]
        return value
