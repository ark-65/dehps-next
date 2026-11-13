# Qwen latency investigation and provider-error repair

Date: 2026-11-13. Status: the original frozen regression ended negative;
classifier and storage acceptance completed, while the full24-hour primary
observation remains pending. The retained/fresh diagnostic is inconclusive.
This document is not a successful requalification, completed soak, primary
source deployment or predictive-improvement claim.

## The original341-second call

Native source-local receipts account for341.415993 of call6982's341.449800
seconds. Thinking consumed187.094995 seconds and the answer154.320997 seconds.
Only0.033807 seconds remained outside provider durations. Thinking load was
2.092792 seconds, answer load0.001694. Both phases had complete native counts,
full GPU offload and16k context. A network/DB delay, cold-model load or silent
CPU fallback does not explain the observation.

| Measurement | Call6980 | Call6982 |
| --- | ---: | ---: |
| Logical seconds |238.0518|341.4498|
| Thinking input/output tokens |3301/512|3560/512|
| Answer input/output tokens |3815/468|4074/592|
| Thinking generation tokens/second |5.6977|3.7345|
| Answer generation tokens/second |4.6539|3.8421|

The103.398-second difference decomposes descriptively into47.238 more seconds
for the same512 thinking tokens,26.644 seconds for124 additional answer tokens
at the first call's rate,26.877 from the answer-rate difference, and2.639 from
remaining native work/overhead. This arithmetic does not identify a causal
hardware bottleneck. The original144-case acceptance had much smaller requests
(mean thinking input1343.75, answer output250.15), so its latency distribution
cannot guarantee six-candidate production latency.

Retained kernel evidence covers the original call interval and has no matching
GPU fence/hang event there. Later GPU faults must remain a separate finding.

## Four predeclared submission diagnostics

Exactly one attempt per declared cell was performed. No diagnostic answer counts
as a qualification slot. All four had empty actual primary-inference overlap.
Primary training retained12 origin processes, one Torch thread each and12 CPU.

| Trial | Original input | Submission mode | Logical seconds | Actual result |
| --- | ---: | --- | ---: | --- |
|a0|6980|Default|104.8437|Stream closed; Vulkan ErrorDeviceLost and attributed context reset|
|b2|6982|Serialized|752.3984|Valid; both native receipts; no attributed fence events|
|b0|6980|Serialized|525.5659|Valid; both native receipts; no attributed fence events|
|a2|6982|Default|317.5562|Provider token-repeat abort; no final native counts|

The default cells recorded12 and10 attributed fence events respectively. Only
a0 had a verified GPU context reset. Preserve this distinction: a2's actual
error frame says `prediction aborted, token repeat limit reached`.

