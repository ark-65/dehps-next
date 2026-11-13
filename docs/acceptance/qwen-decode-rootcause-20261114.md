# Qwen complete decode investigation

As of 2026-11-14 01:25 Shanghai, generation repair is not qualified or deployed.
The original source/profile remains active. This extends the retained negative
[Vulkan investigation](qwen-vulkan-rootcause-20261113.md); it does not replace
its failures or start a repaired-source observation clock.

## Completed cache control

Cold ABBA cells retained identical model weights, native/CPU/Vulkan binaries,
inputs, seeds, F16 versus q8 KV as the only factor, flash attention, poll0,
serialized submissions, batch512, context16K and output budgets512/1024.
Primary training retained twelve independent one-thread fitters; inference
retained four helper CPUs and full GPU offload.

| Cell | Cache | Actual logical seconds | Prefix / answer output tokens | Result |
| --- | --- | ---: | ---: | --- |
| A large, native91/92 | q8_0 | 550.8380 | 512 / 395 | Strictly valid |
| B small, native93/94 | F16 | 296.0323 | 512 / 237 | Strictly valid |
| B large, native95/96 | F16 | 493.5650 | 512 / 538 | Strictly valid |
| A small, native97/98 | q8_0 | 358.8281 | 512 / 279 | Strictly valid |

All four have complete actual two-phase provider counts, valid process/library/
environment bindings, full GPU offload, no matched process GPU fault through
teardown, no primary inference overlap and no operator interruption. The F16
mean is 394.79865s, exceeding 240s; its large cell exceeds 300s. The frozen
screen failed. Different generated work and hardware drift also prevent
interpreting the between-arm mean difference as a pure throughput effect.

The actual final provider receipts show generation taking 412.889937s of the
q8 large logical 550.8380s and 223.901018s of the F16 small 296.0323s, about 75%
in each. The earlier 179.348082s operator trace stopped during prefill and
therefore cannot describe the complete call's bottleneck. A proposed attention
on/off control was retained as NOT_RUN before any preparation or model call.

## Complete decode operator evidence

One known completing F16 small input ran once with the performance logger;
all ordinary execution settings above were retained. Native99/100 returned a
strictly valid answer with actual 512 prefix and 237 answer output tokens.
Instrumented logical latency was 331.2015s. Complete EOF capture contains 753
completed graph blocks; binary/library/environment and full-GPU bindings are
valid. Matched process GPU faults through teardown plus 30s, primary inference
overlaps and operator interruptions are all zero.

| Actual printed query shape | Blocks | Printed GPU-clock seconds |
| --- | ---: | ---: |
| Single query row | 747 | 237.8820297 |
| Batched query rows | 3 | 52.2813000 |
| Other / warmup | 3 | 11.7239150 |
| Total | 753 | 301.8872447 |

Within the single-query group, MUL_MAT_VEC accounts for 117.014169051s
(49.1900%), fused MUL_MAT_ADD 82.48902171s(34.6764%), and FLASH_ATTN_EXT
19.4064943s(8.1580%). The two matrix/vector categories together account for
83.8664%. This directs the next experiment toward quantized matrix/vector
implementation rather than another attention-only change or more rounds.

Graph counts are not provider token counts. Logger barriers and waits perturb
execution; printed intervals can include host submission gaps or waiting.
These are not uninstrumented speed, engine-busy utilization, CPU remainder,
qualification latency or proof that a particular shader was selected.

## Frozen matrix/vector direction

The exact [39febd2ad Vulkan source](https://github.com/ggml-org/llama.cpp/blob/39febd2ad/ggml/src/ggml-vulkan/ggml-vulkan.cpp)
uses Intel Linux MMVQ heuristics with an A770 tuning comment. The host is
integrated MTL. The next cold ABBA control changes only the presence of
`GGML_VK_DISABLE_MMVQ=1`; F16 KV and every other execution setting remain
fixed. Eligible operations then use a direct F16/F32-activation dequantized
matrix/vector path instead of the Q8_1-activation path. Quantized model
weights remain identical. Static eligibility and an environment variable
are not a runtime selected-kernel trace.

All four cells must finish without replacement. Both candidate cells must
be strictly valid, have complete actual counts and bindings, full GPU,
no attributed faults, overlaps or interruptions, each at most 300s and mean
at most 240s. Any matched control with complete provider counts, including a
wrong complete answer, must not be faster. Passing permits only a fresh
original 144-slot qualification. The original quality, futility, fixed 24-pool
comparison, source/profile certificate, deployment boundary and actual later
feedback requirements remain unchanged. This control is pending here.

## Baseline, hardware and observation limits

The original qualified144 slots already used 512 thinking output tokens each.
One exact small-context prefix has the same output hash and 1224/512 input/
output counts: original qualification source call 6964 generated the prefix
in 107.935334s; current diagnostic prefix 98 took 160.409549s. Call 6964 here is
the original qualification's source ID, not the current primary call ID.
Execution settings and hardware state differ, so this excludes a larger
thinking budget as the explanation without assigning a single cause.
The corpus date or profile registration time does not prove the original
inference kernel version.

Intel's [optimization-guide table](https://www.intel.com/content/www/us/en/docs/oneapi/optimization-guide-gpu/2025-2/intel-xe-gpu-architecture.html)
and [AI-engine article](https://www.intel.com/content/www/us/en/support/articles/000098346/graphics.html)
conflict about usable matrix engines for this family. Actual host OpenCL
metadata reports NEO 26.05.037020, 128 compute units, subgroups 8/16/32 and
integer-dot-product support, but no matrix-multiply-accumulate extension.
Neither a usable XMX path nor container SYCL speed has been demonstrated.
No alternative engine was installed or activated. No driver, power, fan,
clock, watchdog, thermal or perf-access policy was changed.

Scoped primary calls 7040–7076 contain 19 terminal calls: all 17 failures have
same-PID, in-call watchdog events; the two successes do not. PID start ticks
and kernel capture boundaries are bound, with no capture gaps. This remains
an observational association, not exact downstream driver causality or
retroactive attribution of the original 341.4498s call.

Original-source observation deadlines remain intact. The actual 920.534550s
fit gap still fails 900s, regardless of periodic zero-warning summaries.
A repaired source/profile needs its own full 24h and actual fit-marker audit;
old hours cannot count. Main training continues, draw-day 17:00 pause and
complete-official-verification-only resume remain. Legacy DEHPS is untouched.
Delivery, repaired live feedback closure and predictive improvement are
separate evidence states and are not claimed here.
