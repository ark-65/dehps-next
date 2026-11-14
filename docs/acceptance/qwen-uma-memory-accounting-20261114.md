# Account for available unified memory within the actual container budget

At pinned llama.cpp revision `39febd2adb947b70da35e95f9351b3bf58ad170a`,
the selected Intel integrated GPU reported only 785 MiB free during automatic
model placement although the host had about 23 GB available and the model
container had an 8 GiB hard limit. The actual run reached health readiness
but placed zero of 37 model layers on GPU. That failed full-offload result
remains preserved; readiness alone does not establish the intended backend.

`patches/llama.cpp/39febd2-uma-available-memory.patch` adds explicit
`GGML_SYCL_UMA_AVAILABLE_MEMORY=1` accounting for a device that reports both
GPU and host unified memory. It reads actual `MemAvailable`, `MemTotal`,
`memory.max` and `memory.current`; effective total is the lesser of device
total and the finite cgroup limit, and effective free is the minimum of that
total, host available memory and nonnegative cgroup headroom. Missing,
unbounded or inconsistent observations return failure, which the pinned
caller propagates to its existing fatal memory-query check. Unset or zero
keeps upstream accounting; any other explicit value refuses the query.
This neither disables automatic fitting nor treats total RAM as free memory.
The existing 8 GiB container and host resource-admission guards remain.

The patch SHA256 is
`2b6bff1df567e118ea3e64be2010194ab2222ec08670140789f05480fa402543`.
Upstream `mem.cpp` SHA256 is
`c3298bfa2c086c7a9e148e5b16fd350f1c21e059bc4e145971e3da359d7db5ee`;
patched SHA256 is
`4d783a218649c153ba71cbafcaea777d4e312ffb600932ee8a6118bc7d0bb9dc`.
The already merged MTL MMVQ capability patch is applied separately.

The real isolated Intel 2026.1.1 MTL AOT build completed on November 14 at
15:11 Shanghai time with exit zero and no container OOM. A probe linked the
actual compiled memory object and queried the real GPU: it returned
8,550,162,432 bytes free and 8,589,934,592 total, using actual host available
memory 23,135,907,840 and cgroup current usage 39,772,160. This host-function
probe submitted no device compute kernels and receives no model credit.
A separate Python 3.12 CPU-container audit checked actual native budget logs,
image identity, 8 GiB/4-helper-CPU limits and the later full-37-layer warmup.

The first full-layer warmup was stopped by the original memory-pressure
threshold and remains failed. After a separately frozen synchronous
allocation change, real warmup completed in 11.340345 seconds with 37/37
layers, no pre-stop native errors, no matched kernel fault and no OOM.
All four subsequent semantic diagnostic cells completed with strict output
validation and complete two-phase counts. The candidate took 248.1991 seconds
on the small input and 430.5316 on the large input: its 339.36535-second mean
and large-input latency failed the unchanged 240/300-second admission limits.
That direction did not advance to fresh 144-call qualification.

This repairs physically bounded memory accounting and demonstrates actual
full offload. It does not establish a latency repair, accepted mechanism,
predictive benefit, primary deployment, real feedback closure, repaired-source
24-hour pass or the cause of the owner's whole-host freeze. The original
failures, gates, main twelve-process CPU training, draw-day 17:00 pause and
official-result-only resumption remain. No unit tests or CI were added;
legacy DEHPS was untouched. Runtime receipts and model files are not committed.
