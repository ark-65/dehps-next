# Qwen Vulkan degradation and operator-cost investigation

This is a negative diagnostic result and a frozen next direction. Generation
repair, a new qualification, deployment, live feedback closure and a repaired
source's full 24-hour observation remain pending. All original failures and
observation clocks are retained.

## What the actual controls establish

Cold-process controls use the same native executable, CPU/Vulkan libraries,
Qwen4B weights, inputs, seeds, 16K context, 512 thinking/1024 answer budget and
512 batch. Primary training retains 12 independent single-thread fitters;
inference retains full GPU offload and four helper CPUs. Known cases are
development regression, not independent qualification or forward evidence.

| Contrast | Actual outcomes | Conclusion |
| --- | --- | --- |
| Poll50 versus poll0 | Poll0 small valid 295.8756s; poll0 large repetition 191.6012s with 17 matching watchdog events. Poll50 large repetition 241.3910s; small invalid 832.3420s. | Lower helper CPU consumption did not resolve generation failures or the original mean-latency gate. |
| Default versus serialized submissions, both poll0 | Serialized small valid 314.6045s; serialized large no-output failure 180.0628s, neither with matching in-call GPU faults. Default large invalid 891.4775s with 11 events; small valid 349.2245s. | Serialization alone did not meet quality/latency requirements. Zero matched faults is insufficient. |

Each cell is terminal and retained. The invalid 832.3420s and 891.4775s
answers have complete provider counts; they must not be described as missing
counts or successful speed samples. The two 180-second prefill failures have
unknown final provider counts; intermediate prompt progress cannot fill them.

For the uninstrumented serialized large case, the actual model loaded all
37 layers and progressed through 3072 of 3532 prompt tokens at 162.51s before
the original 180-second no-output protection aborted it. This was full-GPU
prefill work, not a metadata-only model-loading or CPU-discovery failure.

In the separately scoped primary calls 7040 through 7062, all ten failed calls
had matching same-process watchdog events inside their call windows; neither
of the two successful calls did. This is an observational association. It does
not establish the exact downstream driver propagation or retroactively
attribute the original 341.4498s call, whose matching kernel evidence was not
retained. That call's measured extra time includes slower generation of the
same thinking budget and 124 additional answer tokens.

## Actual operator instrumentation

A separate, cold, known large input ran once with poll0, serialized submissions
and the Vulkan performance logger. Native calls 89/90 failed under the original
180-second no-output guard. Eight completed graph timing blocks and the complete
32,545-byte live log were retained. There were no matched process GPU faults
through backend teardown plus 30 seconds, no primary inference overlap and no
operator interruption. Actual binary/library/environment and full-GPU bindings
were valid.

| Completed instrumented work | Printed GPU-clock seconds | Fraction of printed total |
| --- | ---: | ---: |
| FLASH_ATTN_EXT | 103.062729 | 57.4652% |
| MUL_MAT | 61.6819125 | 34.3923% |
| MUL_MAT_VEC | 11.49032892 | 6.4067% |
| All printed graph blocks | 179.348082 | 100% |

The logger inserts barriers and waits. These intervals can include waiting or
host submission gaps, include completed loading/warmup work and omit unfinished
aborted graphs. They are not uninstrumented speed, whole-call GPU utilization,
CPU remainder, final token usage or qualification latency. Nevertheless, the
actual attention cost motivates a targeted cache-path experiment instead of
another arbitrary increase in rounds.

## Source-constrained next direction

The exact native version is llama.cpp `39febd2ad`. Its Vulkan source excludes
Intel Xe1 from the quantized-KV-to-F16 scratch path. Xe-specific attention
also requires native F16 KV and additional platform/shape conditions. Crucially,
the same source allows Xe1 cooperative matrices only with the proprietary
Windows driver. F16 alone therefore cannot be credited with enabling that
optimization on this Linux/Mesa platform; selected kernels were not traced.

Read-only host properties identify integrated MTL device `0x7d55`, minimum
subgroup 8 and accelerated packed integer dot product, which match the source's
Xe1 classification. Host userspace Mesa 26.0.8 differs from the actual inference
container's Mesa 25.2.8. Host metadata is not a substitute for a container-bound
driver measurement. Neither host drivers nor power, fan, clock, watchdog or
thermal policy were changed.

The next study freezes cold ABBA cells for q8_0 versus F16 KV alone. Both arms
retain poll0, serialized submissions, flash attention and all other contracts.
Actual `--cache-type-k/v`, process environment, CPU library, GPU offload and
memory use must bind to each arm. Increased F16 memory must fit the existing
physical/container limits; CPU or partial offload is a failure.

Both F16 cells must be strictly valid, have complete two-phase counts, no
attributed GPU fault, overlap or interruption, individual latency at most 300s
and mean at most 240s. A complete matched q8 control must not be faster. This
permits only a fresh original 144-slot qualification, never activation. The
original quality, futility, fixed-24 comparison, deployment-boundary and
actual later-feedback requirements remain unchanged. There is one attempt
per cell; performed failures are never replaced.

## Long observation and training integrity

The original source's observation windows retain their actual deadlines. The
first has a 944.539696s sampling gap, exceeding the original 600s limit. Actual
fit-marker auditing also found a 920.534550s training gap, exceeding 900s,
even though periodic samples reported no stall. The latter was caused by two
temporary library-probe symlinks tripping host-accounting integrity protection;
their metadata was retained and only those owned links were removed. No link
target, safeguard or primary training service was changed to hide the failure.

A terminal periodic sampler cannot override these failures. A changed repair
source/profile needs its own full 24 hours and actual fit-gap audit; old hours
do not count. Main training continues, draw-day 17:00 pause remains, and resume
requires complete official result verification. No legacy DEHPS execution,
code, data, model or mount was touched. Mail delivery and predictive improvement
are separate, unclaimed evidence states.
