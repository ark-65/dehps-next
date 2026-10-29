# DEHPS Next owner workflow

Owner instruction, 2026-10-29. Applies to all future work in this repository.

- After creating every PR, Codex must manually squash-merge it using the exact reviewed head.
  Do not enable automatic merge. Verify the resulting merge commit and remote main.
- Do not write new unit tests. Validate behavior by running the real isolated Next application,
  inspecting its database/artifacts, and recording meaningful live acceptance evidence.
- Do not add useless CI or duplicate push/PR runs. The previous P1 workflow is manual-only.
- Preserve existing tests as historical reference; they are not a requirement to add more tests.
- Do not edit, delete, restart, mount, or write to legacy DEHPS code/data/services.
  P2/P3 use the already imported Next history; no additional legacy access is needed.
- Never hide failed experiments, fabricate evaluation outcomes, or call history replay forward evidence.
- Ordinary in-policy branch exploration, rollback, pruning and direction changes are autonomous.
- Keep secrets, raw datasets, model files and runtime caches out of Git. Commit only small intended reports.


- Keep research and historical regression running between draws within accepted budgets. Do not use waiting for a new draw as the default research clock.
- Official mail forecasts may only seal during the registered draw day's Shanghai 16:59–17:00 window. `report-prepare` never bypasses this gate.
- Require frozen recent100, nested recent10 and random historical regression; preserve failed branches, finite extensions and restored parent hashes. Replay remains development evidence, not forward proof.
- Preserve early acceptance predictions and their exclusions; never silently replace immutable predictions or count them as official mail recommendations.

- Owner selected 2026-10-29: two-core on-demand persistent research, 172800 capacity-seconds/day, 24 local model calls/day. Preserve existing spend/call counters; do not stop by campaign count or wait for a new draw while useful registered work and resources remain.
- Controller-only upgrades must retain numerically equivalent recipe exclusions and reuse audited historical scores; never count cached fits as newly executed training.
