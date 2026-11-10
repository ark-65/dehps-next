# Automatic measured batch review, 2026-11-10

The owner requested ongoing per-batch checks and direction changes founded on
actual red/blue effects, rather than only generation or failed-trial counters.

In the primary run, campaign5250 completed with seven INCONCLUSIVE children and
no promotions. Its reference parent's red5+100/50/10 counts were3/2/1 and blue
Top1 counts10/6/2. Candidate outcomes and exact parent-relative deltas remained
available in the real database; later batches continued automatically.

The new steward review reads completed owned frontier campaigns and appends
immutable, uniquely keyed quality events. Actual source windows and source-fact
hashes are retained, including each child's correct paired parent. Reviews are
evidence, not prediction or promotion operations. The planner now records the
dominant red/blue veto and uses sufficiently covered, comparable reviews when
choosing the next question after a non-improving block.

Actual isolated Python3.12 / Next PostgreSQL acceptance reviewed four existing
real Worker campaigns containing28 evaluated children. Every saved red/blue delta
was recomputed against its exact parent and all source-fact digests were checked.
A second run wrote no duplicate reviews. The comparable summary had10 red-veto
candidates,25 blue-veto candidates,27 without recent progress, and no
nested-only vetoes. A prototype misclassified a recent red/blue tradeoff as a
nested-only veto; versioned review records preserve that failed prototype while
the corrected review counts the100-issue tradeoff correctly. Candidate counts are not independent draw
counts. This metadata acceptance executed no new fits or inference calls.

Numerical fitting, original promotion/qualification, eight-CPU training, Qwen
cadence, immutable predictions and mail remain unchanged. No new unit tests,
CI, dashboard, test mail or legacy access is introduced. Deployment is performed
only at the completed frozen campaign boundary.

Production startup exposed an ordering error: backfilled older campaigns had
newer journal sequence numbers. The follow-up orders comparable reviews by
the source campaign creation time, recording that time in new immutable reviews
so graph retirement cannot change their order. Existing records use their live
source campaign time; records without either source are excluded from recent
diagnosis rather than assigned an invented date.
An isolated Python3.12 container queried the real Next database in a read-only
transaction and checked all chosen source campaigns and diagnostic totals
independently: campaigns5253/5252/5251/5250,28 candidates,20 red vetoes and27
blue vetoes. Backfill insertion order no longer controls the next question.

A later actual planning attempt timed out in cross-round family feedback and
automatically recovered. The family query projected large archived payloads
before choosing its eight representatives. A repeatable-read, read-only
comparison on real Next PostgreSQL produced identical complete ordered rows
with narrow identity selection followed by payload projection:6.0253s versus
12.9004s for the original query. This is a paired query observation, not a
whole-training throughput or predictive improvement claim. An earlier comparison
without a fixed snapshot saw different concurrent inputs and was rejected; a
second observation started before a new campaign's root was evaluated and was
also rejected. The accepted comparison used a completed frozen campaign.
An isolated Python3.12 image then executed the complete cross-round feedback
function against a real completed campaign in a read-only repeatable snapshot.
The entire returned structure, including Qwen delivery targets, was identical
(digest4ecfdb3e8853fb9a8d32dc2e2d8375032043235f3e2bcf79702b93a1d459053c).
Observed complete-feedback times were24.5852s after and30.9863s before; numeric
identity remained unchanged. This improves one measured component and does not
claim that all feedback work or future transient timeouts have been eliminated.