A subsequent actual-runner audit found **1024 batch/ubatch in all review trials,
versus512 in the primary runners**, despite matching image/model/context and
wire profiles. The four cells therefore do not establish a production-equivalent
comparison. Ollama0.40.13's
[automatic batch selection](https://github.com/ollama/ollama/blob/v0.40.13/server/sched.go)
uses effective context and available-memory headroom when no batch is explicit.
This explains why image/profile equality alone is inadequate; the specific
reason for this host's different selected batches is still unproven. Preserve
all four outcomes; do not rerun them and replace the failures. The intended
production-latency mitigation is unsupported and no serialized profile is
activated. Any further batch experiment needs its own declared execution
contract and cannot replace the frozen144 requests.

## Provider repetition was misclassified as infrastructure

The existing stream reader mapped every provider error frame to
`LOCAL_INFERENCE_UNAVAILABLE`. The captured a2 frame proves a performed
repetition failure was mislabeled. A same-input physical retry would violate
the original no-resampling rule. The isolated cohort was stopped to prevent
that path; interrupted calls19/20 remain separate operator interruptions with
partial output and unknown provider counts. Earlier attempts without raw error
frames are not retrospectively assigned this cause.

`research_stream.provider_error_code()` now maps only the exact observed
provider repetition message to the existing `LOCAL_MODEL_REPETITION` category.
Other errors retain infrastructure classification. The stream preserves the
canonical error-frame SHA256 and classification in partial progress. No guard,
quality gate, model sampling, prompt, token budget or recovery cooldown changes.
The upstream
[provider implementation](https://github.com/ollama/ollama/blob/v0.40.13/llm/llama_server.go)
confirms this is its generated-token repetition abort.

Actual isolated Python3.12 and Next PostgreSQL acceptance replayed the captured
provider frame through HTTP, `infer()`, the two-stage prefix path, native call
storage and local usage accounting. It made exactly one replay request; both
native rows21/22 were FAILED with `LOCAL_MODEL_REPETITION`, semantic-failure
membership was verified, and missing token counts stayed missing. The frame's
canonical hash survived in the native child receipt. This is **recorded-provider
error integration replay**, not a new successful model generation or a fresh
semantic/latency slot. No unit tests, CI or SMTP were used.

The patched runtime source is
`29e02b32cfd011be70091ab1852834f56ce264d4f515defcabf655632489afaf`;
numeric identity stays
`9cbb1aaf437410dce1dbe24d38cbebca2b2018cd2723ebeb757b3f3917ac2b06`.
The primary services retain source
`981cd97c9e676df7fd3137b026995949922f6a69a5c3cc38ccd6debc3f3371a1`;
this replay is not a primary deployment. The isolated regression may use a
separately hashed, append-only classifier hook to apply this exact mapping while
preserving original source, model requests, gates, wrong slots and all native
attempts. Such a hook is an explicit execution amendment, not unchanged code.

## Long observation remains pending

The first run retains its944.539696-second sampling gap, beyond the unchanged
600-second limit. Exact bounded SQL observation repaired the15-second aggregate
timeout without changing the original counters or sampler thresholds. A new
separate run `qwen-latency-stability-20261113-v2` started2026-11-13 11:14:50.976635
Shanghai; its full24-hour deadline is2026-11-14 11:14:50.976635. The failed first
clock/history is not reset. Counters from overlapping runs must not be added.

The primary observer continues300-second samples,600-second maximum gaps and
900-second fresh-fit stall review, with the unchanged draw-window exemption.
A separate read-only collector writes final evidence only after the actual new
soak deadline/terminal sample, original cohort result and four diagnostic
outcomes exist. Its presence does not prove those conditions have occurred.

Private manifests, interruptions, native/raw provider receipts, kernel events,
runner audits and replay acceptance are under
`runtime/operations/qwen-latency-20261113/` outside Git. Main training, accepted
parent, numerical contract, production1800-second/20-feedback cadence,
draw-day17:00 pause and complete-official-verification-only resume remain in
force. No legacy services/code/data, host watchdog, driver or power setting was
modified. Append final elapsed/latency conclusions only from terminal evidence.

## Frozen regression terminal result

The original negative-futility rule was reached without changing requests,
seeds, thresholds or the preserved first wrong slot. All15 executed slots were
rejected for repetition: feedback0/8 correct and control0/7, with zero valid
replies. Even making all64 remaining feedback requests correct gives64/72,
88.888889%, below90%. The remaining129 slots stay NOT_RUN. This is an original
negative terminal result, not a shortened positive acceptance.

The independent original latency calculation has15 logical slots but **zero
complete measurable two-phase receipts**, so mean/P95 remain null and the144-slot
latency gate is not passed. Early rejected generation is not a speed gain.
An additional read-only audit included all20 cohort logical attempts, including
three earlier uncertain infrastructure failures and two operator interruptions.
It extended interrupted intervals to actual container-stop timestamps and found
zero overlap with the complete primary-inference timeline. The original
qualification receipt and all native attempts remain unchanged.

## Matched512 diagnostic and reporting recovery

The retained-runner cell made one actual logical probe (native51/52). It failed
with provider repetition after349.7497 logical seconds. The repaired stream
reader classified the actual provider frame as `LOCAL_MODEL_REPETITION`; native
child52 retained canonical frame hash
e58efdadfb338fc1b1bf72aee9f304d87c844c53d47703eea3700771a7426d47.
Both provider token counts stayed unknown. This adds actual-model execution
coverage of the classifier to the earlier recorded-frame integration replay;
it does not establish improved model quality or latency.

The diagnostic reporter then hit a foreign-key error: its new study had no
condition pair row before inserting the outcome. The model error had already
been persisted and its job/resources released. The dispatcher refused another
attempt using the original started marker. A Next-only Python3.12/PostgreSQL
recovery inserted the missing pair and outcome from the **existing terminal
native51/52 rows**, verified the exact frozen input/request hashes, and made no
model request. The unrecorded driver elapsed time stays null;349.7497 is the
actual native logical wall time, not an estimated driver time.

The tool now inserts/verifies the condition pair before admission and refuses
any existing native diagnostic stage even if its result-report row is absent.
Actual isolated invocation of the corrected tool refused the performed warm
condition before claiming another job: the database still contained52 native
rows, one warm parent and zero fresh parents. No unit test or extra generation
was used. The original frozen v1 driver remains preserved separately.

The reporter failure also lost its final PID-binding observation. By recovery
time the primary model had naturally unloaded. Before/mid-call observations
showed the retained PID and512 batching, and four kernel fence events matched
that PID during the attempt, with zero primary-inference overlap. **Missing
after-PID proof is not imputed or waived.** The fresh cell is therefore NOT_RUN
under the declared stop rule. The state diagnostic is INCONCLUSIVE; it proves
neither a cache-state cause nor a fresh-process remedy. Its dispatcher is closed
against terminal re-entry, verified by an actual zero-request invocation. No
failed cell, original qualification slot or primary configuration was replaced.

## Actual primary recovery and observation still pending

Production call7034 completed in391.8567 seconds. Audit26874 records actual
QWEN_COMPARATIVE selection and26875 records RECOVERED_BY_ACTUAL_SELECTION;
the protected reason cleared through the certified existing recovery path.
This is actual new-task selection recovery, not a manual lock reset, a passed
latency gate, a newly verified next-feedback chain or sustained reliability.

A dated primary read at12:52 Shanghai showed the successor still RUNNING with
18 actual samples, no fresh-fit stall warning and the preserved542.592210-second
maximum gap. Its12:47:45 sample recorded13,997 fresh origins,1,836,879 gradient
steps and4,490 reused origins since the successor start. These counters are
observation/training evidence, not additional draws or predictive improvement.
The full original24-hour successor deadline remains **2026-11-14 11:14:50.976635
Shanghai**. No completed long-observation verdict is claimed here.

The private `actual-report.md` updates pending actual progress and writes the
terminal report only when elapsed soak, original regression, all-attempt audit
and declared diagnostic outcomes exist. `completed-acceptance-evidence.json`
is reserved for those real terminal conditions. Main source981cd97c...,12-CPU
training, accepted parent, original17:00/official-result gate and legacy
retirement remain unchanged. Code/storage acceptance, negative mechanism/latency
result, ongoing elapsed observation, delivery and prediction evidence remain
separate states. No test mail or report-delivery claim was introduced.
