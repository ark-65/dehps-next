# Qwen receipt storage recovery engineering acceptance

Primary call 7156 failed with `UntranslatableCharacter` during its thinking phase; child 7157 subsequently became `UNKNOWN`, with no final response artifact. Its last persisted progress contained 397 text bytes and 317 chunks. The original rejected bytes are unavailable. A separate read-only Python 3.12 / real Next PostgreSQL probe confirmed that ordinary text can be stored in JSONB while controlled NUL text raises SQLSTATE `22P05`. This reproduces the storage boundary, without reconstructing the missing original response or proving its exact character sequence.

Receipt persistence now stores unrepresentable provider text and its rejected original NDJSON frame as opaque, content-addressed artifacts. The reversible text encoding is `utf-8-surrogatepass`; neither the artifact nor an escaped substitute becomes a candidate answer. Valid text remains unchanged. NUL and isolated surrogates, including those introduced by parsing escaped JSON strings, fail before successful selection. A per-call memo avoids repeated artifact writes from progress and finalization callbacks.

Artifact size, reserved writes, frame/stream limits, leases and provider-count rules retain their original bounds. If an original artifact guard prevents evidence storage, failure metadata records its original error, digest, byte size and unavailable-evidence status without retrying the write or inserting unsafe text into JSONB. The thinking failure update coalesces an initially NULL metrics column before recording the failure and its token receipt. Lifecycle discovery extracts metric references inside PostgreSQL and applies the same campaign retention rules as request/response artifacts.

## Actual isolated execution

The installed candidate ran in the Python 3.12.13 CPU image with Torch `2.15.0+cpu`, NumPy `2.5.4`, no source bind, GPU devices or model weights. A loopback synthetic provider exercised the actual inference, short-thinking, stream, artifact, resource and database code against a dedicated Next PostgreSQL database. Synthetic receipt rows and declared fixture counts remain in that database and are excluded from primary/Qwen usage and qualification evidence. No official draw rows, mail or training were produced.

| Controlled engineering case | Logical call | Thinking child | Recorded result |
| --- | --- | --- | --- |
| NUL in thinking output | FAILED | FAILED | `INVALID_LOCAL_REPLY` |
| Isolated surrogate in thinking output | FAILED | FAILED | `INVALID_LOCAL_REPLY` |
| NUL in a final thinking frame | FAILED | FAILED | Actual fixture final counts retained in the child only |
| NUL in answer output | FAILED | SUCCEEDED | `INVALID_LOCAL_REPLY` |
| Surrogate introduced by parsing escaped answer JSON | FAILED | SUCCEEDED | `INVALID_LOCAL_REPLY` |
| Ordinary two-stage control | SUCCEEDED | SUCCEEDED | Original controlled text returned unchanged |
| Artifact write guard | FAILED | FAILED | Original `ARTIFACT_TOO_LARGE` preserved |

The first engineering execution failed its last case: concatenating failure metadata onto SQL NULL left the child RESERVED and caused an `AttributeError`. That database, its fourteen synthetic receipts and the failed result remain unchanged. After the NULL update fix, a separate database passed the same seven cases. No expectation or production limit changed. Only the guard fixture used a stricter 4,096-byte artifact cap to exercise the original protection.

Seventeen referenced artifacts passed hash/length readback and the actual lifecycle reachability query; an unreferenced control remained unprotected. A subsequent read-only inspection verified complete decoded text and exact original frame bytes for all four direct unsafe-text cases, retained the escaped-surrogate answer as a failed response, and confirmed unknown counts stayed unknown. Per-case writes were 1,324–2,163 bytes against the unchanged 4 MiB planning reservation.

An additional installed-image replay checked the immutable original 144 outputs: 141 previously valid responses had zero additional rejection, the original three invalid outcomes remained invalid, and both earlier failed symbol-loop prefixes remained detectable. The repetition function's AST is unchanged. This replay registers no recovery certificate and contributes no new generation, latency or mechanism qualification.

Candidate source is `4510982911b6cbca142e7462e44af383a2c4f95d694e426657ac984f075d90f8`, output guard `5a3b6859d899a6be76e303c48328e94cf2cdee1aa0565f63453eb51b1ab999a5`, and installed CPU image `sha256:365205150595932c75b3235ff11d906e69c6c45a691ca0be023cab3b709db7a5`. All nine numeric source files remain identical to the parent and the actual numeric identity remains `9cbb1aaf437410dce1dbe24d38cbebca2b2018cd2723ebeb757b3f3917ac2b06`.

Private evidence is retained under `runtime/operations/qwen-primary7156-unsafe-receipt-forensics-20261115`, `qwen-receipt-storage-runtime-v2-20261115` and `qwen-receipt-output-replay-20261115`. Runtime receipts, synthetic data and caches are excluded from Git. No unit tests or CI were added.

## Remaining acceptance

The running primary application was independently rechecked as source `981cd97c9e676df7fd3137b026995949922f6a69a5c3cc38ccd6debc3f3371a1`, with twelve origins and one Torch thread per origin. This candidate has not been deployed or activated. Fresh frozen generation, full quality/latency qualification, completed-boundary deployment, actual selected training and subsequent feedback closure, and the repaired source's own 24-hour observation remain pending. Draw-day 17:00 pause and complete authoritative-result-only resume remain unchanged. Legacy DEHPS remains untouched.
