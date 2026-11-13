# Actual fit continuity audit

The 300-second sampler can miss a stall slightly longer than the frozen
900-second limit when training resumes before the next sample. A zero warning
count therefore cannot certify uninterrupted training.

`scripts/audit-training-continuity.py` audits positive-gradient FIT_PROGRESS and
EVALUATION timestamps from the actual Next database. It reads sequence blocks of
4096 in one repeatable-read, read-only transaction, retaining the original
15-second statement timeout. It includes the observation boundaries and orders
timestamps independently of commit sequence. The threshold stays 900 seconds.
Pause exemptions use the existing application gate between actual calendar,
draw, publication verification and source observation boundaries. The tool never
updates a soak, changes its deadline or changes primary training behavior.

Actual isolated Python 3.12 CPU execution against Next PostgreSQL read 11,389
positive fit markers in 159 blocks in 37.105 seconds. It found the preserved
920.53455-second gap between sequences 648013 and 648014, despite 105 periodic
samples and zero sampled warnings. The run was still below 24 hours, so terminal
pass fields correctly remained null while `failed_so_far` was true.

Read-only replay of the actual 2026130 official publication verified the pause
from November 12 at 17:00 Shanghai to 21:58:05.683054. The original gate still
paused one microsecond before verification and resumed at verification, with the
actual issue and source receipt. Midnight was not used as a resume boundary.

The first isolated launch omitted CPU affinity and Settings rejected it before
opening the database. That failure is retained. The accepted launch used the
registered CPU0–19 pool, one CPU quota, 512 MiB and a read-only filesystem. No new
unit tests or CI, model requests, database writes or primary restarts occurred.
Ruff and diff checks passed. This validates the audit and historical official
boundary; Qwen repair, a completed new 24-hour soak, mail delivery and predictive
improvement remain separate and unproven.

Local immutable acceptance and actual receipts are retained under
`runtime/operations/qwen-continuity-audit-20261113/`; generated receipts are not
committed.
