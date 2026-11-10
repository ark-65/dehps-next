# Label-free red cardinality calibration and measured training pool

The retained red procedure had unconstrained sigmoid marginals with total mass
10.91–12.62 on current100, averaging11.79 although every valid draw contains six
red balls. Its Brier score0.181219 exceeded the unchanged0.158760 guard. The
mean-probability bias term alone was0.030913 of0.032459 excess over uniform.
This is an output-coherence failure, separately from the unresolved absence of
stable predictive signal.

## Mathematical contract

For the33 original marginals, compute logits and their unique shared intercept
such that the resulting sigmoid probabilities sum to six. This uses the known
draw cardinality and no target labels. There is no tuned temperature, shrinkage,
holdout threshold or promotion change. Every six-element subset's log-odds score
adds exactly the same6 times the intercept, preserving its mathematical order.
Real acceptance additionally requires identical complete canonical Top100 lists,
including floating-point ordering. Blue probabilities remain bitwise identical.

The versioned `mass6_blue_*_v2` methods retain both independently fitted base
components and apply the fixed correction only to red probabilities. Old v1
behavior and anchors remain supported. Mathematical state includes the exact
calibration contract; changed cardinality metadata is rejected on restore. New
publication repeats the same rule as every prior-only historical-origin fit.

The corrected numerical contract is new. Migration requires a frozen paired
comparison against the exact retained recipe on current100 plus four predeclared
earlier100 blocks, unchanged redTop100/blue outputs and current eligibility under
the original guards. It also requires red Brier improvement in all nested
windows of all five blocks. A changed parent requires revalidation; acquired
improvements must never be overwritten with an older recipe.

This is an explicitly recorded output-preserving baseline release. It is not a
new red/blue hit promotion: the paired hit review remains INCONCLUSIVE when all
counts are unchanged, and the new owned root is ACCEPT_BASELINE. Old accepted
parent snapshots and sealed predictions remain immutable. Subsequent children
still require the original paired hit promotion and separate eligibility guards.
Earlier blue failures remain in comparative selection context.

## CPU selection

The owner requested higher useful CPU utilization. A temporary20-CPU Next-only
slice benchmark compared8/12/16/20 independent one-thread fitters, including
cold/warm passes. Every frozen probability, weight and mathematical digest
matched. Twelve,16 and20 warm fitters had similar throughput, while20 consumed
about2GB more than12. Separate real Worker comparisons of two frozen recipes,
with fresh databases and8/12/12/8 pool ordering, measured a lower mean complete
cycle time for12. The accepted profile is12 processes x1 Torch thread, aggregate
12-CPU training quota within CPU0–19; host CPU20–21 and Qwen GPU/helper settings
are preserved. Memory, disk, lease, draw and artifact safeguards remain active.

Only the exact audited compute source change raising the independent-pool
admission ceiling8 to20 is numerically mapped to its previous source hash.
This mapping is justified by full per-origin equality in all four measured
pools and actual8/12 Worker executions. It does not cover any fitter, RNG,
feature, scoring or thread change. Pool size remains recorded separately.

Docker physical-read voids also caused real admission gaps. Host collection now
retries an identical read once, caches duplicate immutable image-size lookups
within a sample, and keeps image-retirement failures separate from a successful
resource observation. Two physical-read failures still invalidate telemetry.
Observation timestamps mark collection start, so a delayed snapshot cannot
masquerade as fresh. Ownership, symlink, full-accounting and90s freshness guards
are unchanged. Isolated telemetry outputs must be ordinary files, not symlinks.

The normal17:00 draw pause, checkpoint/report behavior and authoritative-result
resume remain in force. Development eligibility is not forward capability,
delivery proof or sustained-soak completion. Legacy DEHPS is untouched.
