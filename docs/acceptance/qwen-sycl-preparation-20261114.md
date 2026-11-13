# Isolated SYCL application preparation

The existing application rejected the `sycl` backend setting and applied its
full-GPU receipt check only to `vulkan`. The candidate application accepts
`sycl` and requires the same actual resident-model GPU size and context checks.
The default backend and primary deployment remain unchanged. This is preparation
for the next matrix/vector implementation investigation, not a generation fix
or an activation authorization.

An actual Python3.12.13 container started this source, validated the original
CPU0–19 and one-thread numerical contract, and read the named
`dehps_next_qwen_latency_20261113` database in a read-only transaction. Source
identity is `2da65a93c516edfe2a14ccff73c291ff04b762cd18ed1ca35dc7866cd5084a75`;
numeric identity remains
`9cbb1aaf437410dce1dbe24d38cbebca2b2018cd2723ebeb757b3f3917ac2b06`.
The validation generated no model calls, fits or database mutations and had no
GPU devices. Hardware detection, actual SYCL execution and partial-offload
rejection with that execution stack still require live verification.

The first startup probe failed because its expected guard fingerprint was
copied from the parent source. The guard fingerprint covers
`research_agent.py`, so the new GPU branch correctly changes it to
`c0ba20597f8d5e0649a4a95a02d9d060a4a509be0ee45a7e01610d314ef9fa8d`.
That failure is retained; the second probe independently matched the exact six
guard source files. No guard logic or acceptance threshold was weakened.
The old source/guard certificate cannot be reused.

The separately frozen native build uses the same llama.cpp revision
`39febd2adb947b70da35e95f9351b3bf58ad170a`, a digest-pinned Intel SDK, one low
priority CPU and4GiB, without GPU devices, model mounts or database credentials.
It waits for all four current matrix/vector control cells to finish and fail;
a passing parent makes it NOT_RUN. Primary inference, resource safeguards and
the draw pause take priority over compilation. The source's SYCL backend
documents quantized matrix/vector reorder paths, but neither usable XMX nor
speed on this host is assumed. Host driver and power policy remain untouched.

Build success alone permits no deployment. Actual GPU/library/driver bindings,
the original fresh144-slot quality and latency qualification, fixed24-pool
comparison, scoped certificate, completed-campaign transition, real selected
training outcomes in the later Qwen request and the final source's own full24h
remain pending. Primary training, draw-day17:00 pause, official-verification-only
resume, retained improvements and legacy DEHPS boundaries remain in force.
No new unit tests or CI were added.
