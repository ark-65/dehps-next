# Qwen candidate selection and cross-round feedback

This extends the v1.1 research controller. It changes candidate selection, not the
numeric fitter, chronological100/nested50/10 evaluation or parent-child promotion.
All evidence is development replay until independently sealed pre-draw outcomes exist.

## Real alternatives within a bounded context

`candidates-v3` supplies six distinct recipes in compact column arrays. Two open
pipeline slots receive three repair and three structural exploration alternatives;
one open slot receives a single group with at least three alternatives. The controller
prefers different changed axes locally and different method/window/width/history
combinations for exploration. These remain the registered FFT/ridge/Newton feature
families, not new neural architectures. IDs are stably shuffled within groups so
the learned value rank does not determine the first ID.

Candidate generation and submission both query the complete durable recipe index.
When an extended batch has too few untried recipes for genuine alternatives, its
remaining recipes carry into a registered successor batch. Previously tried recipes
never become new training because of compression or code-only release changes.

Every choice group must retain at least three distinct recipes. If candidate and
feedback facts cannot fit the conservative4096-token envelope, planning refuses
the call instead of deleting alternatives. A bounded input is not a lifetime quota.

## Feedback grounded in real records

Feedback queries durable evaluation events by exact dataset/validation/numeric/thread
contract and exact parent outcome digest. Family totals count comparable recipe
trials, not independent draws. Up to four concrete cases retain parameters, actual
red5+Top100/blueTop1 counts in100/50/10, verdict, paired differences and original
node/campaign/sequence references. The request contains these cases and aggregate
family risks directly; a memory hash alone is insufficient.

Qwen selects one candidate, one supplied evidence key and an intended red/blue/stability
goal per named group. Strict validation rejects misplaced candidates, missing evidence
and unchanged parent recipes. Exact parameter changes and the per-child hypothesis
are rendered from records by the controller; they are not Qwen-authored numerical
claims. Each child stores its own selection and cited evidence. Lease fencing,
stale-parent rejection, commit-time deduplication and pipeline capacity remain active.
The direction-value network continues actual gradient updates; Qwen weights are not
fine-tuned by this mechanism.

Physical admission treats the configured Next memory envelope as a total, subtracting
already resident named Next containers when reserving additional growth. It retains
the60% physical cap and4GiB host margin. Docker accounting requests allow30 seconds
because actual build-cache/image queries can exceed ten seconds during fits; missing
or older-than90-second telemetry still blocks admission. This removes false waits
without introducing usage quotas or weakening physical protection.

## Frozen feedback comparison

`scripts/benchmark-feedback.py` only runs in a named isolated Next PostgreSQL clone
and `feedback-case` runtime. It freezes twelve disjoint six-recipe pools, the parent,
comparable failure records, model digest, inference options, analysis and source hashes
before any candidate outcome. Each pool is reviewed both with and without failure
feedback, alternating arm order. Both arms see the same parent and recipes. Every
offered recipe is evaluated using the unchanged prior-only100-origin fitter.

The primary measure is unchanged promotion eligibility among each arm's two picks.
Secondary utility adds the recent100 red/blue deltas and penalizes every negative
nested-window delta. Twelve pool pairs, not7200 fitted origins, are analysis units;
all recipes share100 draw labels. Exact paired sign randomization and paired bootstrap
intervals describe this development comparison, without correcting prior adaptive search.
Invalid reviews score zero primary eligibility and retain their error records. An
infrastructure admission wait retries without changing completed immutable choices.

Migration013 stores immutable study protocols, pools, selections, evaluations and
results separately. Study roots are excluded from forecast selection and complete
without proposing successors or promoting a study model. The status API reports
choice evidence and comparison results; it does not add a dashboard or send study mail.

Feedback consumption, changed choices, better development selection and genuine
forward improvement are separate claims. Identical choices are a negative result
for feedback discrimination, even when all structured replies are valid.
