# Short-output loop rejection and certified new-task recovery

This is an operational repair for the already qualified Qwen4B profile. It does
not change model weights, prompts, schemas, sampling,512/1024 token budgets,16k
context, full-GPU requirements,1800-second/20-feedback advice cadence or any
mechanism, comparison, latency, prediction-promotion or probability gate.

## Failure and output handling

Production call6978 exhausted1024 answer tokens after a degenerate thinking
prefix. The previous streaming guard required2048 characters before recognizing
eight identical256-character blocks. A bounded short prefix could therefore
finish with a loop undetected, and the next phase would consume it verbatim.
The selection error was then latched indefinitely with no retry timestamp.

The additive short guard detects long consecutive character units and long
lexically collapsed tails, including punctuation-separated repeats. It runs on
partial provider output and again on the completed native prefix before answer
generation. It rejects rather than edits the prefix or model answer. No oracle
selection, forced utility, malformed-JSON repair, resampling of a failed semantic
case, token increase or estimated usage is introduced.

Partial output remains durable evidence with unknown token counts when the
provider never supplies a final receipt. If a final receipt exists, record it
before rejecting the output. Preserve already-persisted stream and thinking-call
metadata when an outer call fails; do not overwrite that evidence with only an
exception code. The existing long-repeat guard remains as an additional check.

## Certificate and recovery

An immutable operational certificate is specific to the exact repair source and
accepted profile. Its verifier recomputes the original144-slot quality and
latency gates, replays all recorded native thinking/answer outputs, requires no
previously valid answer to be newly rejected, preserves the original incorrect
slots, and requires detection of the actual production failure. This is output
replay and compatibility evidence, not144 new model calls or a new model
acceptance. No model configuration is activated or re-activated to clear a lock.

Only output-quality failures are eligible: truncation, demonstrated repetition,
invalid local reply or invalid comparative selection. Model/context identity,
GPU, mechanism and aggregate position-bias holds retain their existing gates.
A certificate alone cannot clear a reason or start inference.

Behind the original job lease and official-result gate, record an append-only
recovery audit and set a not-before timestamp at least1800 seconds after the
failed attempt/last scheduled advice. Keep the failure reason latched. The next
probe must be a genuinely changed task and must still have20 fresh comparable
training outcomes. Renaming or reordering IDs does not change the task identity.
The failed task is retained, never retried as a physical void. Failed new tasks
receive their own failure audit and subsequent cooldown, not an artificial
lifetime/daily usage cutoff. Ordinary CPU research uses its feedback-value
fallback between qualified Qwen advice requests.

Only a later successful native two-phase Qwen selection, with matching profile,
job/attempt, GPU/token receipts and QWEN_COMPARATIVE audit, can clear the reason.
Its creation time must follow the failure and cooldown; a historical success,
fallback, running service, certificate or watermark cannot clear it. Successful
selection, per-node feedback acknowledgments and recovery audit commit behind
the same fence. Success is still not predictive improvement.

The owner-requested final acceptance requires both actually selected candidates
to train with real parameter updates, followed by their exact outcomes in the
same later successful actual Qwen request with individual delivery receipts.
Use `scripts/verify-qwen-feedback-closure.py`; preserve all failed/partial chains.
Do not call certificate replay or a single successful inference a closed loop.

Future normal report payloads include a separate factual Qwen health line:
protected hold/fallback, last actual selection success and the draw-window state.
Token totals remain unmodified. Previously sealed/sent mail is immutable; no
test or duplicate mail is sent. Existing training recovery logic is unchanged;
Qwen-specific handling lives separately in `qwen_recovery.py`.

Deployment waits for complete authoritative result verification and a completed
campaign boundary. Retain the accepted parent and numeric contract, then adopt
the controller-only release. Keep the existing12-CPU shared training cap,
CPU0–19 pool, host CPU20–21 and inference topology. No legacy services/data,
dashboard, new unit tests or CI are involved.
