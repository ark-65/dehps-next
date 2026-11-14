# Respect the frozen native target's XMX capability

The llama.cpp revision `39febd2adb947b70da35e95f9351b3bf58ad170a`
sets `GGML_SYCL_XMX_AOT_SG=0` for the selected `mtl` AOT target, but
`mmvq.cpp` still instantiates its XMX kernels when the Intel compiler and
ESIMD header are present. The actual offline compiler rejected the resulting
`llvm.genx.dpas` intrinsic for XeLPG. Runtime dispatch excludes this target
from that XMX path; a runtime condition cannot prevent unsupported instructions
from being compiled into an AOT image.

`patches/llama.cpp/39febd2-mtl-mmvq-xmx-aot.patch` makes the local MMVQ
capability macro respect the existing explicit zero AOT setting. It preserves
ordinary non-XMX ESIMD matrix/vector kernels. Builds with an undefined or
nonzero AOT setting retain the upstream selection. It changes no application
recipe, prompt, model weight, acceptance gate or host driver setting.

The patch SHA256 is
`d331ef9e418c77b5f602bab40fe62f7f401cec9befe623aade3674b7284b22a0`.
The expected upstream file SHA256 is
`3fb54fac721c0898205cbe0584455d98bae1007903a86fd21b3660c43a7ffebf`;
the patched file is
`7b8e0b9e2b4c6de9b5a3d6e82ee8451cad221105f385bfc82cab82c4b9cb3fc2`.
The actual source workspace reports only that file modified.

Actual Intel compiler 2026.1.1 preprocessing with the frozen target setting
selected XMX before the patch and excluded it afterward; ordinary DMMV ESIMD
remained selected in both. The real isolated build targeted `mtl` / offline
device ID `12.70.4`, retaining F16, oneDNN, graph support and disabled host-memory
fallback. It ran with two low-priority CPU, 4 GiB memory, one link job, bounded
scratch, no GPU devices, no model mounts, no database credentials and no network.
Primary training retained its aggregate twelve CPU and original draw guards.

The owner reboot interrupted the first patched build; that outcome remains
separate. Recovery of the same patched workspace finished on November 14 at
12:09:38 Shanghai time with container exit zero and no container OOM. Its
complete compiler log contains 209 `Build succeeded.` messages and the final
`llama-server` target, without the previous unsupported-DPAS diagnostic. The
produced native executable SHA256 is
`426640d72a6a1b81513f7043b3a30cd8d25e907d9f9d69da6050c6a4159b0a00`;
the SYCL library SHA256 is
`891fb74219ed58a27d95f18f224ed8c4dedd4eb0535ab66ed5a6ddaf4058a506`.

The following metadata export initially failed because its assertion still
expected the previous output directory. That script failure and the five
zero-call downstream NOT_RUN records were preserved. An independent bounded
regular-file export verified the completed container and recovered only its
five metadata files; it did not recompile or export library links onto the
host. The same frozen downstream stages were explicitly resumed after a real
Next clone query confirmed zero calls in their namespaces.

This establishes a native compilation repair only. It does not establish
startup readiness, generation correctness or speed, a cause for the whole-host
freeze, new 144-call qualification, fixed24 comparison, activation, real feedback
closure or a repaired-source 24-hour pass. Those stages require their own actual
receipts under the original gates. All failed studies and old observation clocks
remain intact. No new unit tests or CI were added; legacy DEHPS was untouched.
