# v1.1 extension: causal multiscale probability research

Owner scope, 2026-11-03: red and blue are separate models and outputs; multiscale
research becomes the main research topic after the current complete campaign.
This document establishes an experiment, not evidence that draw fluctuations are
predictable. Existing promotion and formal qualification remain unchanged.

## Frozen first grid

The methods `dynamic_level_v1`, `dynamic_trend_v1`, `dynamic_full_v1` and
`dynamic_no_short_v1` share coefficients across numbers, without identifier bias.
Each uses smoothed frequencies `(count + 20 * p0)/(window + 20)`, with windows
10/30/100 and p0=6/33 for red, 1/16 for blue. Trend features are f10-f30 and
f30-f100; gap is the number of immediately preceding nonappearances, capped at100
and divided by100. The four methods use respectively frequencies; frequencies
and trends; all features; and f30/f100/f30-f100/gap. The fourth method excludes
the10-period frequency and its difference from30. An immediately preceding appearance has gap0.
Trend columns are linear combinations of frequency columns: this comparison
tests representation and regularization, not additional independent information.

At historical origin t, feature rows use only [i-100,i), training targets i<t,
and the prediction uses [t-100,t). Separate colour means/scales are estimated
only from fitted historical feature rows; scales are floored at1e-6. Standardized
features feed red shared logistic and blue shared-score softmax heads. Adam fits
red binary cross entropy plus blue categorical cross entropy with regularization.
The red output is projected with a common logit offset to sum6, blue sums1.
Existing marginal-log-odds Top100 ranking and deterministic blueTop1 remain.

The first36 recipes are four feature methods x train_history256/512/1024 x
weight_decay0.01/0.1/1; learning_rate0.01, epochs100. `window=100` denotes the
feature warmup, `hidden=8` is a versioned compatibility sentinel, not a hidden
neural layer. Shared coefficients start at zero, red intercept log(6/27), blue
intercept0. Protocol seed1729 and existing origin-seed offsets remain recorded;
zero initialization is deterministic. Every origin and publication anchor is
fresh; coefficients and changed-prefix preprocessing are never inherited.

The36 recipes, dataset artifact, protocol and numerical identity are registered
before comparisons. Campaigns retain their existing node bound. The retained
accepted parent is the comparison root, never an arbitrary pruned candidate.
After the grid, feedback-neighbor/global batches continue with the same feature
version and fixed warmup; resource protection, novelty and failures persist.

## Evidence and interfaces

Existing per-issue100/50/10 hit gates decide promotion. Additive diagnostics compare
uniform, smoothed100, the exact parent and the model using red Brier and blue log
loss; calibration bins and rising/falling/equal frequency groups are descriptive.
Intervals use1000 circular block bootstrap replicates, block length5, seed1729,
with an issue as the resampling unit. Nested windows and33 numbers do not create
more independent draws. Calibration SVGs are bounded registered artifacts.

`/status.probability_research` exposes methods, latest real evaluation, feature
windows and frozen-rule forward counts. Existing research evidence and email
summaries retain the distinct scope of diagnostics, hit promotion and forward
results. No dashboard or new writable HTTP interface is introduced.

The explicit `program-multiscale --name ... --reason ...` transition requires
no unfinished campaign jobs, an adopted source and a verified accepted parent
re-evaluated under the new numerical identity. It preserves counters and replaces
topics with multiscale research. Legacy recipes, anchors and reports stay readable.
All new fitter files enter numeric identity; no cross-version cache mapping is
created. Direction-value input dimensions and feedback are version-isolated.

## Prospective shadow

After every first-grid recipe has a persisted evaluation on the same dataset and
numeric contract, an actually improved dynamic candidate must also pass the
unchanged formal assessment before its algorithm/update rule can be frozen.
`probability_rules`, `probability_forecasts` and `probability_settlements` are
append-only. Current trained fixed-rule refits are ordinary leased study jobs in
the same compute queue, separate from parent promotion and mail recommendations.

At the existing17:00 checkpoint boundary the reporter may seal the current
fixed-rule probabilities, with pinned data/model references and no extra fit.
Missing refits or illegal timestamps produce explicit absence, not reconstruction.
Settlement requires an authoritative verified result and an actual seal predating
the draw. The first30 settled draws are descriptive only; they do not stop the
observer or prove predictive improvement. Failed qualification leaves this journal
unstarted while research continues. Prior emails and official hit accounting are
never rewritten or replaced by the shadow evidence.

## Runtime contract

Use actual Python3.12 CPU application and real isolated Next PostgreSQL,8 origin
processes x1 thread, aggregate training budget8 CPU, Next0-19 and host20-21.
Validation may share that budget by temporarily dividing cgroup quota4+4 without
changing fitter threads. Qwen4B validation remains independent; no Qwen weights
are trained or automatically activated. No new unit tests, CI, test mail, legacy
access, quota-based stopping, or manufactured forward evidence is introduced.
