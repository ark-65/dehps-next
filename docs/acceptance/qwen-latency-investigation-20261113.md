# Qwen latency investigation and provider-error repair

Date: 2026-11-13. Status: investigation and recorded-error integration replay
completed; original144-slot latency regression and new elapsed24-hour primary
observation remain pending. This document is not a successful requalification,
completed soak, production deployment or predictive-improvement claim.

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
