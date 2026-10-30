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
- Latest owner mail schedule2026-10-29 supersedes the old17:00 cutoff: Shanghai draw-day17:00 starts preparation;18:50–19:00 seals;19:00 queues final mail;19:30 is the conservative internal send cutoff before20:00 shop closure. `report-prepare` never bypasses the seal gate. Preserve prior reports and append any eligible unresolved early17:00 schedule correction; never rewrite immutable facts.
- Require frozen recent100, nested recent10 and random historical regression; preserve failed branches, finite extensions and restored parent hashes. Replay remains development evidence, not forward proof.
- Preserve early acceptance predictions and their exclusions; never silently replace immutable predictions or count them as official mail recommendations.

- Owner selected 2026-10-29: two-core on-demand persistent research, 172800 capacity-seconds/day, 24 local model calls/day. Preserve existing spend/call counters; do not stop by campaign count or wait for a new draw while useful registered work and resources remain.
- Controller-only upgrades must retain numerically equivalent recipe exclusions and reuse audited historical scores; never count cached fits as newly executed training.

- Latest owner allocation 2026-10-29: training8 CPU, local inference4 CPU, planner1 CPU; 691200 capacity-seconds/day, 24 model calls/day. Preserve prior counters and formal forecast/mail timing. Keep process threads distinct from frozen training threads; complete active campaigns before changing thread configuration.

- Latest owner policy 2026-10-29: local inference has no consumption billing or daily capacity/call/token quota. Display provider-reported input/output tokens only; preserve missing-count flags and historical receipts. Keep hardware8/4/1, memory/storage/concurrency safeguards and real validation; never use historical spend or call totals to disable Qwen or research.

- Final recommendations and missing-coverage settlement use effective_forecast_selections. Prior17:00 mail remains immutable; PRE_FINAL is independently deduplicated. Never relax eligibility or fabricate a recommendation to meet the clock.

- Owner2026-10-30 retired legacy DEHPS services, timers, containers and startup paths; code/data/models remain archived. Do not re-enable legacy execution.
- Latest CPU policy2026-10-30 supersedes hardware8/4/1: Next uses its dedicated dehpsnext.slice with CPU0-19; ordinary host system/user/init groups use LP-E CPU20-21. Select training/inference thread counts from actual frozen-fit and Qwen benchmarks, not CPU occupancy. Finish frozen campaigns before changing numeric threads; new campaigns record the selected CPU pool and threads and revalidate under that numeric contract. Preserve mail timing, token-only observation and memory/storage guards.
