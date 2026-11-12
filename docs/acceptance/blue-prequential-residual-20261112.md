# Third-block diagnosis and frozen blue rank-correction comparison

Date: 2026-11-12, Asia/Shanghai. Next only. No legacy reads, writes, mounts or
service actions. No production recipe, threshold, report or delivery was changed.

## What failed in the previous study

The original500-origin result and frozen driver remain intact. This diagnosis
uses their existing immutable scores and prior64 selection receipts; it is
explicitly post-hoc diagnosis, not an additional validation sample.

Positive uniform shrinkage has `q_i-q_j=alpha*(p_i-p_j)`. All500 actual blue
Top1 choices were unchanged, as required. That algorithm has no mechanism for
increasing Top1 hits, irrespective of additional rounds or lower probability
loss. A changed ranking requires a different model, not more of that calibration.

In the failed2018020–2018119 block:

- The100-issue calibrated loss was2.792603757 against the unchanged2.792588722
  limit. The nested50 loss was2.807977272 and the nested10 loss2.771832701.
- Only12/100 origins selected alpha>=0.5. They contributed1.181424 of2.001503
  total excess log loss over uniform, about59%. In the last50, eight such origins
  contributed1.161902 of1.769427, about66%.
- The largest miss, issue2018104, selected alpha0.75 based on prior validation
  loss2.740352, then realized outer loss3.374079. It alone contributed0.601491
  excess loss over uniform. Issue2018079 selected0.5 and contributed0.259794.
- Mean selected inner loss was2.769685, substantially below the realized outer
  loss. The original validation holds a model fitted before the64-label segment
  fixed, whereas each actual forecast refits through the immediately prior draw.
  This is an observable procedural mismatch; noisy selection and mismatch are
  plausible contributors, not separately established causal effects.

An origin-matched counterfactual selected alpha using the preceding64 genuine
per-origin forecasts, never the target label. It changed62/100 choices and gave
100/50/10 losses2.779721682/2.785660519/2.770475744. This improves the inspected
block without changing thresholds or Top1. It remains diagnostic evidence;
fixed-alpha and rolling alternatives examined here are not retroactively promoted.

## New direction frozen before execution

Study: `blue-prequential-residual-v1-20261112`.
Protocol: `2faa47d0609390c6066fd65fbbab804eb35e7edbf69ff9978c39954044629dd5`.
Registered before new fitting at2026-11-12 14:48:33 Shanghai.
Driver: `d4154d0c22052428f144172b4c8f95de34784ce684983ded8ccea947f2bd9d7a`.
Pinned parent: `4c47956e261141dd2b17cc4a4f19b667f11fba88e28eb67b3a30f04bfabe0110`.
Numeric contract: `9cbb1aaf437410dce1dbe24d38cbebca2b2018cd2723ebeb757b3f3917ac2b06`.

The exact retained parent has current blue14/100,8/50,3/10 and red5+3/100,2/50,1/10.
Its data, scores and publication anchor were copied from hash-identical Next
artifacts into private study context before graph retirement could remove a
source. The study neither rewinds nor changes the production head.

One new16-parameter class-residual candidate, one fixed learning rate/regularizer,
one chronological pass, four controls and all windows were frozen before new
scoring. At each origin, a scalar uses the previous64 real out-of-sample
forecasts to choose the original alpha grid. The aligned candidate then learns
per-number logit biases from those same prior forecasts/labels. The rotated
control uses identical training with every prior blue label shifted by one
modulo16. Additional controls are scalar-only, smoothed prior100 frequency and
uniform. No control can be selected as a replacement after seeing results.
See `docs/architecture/blue-prequential-residual-study.md` for exact formulas.

The two additional historical blocks and the exact current100 each retain nested
50/10 checks. The previous failed block is excluded from validation. This does
not make these historical windows a protected project holdout or forward test.
Existing joint hit review and probability gates are unchanged; both earlier
blocks also require nonregression and probability eligibility. Current aligned
hits and loss must beat the rotated control for the narrow alignment diagnostic.

## Actual controlled results

Blue Top1 hits, in100/50/10 order:

