# Exact bounded soak progress observation

Date:2026-11-13. The original progress aggregate repeatedly exceeded its15-second
statement timeout while reading581,036 memory events, about2.95GB including TOAST.
Disabling JIT alone also timed out after15.011 seconds. Merely starting another
timer did not fix the query. Preserve those actual errors and sampling gaps.

`scripts/observe-soak-bounded.py` partitions the **unchanged original progress
SQL** by disjoint4096-wide event-sequence ranges. It uses a single read-only
repeatable-read snapshot, including the global FIT_PROGRESS existence checks.
SUM/MAX over the partitions preserve the original integer counts, resumed-origin
accounting and last actual fit. Preserve PostgreSQL bigint result bounds. New
events committed during observation wait for the next sample, as with the
original single-statement snapshot. No date assumption, approximate counter,
stale cache, event mutation or synthetic training receipt is introduced.

Each statement retains the original15-second timeout. The four original metrics
and original `training_observer.sample_due()` implementation remain in use:
300-second sampling,600-second maximum gap,900-second fresh-fit stall review and
the existing draw-window exemption. The24-hour start/deadline are never reset,
missed samples are not backfilled and warnings are not cleared. Disabling JIT
and bounding statement work change query execution, not the acceptance limits.

Actual Python3.12/Next PostgreSQL validation compared the original SQL with its
partition aggregate on old/recent8192-sequence ranges under both all-history
and current-soak cutoffs, all in one consistent real snapshot. All four metrics
matched exactly in all four comparisons. The complete156-block observation and
comparisons finished in25.550 seconds. At that snapshot, since08:59:53 Shanghai,
the original counters were15,200 fresh origins,2,164,554 gradient steps and3,440
reused origins; those categories remain distinct. These dated counts continue
to advance and are not predictive improvement.

The restart-safe dedicated Next observer calls the original sampler using the
bounded progress function. Its source identity and named primary database are
checked. It does not replace training workers or change CPU quotas, numerical
threads, Qwen profiles, planning cadence, model selection or report contents.
Steward's ordinary sampling can coexist through the original locked-row/skip
logic; only due actual samples are persisted. Private receipts record full query
identity, snapshot sequence range, block count and real elapsed time.

An enabled observer, matched counters or a short successful sample is not a
completed soak. The original elapsed run must still finish and pass its unchanged
gap/progress rules. No unit tests, CI, dashboard, test mail or legacy access are
added. Runtime evidence is retained outside Git under the named latency operation.
