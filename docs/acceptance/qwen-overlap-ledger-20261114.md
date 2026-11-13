# Primary inference intervals across graph retirement

The earlier overlap export queried only live `research_model_calls`; its
`complete` flag only checked a row-count bound. Retiring a campaign could
therefore remove an earlier primary inference interval from a long revalidation.
This is an evidence-collection defect, separate from Qwen generation repair.

`scripts/observe-qwen-overlap.py` keeps a durable interval ledger using a
repeatable-read, read-only PostgreSQL snapshot. It reads every live logical
primary call and archive events in4096-sequence blocks with the original8s
statement timeout. Archived receipts are read before their event sequence is
allocated; unioning live calls also covers late archive commits behind the
sequence frontier. The observer does not assume sequence numbers commit in
order. An active call disappearing without its archive, conflicting terminal
facts or a regressed archive cursor fails closed without renewing the output.

The publication timestamp is the first query's statement timestamp, not the
later publication time. Active intervals use a conservative snapshot bound.
Missing terminal latency uses the first terminal observation as an upper bound,
explicitly labeled; it never becomes zero or an estimated provider duration.
The32MiB artifact cap stops only this observer. It does not limit main training
or model calls.

Actual Python3.12/Next PostgreSQL acceptance reconstructed211 logical records,
including186 from immutable campaign archives and older records outside the
requested coverage boundary. Call7034 was recovered from archive sequence653334
with its original391.8567s wall time and request/response references. The first
scan read161 blocks in3.038533s; two incremental restarts read one block each
in0.011545s and0.007381s, preserving all211 IDs and the original initialization
time. Records were checked against the separate archive-aware selection
observer with no missing IDs. There were no model calls, fits or database writes.

Historical reconstruction is labeled separately from live observation. The
observer's initialization time cannot be borrowed as earlier live sampling or
a completed24h soak. Future fresh-slot revalidation must start after its actual
initialization and bind the frozen observer source. The old source's sampling
and920.534550s training-continuity failures remain intact. Actual generation
repair, qualification, deployment, later-feedback closure and a repaired
source's own24h are still pending.

Primary training, draw-day17:00 pause and complete official verification before
resume are unchanged. No legacy DEHPS, mail flow, unit tests or CI was changed.
