# Qwen repeated generation: matched batch diagnostic

This is a new causal diagnostic, not a replacement for the failed original
144-slot study, its15 performed repetition failures, the mixed1024 submission
matrix, or the incomplete retained-runner comparison. None receives new credit.

Actual production call7040 failed with repetition after597.0504 seconds. Its
observed llama-server PID2711982 used batch/ubatch512, four helper threads,
16k context, flash attention and q8_0 KV. Eleven i915 fence timeout events match
that PID in the call interval. Provider prefill progressed through2048,2560,
3072 tokens at29.38,49.51,69.58 seconds: successive approximately20-second
plateaus. This motivates a GPU queue/batch hypothesis. It does not establish
that every repetition, or the earlier341-second call, had the same cause.

Freeze `qwen-batch-causal-20261113-v1` before any new generation. Use the exact
logical inputs of production7040 (six choices) and isolated23 (three choices).
Verify their source context/schema and original logical payload hashes first.
Explicit batch/ubatch512 is A;128 is B. All other options, seeds, weights,
backend, CPU topology and strict response validation remain unchanged. Start a
fresh isolated backend for each cell, ordered A-large, B-small, B-large,
A-small. Four cells only; no retry or resampling, including physical failures.
Known-input results remain development evidence with zero qualification credit.

Admission retains the original desktop/resource rules, a fresh primary snapshot,
no primary inference, at least900 seconds until the next primary call, and
natural primary model unload. Main12-CPU training continues. If primary headroom
falls to60 seconds, a primary call becomes active, the draw pause begins or
monitor freshness is lost, stop only the isolated client/backend. Preserve that
cell as operator interruption, without a successful latency sample or retry.
This preemption is scheduling protection, not a relaxed model acceptance rule.

Persist actual process identities/arguments, full-GPU model placement and kernel
evidence during generation and immediately after it. Persist the native result
before result-ledger postprocessing. A missing report never authorizes another
model call. Missing binding, overlap or observer gaps cannot be inferred away.

Advance only if at least one512 cell reproduces repetition or an attributed GPU
fault, both128 cells return strictly valid complete two-stage native receipts,
both have actual128/full-GPU binding without new attributed faults or primary
overlap, both walls are at most300 seconds and their mean is at most240 seconds.
Any completed512 counterpart must not be faster. Interrupted/failed512 cells
cannot establish a complete paired speed ratio. These diagnostic conditions only
permit a fresh144-slot qualification; they never authorize activation themselves.

The fresh qualification must retain the original accuracy0.90, stability0.80,
first-position fraction0.50, feedback lift0.20, all144 complete latency samples,
mean240/P95300 gates and original futility rules. Activation additionally needs
the proper source/profile recovery certificate, completed campaign boundary and
actual candidate-training/next-call feedback evidence. No threshold, token
budget, training load or hardware watchdog is relaxed.

Original24-hour clocks and failures remain immutable. The current primary-source
observer ends no earlier than2026-11-14 11:14:50.976635 Shanghai. It cannot certify
a later repair epoch; a changed source/profile needs its own completed24 hours.
The17:00 draw pause and complete official-verification-only resume stay in force.
Legacy DEHPS, mail delivery and predictive claims are outside this diagnostic.
