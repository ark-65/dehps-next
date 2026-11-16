# Host outage and mail recovery (v1.1)

Official result notification must not depend on successful pre-draw preparation.
On every reporter tick, complete authoritative CWL publication/source receipts
since the first immutable final mail report are eligible for result notification,
including issues whose entire preparation window was lost. The subscription-era
anchor avoids flooding recipients with imported historical draws. Recovery is
oldest-first, bounded to32 notices per tick. Existing POST or DRAW_RESULT reports
suppress another result notice; the immutable issue/kind identity and recipient
outbox keys retain concurrent/repeated-tick deduplication.

Missing final reports are explicitly described as prediction coverage gaps.
Recovery never creates or retrospectively seals a prediction. Existing final
reports retain the independent result-before-settlement notice and later POST.
Pre-draw mail still expires at its deadline. Ambiguous SMTP DATA outcomes remain
UNKNOWN and are not blindly resent. Recovery is possible only once the host,
Next database, source verification and reporter are available.

The bounded host incident watcher records boot identity, memory, swap and memory
PSI, plus new kernel faults. Two sample files are capped at approximately2MiB
each. It preserves the first incident hold and publishes existing controller
operator-boundary-hold markers for owned Qwen experiment directories with frozen
admission drivers. Existing holds are never overwritten or automatically released.
Primary inference's existing physical-fault quarantine remains authoritative;
CPU training and mail are unaffected. This reduces repeated experimental GPU
exposure; it does not prove a kernel/hardware defect has been fixed. Samples and
receipts remain private under runtime. No synthetic GPU fault or crash is induced.

## 2026-11-16 acceptance and incident findings

Actual Python3.12.13 and isolated Next PostgreSQL validation recovered a missing
final-report issue, deduplicated repeated recovery, rejected unverified provenance,
skipped pre-subscription history, and retained result-before-settlement behavior
for an existing final report. No predictions or acceptance SMTP attempts were
created. Production2026131 official result mail was SMTP-accepted at10:52:01
Shanghai on November16; provider acceptance is not inbox confirmation.

Previous boot journal coverage ends November15 at16:16:34 Shanghai; the next boot
starts November16 at10:34:33. There is no orderly host shutdown record or explicit
OOM/panic/thermal shutdown in the available previous-boot journal. There are274
GPU fence timeout lines in that boot; the continuous observer ties the final
11:54 events to the Next primary llama-server process. The existing primary
profile is quarantined as ACTUAL_GPU_FAULT_REVIEW_REQUIRED with no timed retry.
The hours-long gap between the last GPU fault and journal termination prevents
assigning the abrupt host failure to that fault with confidence. Power loss,
forced power-off and an unlogged kernel/hardware hang cannot be distinguished
from available evidence. The watcher retains future evidence, not a root-cause
or recurrence-prevention guarantee. No sustained soak has passed for this change.

All seven legacy-named containers were stopped with restart policy `no`.
System/user legacy services and timers were inactive and disabled/masked/static;
no legacy runtime was started, mounted or modified. New incident monitoring is
Next-only. Existing unrelated working-tree changes were preserved.