| Procedure | Earlier0:2013087–2014032 | Earlier1:2014033–2014132 | Current:2026030–2026129 |
| --- | --- | --- | --- |
| Exact retained parent | 6 / 1 / 0 | 5 / 4 / 3 | 14 / 8 / 3 |
| Rolling scalar control | 6 / 1 / 0 | 5 / 4 / 3 | 14 / 8 / 3 |
| Aligned residual candidate | 5 / 1 / 0 | 6 / 4 / 1 | 10 / 3 / 0 |
| Rotated-label control | 8 / 3 / 0 | 12 / 6 / 1 | 8 / 4 / 0 |
| Prior100 frequency | 3 / 0 / 0 | 6 / 2 / 0 | 6 / 4 / 0 |
| Uniform deterministicTop1 | 6 / 4 / 1 | 3 / 2 / 1 | 7 / 2 / 0 |

The issue ranges are recorded from the actual frozen data in the private audit;
the indices1525–1624,1625–1724 and3426–3525 are the authoritative window identity.

Current100 probability results and unchanged-rule assessment:

| Procedure | Blue log loss | Red Brier | Probability guard | Joint hit review |
| --- | ---: | ---: | --- | --- |
| Exact retained parent | 2.776263 | 0.149251 | Pass | Baseline |
| Rolling scalar | 2.773395 | 0.149251 | Pass | INCONCLUSIVE |
| Aligned residual | 2.770874 | 0.149251 | Pass | INCONCLUSIVE |
| Rotated-label control | 2.772264 | 0.149251 | Pass | INCONCLUSIVE |
| Prior100 frequency | 2.810074 | 0.149251 | Fail | INCONCLUSIVE |
| Uniform | 2.772589 | 0.149251 | Pass | INCONCLUSIVE |

Aligned current50/10 blue losses are2.778268 and2.749318 respectively; full
precision and every nested window are retained in the audit. All complete
canonical red Top100 lists remain identical to the same-origin parent, not just
their aggregate hit counts. Current aligned ranking changes71/100 Top1 choices.

The current100 paired blue-hit interval for aligned minus parent is[-0.11,0.03];
the existing review therefore says INCONCLUSIVE, not a statistically confirmed
regression. Its observed100/50/10 hit decreases still violate the required
nonregression gate. Aligned current hits/loss beat the rotated control, so the
narrow current-only alignment flag is true; this is not overall mechanism
acceptance. The rotated control outperforms aligned on both earlier blocks.
The aligned candidate's earlier0 hits decline6 to5 and earlier1 tail10 declines
3 to1. Earlier replication and overall candidate validation are false.

Conclusion: rolling prequential calibration is a useful probability-control
direction to investigate, but scalar shrinkage cannot improve ranking. This
specific static class-residual rule changes ranking and sometimes improves loss
while destroying the parent's existing hit gains. Its older-window advantage
does not survive the wrong-label control. Reject it as a production replacement;
do not increase its rounds, tune against these results, choose the negative
control, widen thresholds or roll back the accepted parent. No new predictive
edge or forward capability is established.

## Actual execution and independent audit

The isolated Python3.12 CPU study used the exact live parent's immutable image,
two-CPU cap, one Torch thread and4GiB memory within the existing shared training
cgroup. An older image was initially rejected on numeric identity before the
protocol could register or a fit could run; no compatibility mapping was widened.
The failed startup is preserved. Primary DB connections were SELECT-only; study
writes went only to the named isolated Next study DB and owned Next artifacts.

Actual execution completed328 new prior fits:200 full composite parent fits and
128 blue-only warmup fits, totaling15,544 neural gradient steps. The current100
parent scores are reused, not new fits. Six hundred actual bias models each made
64 updates, totaling38,400 separate16-parameter SGD updates. Three bounded neural
anchors and every prior-origin reference, label digest, weight change, alpha
selection, bias vector and frozen arm output are persisted. The study exited0.

A separate read-only audit independently recomputed all600 bias models using
Torch autograd and SGD instead of the runner's hand-derived NumPy gradient.
Maximum coefficient discrepancy was5.551115123125783e-17. It verified all328
fresh-fit seeds, prefix/weight/step receipts,64-label boundaries, checkpoint
hashes,300 comparisons,1,500 arm outputs, red invariance and every original
assessment/review. It matched the persisted result and exited0. No new unit
tests or CI were added.

The primary worker stayed on its original container, with restart count0 and
fresh training results throughout. The program advanced from5845 before this
work to5849 by study completion. Twelve observed recovery samples were all
complete, with maximum telemetry age37.814 seconds. This short acceptance is
not a24-hour soak. No emails were changed or sent by this work. Existing17:00
checkpoint/report and authoritative-result-only resume guards remain active.

Private evidence, excluded from Git: `runtime/blue-residual-20261112/` contains
the frozen protocol and copied context, diagnosis, immutable-result export,
independent audit, actual progress observations and final primary-state receipt.
