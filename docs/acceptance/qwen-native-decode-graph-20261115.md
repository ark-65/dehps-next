# Opt-in native execution stack and cold-slot evidence

The fenced-prefill execution stack produced valid replies with complete token
counts and full37-layer offload in all four matched diagnostic cells, but failed
the original latency gates. Its small and large candidate calls took169.4203 and
506.9913seconds; their mean338.2058 exceeds240. The two provider decode durations
for the large input alone sum to355.982416seconds, above the300-second whole-call
limit. Faster prefill alone cannot make that recorded call pass.

The new experiment keeps the original Vulkan controls and unchanged inputs,
seeds, ABBA order,512/1024 generation budgets,16K context,512 native batch and
microbatch,4 helper CPU,12 training CPU,8GiB limit and full37-layer GPU requirement.
It tests an explicit execution-stack change: LevelZeroV2/async submission and
command graphs for single-token decode, with the original queue and compute-group
fences for multi-token prefill. This cannot identify a single changed factor.

Apply these patches in order to official llama.cpp revision
[`39febd2adb947b70da35e95f9351b3bf58ad170a`](https://github.com/ggml-org/llama.cpp/tree/39febd2adb947b70da35e95f9351b3bf58ad170a):

1. `patches/llama.cpp/39febd2-mtl-mmvq-xmx-aot.patch`
2. `patches/llama.cpp/39febd2-uma-available-memory.patch`
3. `patches/llama.cpp/39febd2-fp32-vector-dispatch.patch`
4. `patches/llama.cpp/39febd2-prefill-node-fence.patch`
5. `patches/llama.cpp/39febd2-decode-only-graph.patch`

The FP32 patch retains K-quant F32 activation dispatch and stages overlapping
fused-GLU output. The prefill fence is opt-in. The decode-only patch preserves the
original refusal when its flag is absent and asserts that fenced prefill is not
being recorded. It changes no mathematical kernel body or graph replay body.
The combined `ggml-sycl.cpp` SHA256 is
`b83d2115556c651cf79959a2656e1c83d4986f8267da1fc2028fa037ca898059`.
An independent source-only application of all five patches to the official three
source files reproduced the exact built hashes, without model calls or binaries.

The isolated Intel2026.1.1 MTL build completed with exit0 and no OOM on November15.
Its SYCL library SHA256 is
`fc43f9786ee5ba281ddf30659afcfb428dc5dad4fa6ebff9fbe35cdf2b2596d3`.
The two new-source hardware warmups completed with full37-layer offload, exit0,
complete traces and no matching kernel/runtime error. Independent arithmetic and
process binding verified the actual8GiB budget,4-helper quota, configured native
batch sizes and six process environment flags. The single-token trace contained
1809 completed direct launches and1295 kernel instances inside successfully
finalized/enqueued graphs, including575 F32 Q4 and142 fused-GLU instances, with
zero unknown identities. Append alone is not execution. The configured512 warmup
used the native two-token startup workload; it is not a real512-token semantic
prefill or a latency result.

The prospective four-cell screen is incomplete. Its first Vulkan control was
strictly valid at297.382seconds. The following candidate was interrupted at
30.3744seconds when a10-second Docker-exec binding observation timed out and
triggered cleanup. No stream bytes or provider token counts had been observed;
this is not a valid fast reply, natural model completion, or a proven native
fault. Later cells,144 qualification and48 fixed comparisons did not run. A
separate synthetic real-prefill diagnostic investigates process startup and
resource scheduling without retrying or reclassifying this screen.

These source and hardware results do not establish normal-call speed or quality,
profile activation, deployment, actual feedback closure, or its own24-hour
observation. Each requires its original independent evidence.

No application/profile activation follows from this document. Old failures and
observation clocks remain intact. No new unit tests or CI are added; legacy DEHPS
remains retired and untouched.
