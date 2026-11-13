# Actual-receipt recovery after a stream error

Primary call7048 produced a strict accepted comparative selection with complete
two-stage native receipts after574.2109 seconds. Its earlier generic stream
failure reason nevertheless remained latched. The recovery function only
handled four semantic reasons, while an expired stream-error backoff permitted
new calls without clearing that old reason after their actual success. Status
could therefore still report protected disablement while Qwen participated.

The successful-receipt cleanup now also handles the three existing stream
failure reasons. It does not add an admission path, retry, new-task exemption
or timer bypass. Clearing still requires the exact active profile, a later
SUCCEEDED native selection, its accepted QWEN_COMPARATIVE audit, complete frozen
two-stage/full-GPU receipts, matching model and same-job/attempt thinking
provenance. The logical stage must also be a candidate-selection stage. Failed,
fallback, stale, different-profile and incomplete receipts cannot clear state;
position bias, digest/context mismatch and unqualified profiles are not added
to the clearable list. The audit now retains the previous reason.

Recovery certificates are indexed by the exact profile and guard identity.
The old certificate remains immutable and is still considered with every
original binding check; it cannot certify changed guard/recovery code. The
verifier registers a separate scoped certificate instead of colliding with or
rewriting the prior one. Quality, latency, original negative-output detection,
144-slot provenance and zero valid-output rejections remain mandatory.

Actual isolated Python3.12/Next PostgreSQL acceptance used the original7048/7049
successful receipts and7046/7047 failed receipts, copied with explicit source
hashes and owned artifact references. A real planning lease/resource admission
fenced the replay. In database transactions, the old function retained the
stale reason after the successful receipt; the new function cleared it and
created the bound recovery audit. The actual failed/fallback receipt was
rejected and retained the reason. Both temporary state/native/audit replays
were rolled back; the original clone state and58 native rows were verified
unchanged. The immutable acceptance result remains separate, with zero new
model requests and zero fits. The old-identity certificate was rejected, and
the independently recomputed new scoped certificate was verified in the
isolated database. No primary state was cleared manually.

This is recorded-output operational acceptance, not new live Qwen participation,
generation-quality recovery, latency qualification or feedback-loop proof.
Production still uses its original source/profile. Current128 large-input
diagnosis failed with repetition after197.6982 seconds and five attributed GPU
fence events, despite verified128/full-GPU binding and zero primary overlap.
The failed batch-only direction is retained; GPU operator profiling is a
separate frozen next diagnostic. No code here promotes that failed profile.

Original24-hour observation and failures remain unchanged. The current clock
ends no earlier than2026-11-14 11:14:50.976635 Shanghai. A later repair source
needs its own full elapsed observation and actual live feedback proof. Main
12-CPU training, prior improvements, draw-day17:00 pause and complete official
verification before resume remain in force. Legacy DEHPS, mail delivery and
predictive evidence are unchanged; no new unit tests or CI were added.
