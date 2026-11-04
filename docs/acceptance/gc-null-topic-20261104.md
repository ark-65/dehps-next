# Nullable retirement topic recovery

2026-11-04, Asia/Shanghai. Production training resumed after the official
2026126 receipt, then stopped advancing after campaign
`autonomous-v2-1824-866260c3` completed at00:15. Steward repeatedly failed
with `NotNullViolation` while retiring the superseded manual parent
revalidation, which had a program association and a null topic. The GC
transaction rolled back, repeatedly contending with job claims on740139;
there were no READY/RUNNING jobs at diagnosis.

Retirement now assigns a program-associated campaign without a topic to the
existing `manual` rollup. Named program topics keep their original grouping.
The campaign facts, recipe exclusions, archival/compaction order, protected
artifacts, numeric contract and forecast gates are unchanged.

Actual isolated Python3.12 CPU application acceptance used a separate
`dehps_next_gc_accept_20261104_v2` database in the Next PostgreSQL container.
The actual null-topic campaign, its node, program and dataset metadata were
copied with SELECT-only source transactions. Only in that isolated database,
the campaign was aged91 days and two newer keeper copies controlled GC
eligibility; this is controlled recovery acceptance, not prediction evidence.

- Original code reproduced the `research_rollups.topic` not-null failure;
  rollback preserved the campaign and published no memory events.
- Corrected real `Lifecycle.collect(apply=True)` retired exactly one campaign,
  produced a `manual` rollup of one campaign/one node, and retained the exact
  config/status in durable memory with a compaction head.
- A repeated collection retired zero campaigns and did not double count.
- No SMTP path was run in acceptance. No new unit tests or CI were added.

During the repair the failed steward was stopped and its unchanged, fenced
`tick()` entrypoint resumed real production campaigns1825 and1826. Deployment,
subsequent automatic progression, delivery and sustained observation require
their own live evidence; this isolated GC check does not establish them.
