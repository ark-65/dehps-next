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
