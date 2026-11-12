# Qwen output and recovery repair: pre-deployment acceptance

Date:2026-11-12, Asia/Shanghai. Code/isolated acceptance is complete; production
deployment and the new actual closed loop remain pending official-result
verification. This record does not claim a repaired live chain in advance.

## Original failure

Last successful production selection: call6976, audit22325,2026-11-10 13:26:09.
Failed attempt: call6978, audit22388,2026-11-10 14:01:03. The answer used1024
tokens and ended with `done_reason=length`. The actual thinking prefix contains
short repeated material, then the answer degenerates. Selection state remained
`LOCAL_MODEL_TRUNCATED` with `retry_after=NULL`. On November12 all1,547 selection
audits before17:00 were feedback-value fallback; no Qwen provider call occurred.
The historical58 missing-token records are not today's calls or an admission
quota. The current5878 program correctly entered its17:00 draw pause.

The repair rejects short loops before they poison the next phase, preserves
native/partial receipts, and supports certified new-task recovery without
clearing the error first. See `docs/architecture/qwen-output-recovery.md`.

## Native-output replay

Replayed the accepted profile's complete144 actual recorded slots. All141
previously valid outputs remain accepted by the added guard, and all three
original invalid cases remain preserved. The actual failed prefix is detected
at character285 of869; this is a character location, not an estimated token count.
The raw prefix/answer and original semantic failure are retained.

Recomputed original mechanism metrics remain semantic accuracy0.944444,
feedback lift0.472222, recipe stability0.875 and first-position fraction0.347826.
All144 actual latency receipts remain complete, mean155.213 seconds and
p95203.339 seconds, with the original240/300 limits. Gates were not relaxed.
This is immutable actual-output replay, not new inference, and does not replace
the original frozen study or manufacture new144-slot acceptance evidence.

## Isolated real application/PostgreSQL checks

The Python3.12 CPU application and named isolated Next PostgreSQL acceptance
verified the following without a provider call or SMTP operation:

- The real application cannot claim a planning task during the current17:00
  pause; arming recovery during the same pause leaves the error unchanged.
- At an actual historical officially verified window, recovery records a probe
  schedule while leaving the original error latched.
- The same failed task and an ID-renamed/reordered copy are rejected. A genuinely
  changed context still has to pass the existing cadence and new-feedback gates.
- Zero fresh training feedback blocks; the unchanged1800-second interval blocks.
- A pre-failure successful call cannot clear the current fault.
- In an explicitly constructed isolated prior-failure timeline, imported actual
  successful two-phase native receipts clear the lock atomically. This is a
  state-machine check, not a new live Qwen success or feedback chain.
- A model-digest fault remains a hard hold. Future mail health previews expose
  the protected state, last real success and draw pause; no mail was queued.

An initial isolated fixture omitted the required attempt worker field; that
transaction rolled back and the fixture was corrected. During review a new
module name collided with existing training recovery; it was separated before
deployment, and the original tracked training-recovery file is byte-identical.
Final certificates and acceptance must match the final installed source hash.

Docker's cached CPU count rejected a NanoCPU-based12-CPU temporary container.
A real Next-only quota-encoding check returned `cpu.max=1200000 100000`, preserving
the accepted12-CPU cap without restarting Docker or affecting other services.
Deployment may use that equivalent explicit period/quota encoding; it must not
lower training allocation or widen it.

## Production and final acceptance still required

At pre-deployment capture2026-11-12 17:43, the program remained at5878 in
`PAUSED_DRAW_WINDOW`, today provider calls remained0 and the Qwen error remained
latched. The already-sent2026130 PRE_FINAL digest is
`9bbcca2c4437bb50141b5e55c6ef4fc48851c6c56650a03355080c5e14032622`.
Do not rewrite or resend it.

Wait for the complete official receipt, drain the active frozen campaign, adopt
the numerically equivalent controller release and observe the actual repaired
selection. Freeze both selected node identities and their real training receipts,
then require exact results in one later successful actual Qwen request plus
per-node acknowledgments. Append a separate final acceptance record when that
proof exists. Main training must continue between advice requests, subject to
the normal draw pause. No predictive gain, inbox delivery or24-hour soak is
established by the pre-deployment checks.

Private runtime evidence, excluded from Git:
`runtime/operations/qwen-recovery-20261112/` contains immutable-source exports,
replay certificate, final isolated acceptance, original/final source identities,
sealed-report snapshot and subsequent deployment/closed-loop receipts.
