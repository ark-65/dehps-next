# Retained parent and pruning-fallback reports

Migration014 separates immutable accepted-parent versions and atomic current/previous
pointers from optional research graphs. Accepted baseline/improvement commits register
verified publication weights, historical scores and the dataset in the same fenced
transaction that selects the node. Pruned/inconclusive nodes do not update the pointer;
replayed older facts cannot move it backwards. Study/recovery campaigns are excluded.

Formal promotion and report qualification are unchanged. After draw-day17:00 checkpoint
completion, formal sealing is attempted first. If unavailable, the fallback follows the
retained lineage, matching numeric/thread/data contracts and the legal cutoff. It uses
the publication anchor, not a warm-start research optimizer, an arbitrary completed
child or frequency baseline. A missing/corrupt parent is an explicit error. New seals
are forbidden before17:00, after the failsafe or once the target result is known.

Fallback payloads freeze100 unique legal red combinations, one blue, probabilities,
model/score/data references, validation failures, parent version and prediction digest.
They are independently immutable and idempotent; completed official receipts settle
these exact numbers into a separate ledger. Qualified coverage and existing report
identities remain unchanged. Mail identifies the parent and fallback status explicitly.

GC roots now include current/previous parents, fallback seals and restored evidence for
older reports. Historical version metadata survives graph retirement; unreferenced
large artifacts remain reclaimable. Report2026125's original weights/scores/data are
restored only from hash-identical Next copies and pinned through report evidence;
its immutable payload, prediction, result and delivery are not rewritten or resent.

The existing read-only status API adds parent heads, fallback seals/settlements and
restoration evidence. `parent-pin` bootstraps an already completed selected parent at
an audited release boundary. No dashboard or mutable HTTP interface is added.
