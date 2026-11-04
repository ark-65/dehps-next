# Qwen4B activation and causal execution evidence

The owner paused this long-thinking workflow on2026-11-04. Its evidence remains
preserved; new activation work follows [the separate short-thinking contract](qwen4-short-thinking.md).

Owner authorization2026-11-04 permits activation after acceptance, superseding
the previous instruction to retain4B without automatic activation. The existing
mechanism and fixed comparison contracts, promotion/qualification gates and
draw-window rules remain unchanged.

The sole retained weight cache is `.next-qwen-review`, not the emptied
`runtime/inference` directory. Both inference configurations use the pinned
Ollama image, Vulkan, four helper threads, flash attention and q8_0 KV cache.
The frozen profile explicitly requests40960 context. Actual review execution
reported100% GPU residency and approximately6.9GiB container memory, exceeding
the former primary6GiB limit; the existing review16GiB safeguard is retained
for primary inference. Registration does not activate the selector.

Recovery links a new corpus to the original immutable cases and model profile.
Carry every performed semantic answer, including wrong/truncated answers;
retry only infrastructure voids with identical cases, layouts and seeds.
Physical failures must not consume the semantic futility allowance. Preserve
the original premature result rather than rewriting it into a pass. Require
all144 logical slots and independently recompute the existing four gates from
actual receipts before activation. A new inference-only context may preserve
the same requests when the old context belongs to a different controller
release; it must not run snapshot-excluded training jobs.

After the fixed24-pool comparison, switch only at a completed primary campaign
boundary. Import acceptance evidence append-only with source-local call IDs
and payload hashes; never import acceptance calls as primary execution.
Activate through `research_selection.activate`, which recomputes all mechanism
gates and checks for active frozen selection work. Preserve the one8-CPU
training allocation during any isolated comparison fits, and restore automatic
primary scheduling afterwards. Keep inference generation, semantic failures
and actual fitting counts separate from cached work.

Closed-loop acceptance requires a primary `QWEN_COMPARATIVE` audit linked to
a successful full-GPU provider call, the exact selected recipe in an evaluated
node with real parameter updates, and that node's persisted paired feedback in
a later actual Qwen request. Record call IDs, node IDs, recipe/input hashes,
parameter/optimizer digests and feedback keys. A loaded model, valid JSON,
fallback choice or inference-only mechanism pass cannot replace this chain.
Report sustained observation, mail delivery and predictive benefit separately.
