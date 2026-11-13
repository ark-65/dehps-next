# Fresh revalidation slot recovery

The latency revalidation driver previously retried every nonsemantic error and
delegated to a wrapper that also retried YIELD errors. A generic unavailable
error can contain actual degenerate output. A process exit after generation but
before the selection ledger write could also repeat the same performed slot.

Named latency revalidations now call one native attempt at a time. A slot records
its frozen context/profile/key and native watermark before execution, then saves
the exact outcome before the selection ledger write. Files and containing
directories are synced. Resume verifies the payload hash and the original native
records in Next PostgreSQL. A performed outcome is returned unchanged; a started
slot with no outcome requires review and cannot generate again.

A physical retry requires every native phase to have failed with an allowed
transport reason, an actual zero-byte stream observation and no generated text,
tokens or semantic failure. Missing counters are not zeros. Partly performed or
unclassified failures stop for review. A YIELD may repeat automatically only when
no native attempt was allocated. The original 144 inputs/seeds, eight-error
futility rule, quality gates, all-slot latency gates and priority/resource/draw
rules are unchanged. Existing frozen driver copies and terminal studies remain
untouched. Future driver bundles must include `qwen-fresh-slots.py`.

Actual isolated Python 3.12 CPU execution used read-only Next PostgreSQL records
71/72, 69/70, 75/76, 7044/7045 and 77/78. Only the actual zero-stream loader failure
qualified as a physical void. Interrupted generation, valid generation, generic
nonempty degeneration and the newly failed poll0 generation were all refused as
retry voids. The exact recorded valid payload survived controller restart; the
physical void stayed recorded before a new admission. Owned-file fault injection
confirmed that a missing outcome stops recovery, and the real generic nonempty
failure continued to require review. Native records were reverified from the
database during replay.

The final source replay receipts are retained in
`runtime/operations/qwen-fresh-slot-acceptance-v3-20261113/`; earlier engineering
replays remain separate. These were recorded-output and controller-file checks,
with zero model requests, new fits or database writes. Ruff and diff checks
passed. No unit tests or CI were added. Fresh generation under the new driver,
model/backend qualification, primary deployment and a repaired-source 24-hour
soak remain pending; this change does not claim a generation repair.
