# Bounded GPU submission diagnostic

Date:2026-11-13. This is a four-attempt causal diagnostic while primary CPU
training continues. It does not replace the frozen144-slot revalidation,
qualify a new backend or activate a profile.

Native timing establishes that call6982's341.450 seconds consisted almost
entirely of187.095 seconds of thinking provider time and154.321 seconds of
answer provider time. More output and slower observed generation account for
the difference from call6980. The original144-case workload was smaller:
mean thinking input1,343.75 tokens and answer output250.15, compared with
3,560 and592 for call6982. Do not apply the small-case latency distribution as
a guarantee for six-candidate production requests.

Retained kernel evidence covers the original call window and shows no matching
fence events during that call. Later `llama-server` i915 fence-expiration events
are a separate instability lead, first observed at2026-11-12 23:07 Shanghai.
[Upstream reports](https://github.com/ggml-org/llama.cpp/issues/27634) describe
similar queue-watchdog symptoms and a container-local submission-serialization
workaround. Those reports motivate an experiment; they do not prove this
host's cause. Do not widen/disable the host watchdog or reset the desktop GPU.

## Frozen four attempts

Use the two exact previously successful production logical requests6980/6982,
including every candidate, evidence item, schema, seed and original input hash.
These are declared known-input runtime regressions, not fresh predictive cases.
Reconstruct and verify each complete request before generation.

| Order | Trial | Original input | Review backend |
| --- | --- | ---: | --- |
|1|a0|6980|Default submissions|
|2|b2|6982|`GGML_VK_SERIALIZE_SUBMISSIONS=1`|
|3|b0|6980|`GGML_VK_SERIALIZE_SUBMISSIONS=1`|
|4|a2|6982|Default submissions|

Both conditions use the same pinned Ollama image, retained4B weights, Vulkan
full offload,16k context,512/1024 token budgets, sampling and four helper CPUs.
Start a fresh isolated review-backend process for every attempt. Only the
submission environment variable changes. Its serialized condition has an
explicit extra backend-profile field; never silently label it as the original
execution configuration. Verify the actual runner environment and image.

The current numerical identity,12 origin processes/one Torch thread,12-CPU
training quota, CPU0-19 placement and accepted parent are unchanged throughout.
The review services mount only the retained Next model cache read-only. They
remain stopped outside each trial. Never overlap an intentional probe with
production inference; keep the existing idle/resource policy,900-second
primary headroom and official-result gate. Require the primary model to be
unloaded before a cold review trial. Any actual overlap invalidates attribution.

Each cell gets exactly one attempt. Preserve invalid answers and physical
voids; do not resample a cell to obtain a good answer. Existing strict selection
validation, native/partial token accounting and actual lease/resource fencing
remain in use. Record raw provider error frames before unchanged classification.

Support the targeted hypothesis only if both serialized cells are valid, have
no new attributable GPU fence/hang events, and improve both paired logical wall
times. Otherwise reject it or report insufficient evidence. Four observations
cannot establish the original latency/quality gates or long stability. Any
candidate pursued next needs its own new full frozen qualification; no diagnostic
answer is reused as a qualification slot.

Primary mail, advice cadence, draw-day17:00 pause and official-verification-only
resume remain unchanged. No legacy access, unit tests, CI, dashboard, test mail,
primary model swap or main-service recreation is part of this diagnostic.
Private manifests, actual native responses, runner environment, kernel events,
overlap checks and results stay outside Git under the named runtime operation.
