# Frozen Qwen latency and stability revalidation

Owner request: 2026-11-13. This is a fresh regression of the accepted short4B
contract under the current continuous-training workload. It is not a new model
selection, predictive study, performance pass or completed soak in advance.

## Diagnosis to distinguish

Production call6982 spent341.450 seconds: thinking187.101 and final answer154.321
seconds of provider time. Their sum differs from logical wall time by only0.034
seconds. Full GPU residency and16k context were verified. Thinking-model load
was2.093 seconds; final-phase load was0.002 seconds. HTTP/DB delay, a cold model
load and silent CPU fallback do not explain this observation.

Compared with call6980 (238.052 seconds), the thinking output stayed512 tokens,
but its native evaluation grew from89.861 to137.099 seconds. Final output grew
from468 to592 tokens and native evaluation from100.561 to154.082 seconds. Input
size also increased. Both more work and slower observed token generation matter.
Shared iGPU/CPU memory or power contention is a hypothesis, not a proven cause
from these historical receipts alone. Later production calls include slow and
rejected answers; successful-call-only latency would bias the diagnosis.

## Preserved contract

The isolated revalidation uses database `dehps_next_qwen_latency_20261113`,
runtime `qwen-latency-case` and a new immutable corpus. It names source study
`qwen-mechanism-39b946ec64cf9c6b` and verifies all144 source logical-input hashes,
the same12 real cases, three variants, two seeds, feedback/control arms and
exact pair identities before any provider call. All answers must be new. Source
answers are not imported as new selections. The profile/model, prompts, schemas,
sampling,512/1024 budgets,16k context and four helper CPUs remain unchanged.

Original quality gates remain accuracy>=0.90, stability>=0.80, first-position
fraction<=0.50 and feedback lift>=0.20. The sole original negative futility rule
is retained. There is no positive early stopping or selective retry of wrong
answers. Physical voids retain the same input/seed and separate retry evidence.

Latency uses the existing `performance()` implementation: all144 performed
logical slots, including wrong answers, source-local distinct two-stage receipts,
mean<=240 seconds and nearest-rank p95<=300 seconds. Missing/partial receipts do
not become estimated tokens or a latency pass. Preserve failed and unrun slots.
Production's larger six-candidate requests are reported separately; passing
the original three-candidate regression cannot establish their latency.

## Primary priority and interference controls

The existing idle admission remains: serialized calls,30 seconds after actual
completion while desktop idle>=120 seconds and resource/training guards pass;
otherwise the original300-second start interval. Missing/stale host observations
retain the original policy. The revalidation adds a stricter primary-priority
guard: a fresh<=30-second snapshot, no active primary logical call, an open
official training window and at least900 seconds before the next possible
production review. Every wait rechecks the existing resource admission.

These are admission guards, not guarantees that a future request cannot run
unusually long. The shared provider still permits one physical request. A
retained primary timeline is checked against every actual revalidation interval;
any primary/revalidation overlap invalidates this regression rather than being
discarded from latency. Original semantic and latency gates are not widened.

Primary training/services, its1800-second/20-new-feedback advice cadence,
accepted parent, numerical threads and CPU quota are unchanged. The observer
records live CPU counters/throttling/pressure, GPU clock, memory, primary progress
and actual native timing. It does not throttle training or treat temperature as
a new gate. The current controller/model services need no recreation for this
isolated inference-only regression. No new fitting is credited to revalidation.

## Long observation and reporting

Primary soak `qwen-latency-stability-20261113` started2026-11-13 08:59:53.444663
Shanghai time and ends no earlier than2026-11-14 08:59:53.444663. Its original
300-second sampling, maximum600-second sample gap and900-second fresh-fit stall
review rule remain unchanged. The persisted observer does not reset the clock
after restart. An enabled observer or a few clean samples are not completion.
Sample gaps/warnings are retained and result in review, not an extended limit.

Report actual elapsed coverage, gaps, training updates, Qwen successes/rejections,
physical voids, recovery events, token-count coverage and latency separately.
`OBSERVED_COMPLETE` is a training observation result; it does not erase Qwen
semantic failures, qualify latency or demonstrate predictive improvement.

The existing draw-day17:00 pause, immutable report and official-result-only
resume remain in force in both admission and application leases. Next-only
verified official receipts may be copied into isolation; no clock override is
used. Legacy DEHPS is not accessed. No new unit tests, CI, dashboard or test mail
are introduced. Private frozen manifests, native receipts and hardware journals
remain under `runtime/operations/qwen-latency-20261113/`, outside Git. Append the
actual final acceptance record only after the frozen study and elapsed soak have
their own results.
