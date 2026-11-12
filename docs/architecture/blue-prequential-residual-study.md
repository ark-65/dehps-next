# Frozen prequential blue residual study

This is a bounded Next-only research direction, not a production model change.
The accepted parent, canonical red Top100, all historical failures, original
qualification thresholds and current main training remain intact. No legacy
data or services are accessed.

## Question and diagnosis

Positive uniform shrinkage cannot change a blue ranking:
`q_i-q_j = alpha*(p_i-p_j)` for `alpha>0`. It can improve probability loss but
cannot improve Top1 hits. The older 500-origin calibration explicitly preserves
these rankings; unchanged hits are the expected result of that contract.

The failed third block's errors concentrate in a small number of weakly
shrunk misses. Its fixed-model prior64 selector also evaluates a different
forecast sequence from the actual per-origin-refitted parent. Matched rolling
prior64 counterfactuals are informative diagnosis on already inspected data,
not independent acceptance or a reason to change thresholds.

The new hypothesis is narrower: persistent per-number forecast residuals may
carry usable historical ranking information beyond a scalar shrinkage and
simple frequency. A shifted-label control tests whether any apparent benefit
requires correct label alignment.

## Frozen comparison

Before new scoring, the study registers the complete driver hash, pinned
accepted-parent snapshot and original scores/anchor/data references, current
numerical identity and three chronological protocols in Next PostgreSQL.
The phases are earlier origins1525–1624 and1625–1724, plus the parent's exact
current100 with nested50 and10. The diagnostic failed block is excluded from
acceptance. These are predeclared historical comparisons; none is advertised as
protected, independent of prior project research, or forward evidence.

At origin t, the scalar control chooses alpha from the original six values
0.05/0.1/0.25/0.5/0.75/1 using only actual past out-of-sample forecasts and labels
on [t-64,t). Each forecast at j was fitted only on labels before j. This removes
the fixed-model/rolling-refit mismatch from the new scalar comparator.

One candidate and four controls are frozen:

- Scalar: apply that alpha uniformly to the parent. Top1 must be unchanged.
- Aligned residual candidate: initialize16 biases at zero, then make one
  chronological pass over the64 prior forecast/label pairs. With q the scalar
  probabilities, update `b -= 0.05*(softmax(log(q)+b)-onehot(y)+b)` and center b.
  The L2 coefficient is1. Predict `softmax(log(q_t)+b)`.
- Rotated negative control: identical update and inputs, but use `(y+1)%16`
  for every past training label. It is never an eligible replacement candidate.
- Frequency100: `(prior100 count + 20/16)/120`, with the parent's red output.
- Uniform: exactly1/16 for each blue number, deterministic existing Top1 tie
  convention, with the parent's red output.

There is no residual learning-rate/regularization search, outer-label fitting,
extra epoch extension, retry of negative results, or selection of the best arm.
Alpha choices, per-origin prior references, actual bias weights, gradient steps
and before/after digests are persisted immutably. Real fresh parent fits and
reused current scores are accounted separately. Recomputing deterministic
already-stored corrections after interruption is not additional unique training.

## Gates and evidence

The single aligned candidate must pass the existing joint red/blue hit review
on current100/50/10 and the separate original probability guards. Both earlier
blocks must also be nonregressing in all nested hit windows and probability
eligible. For support of the label-alignment mechanism, aligned current100 hits
must exceed the rotated control and its current100 blue loss must be lower.
Failure of any required comparison leaves `candidate_validated=false`.

Each arm's probability-only diagnostic uses the unchanged accepted-baseline
assessment; this alone is not a promotion. The actual paired hit review is
recorded separately and is mandatory for candidate validation. Existing issue
block-bootstrap intervals, nested-window dependence and lack of multiplicity
adjustment remain visible. Neither lower loss nor passing this historical study
establishes future accuracy. No candidate is automatically activated.

Execution uses the exact parent's Python3.12 CPU numerical identity, one Torch
thread and a two-CPU study cap inside the existing shared training cgroup.
The primary worker is not restarted. The existing90-second host telemetry,
memory/disk, fencing,17:00 checkpoint/report and verified-result resume guards
remain active. All writes are bounded Next study records and owned checkpoints;
raw context, model files and runtime receipts stay out of Git. No unit tests,
CI, dashboard or test mail are added.
