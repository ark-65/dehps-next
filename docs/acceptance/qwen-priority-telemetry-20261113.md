# Qwen admission telemetry publication

The graph-sync diagnostic was interrupted by its unchanged freshness guard:
snapshot age31.9026s exceeded30s while primary training was healthy, primary
inference was inactive and its next-call headroom was1106s. The attempted answer
and interruption remain recorded; the remaining two cells are NOT_RUN. This is
not a successful latency result or evidence that synchronization fixes Qwen.

The old observer serialized admission reads, application startup, hardware
inspection and reporting queries before publishing its admission file. The new
`scripts/observe-qwen-priority.py` gives publication an independent path. Four
bounded read-only observations run concurrently: host resources/desktop idle,
Next service activity, actual Next PostgreSQL progress/cadence/state, and the
existing Python3.12 application's official-result training-window function.
Slow native-call and hardware reports remain separate.

The snapshot timestamp precedes every read. Publication never refreshes old
data; missing state or a capture exceeding30s leaves the previous snapshot
unchanged. Training age and cadence headroom are conservatively updated at
publication. Unknown desktop idle retains existing admission behavior. No
quality, latency, idle, memory, progress, freshness or draw gate changes.

Actual host/Next PostgreSQL and Python3.12 acceptance, without new unit tests:

- 15 successful reads, including14 consecutive daemon samples. Maximum capture
 4.910073s; maximum consecutive daemon start gap10.003044s.
- Primary generations6141–6142 remained running. Official receipt2026130 and the
 original observation deadline2026-11-14T03:14:50.976635Z were retained.
- A real PostgreSQL lookup for a nonexistent soak failed closed. The previously
 published admission file remained byte-identical, including its timestamp.
- Zero model requests or acceptance-created fits; Ruff and diff checks pass.

This is functional telemetry evidence over a short interval. It does not pass
Qwen generation, the original144-call qualification, a repaired-source24h soak,
feedback closure, delivery or predictive acceptance. Primary model/source and
training allocation are unchanged; legacy DEHPS is untouched.

## Faster telemetry refresh, retained failure

Longer live observation subsequently recorded one application-window subprocess
timeout. The old snapshot was correctly left unchanged; maximum age before the
next publication reached31.265989s. Preserve this failure. The short functional
acceptance above did not establish long-term availability.

The observer now accepts an explicit5-second refresh interval; the default is
still10. This changes only telemetry polling, never model-request spacing,
production cadence, the30-second freshness guard or the300-second soak sampler.
The observation and failure-handling function is byte-identical to PR61.

Actual5-second host/Next PostgreSQL/Python3.12 acceptance:16 samples at primary
generation6148; maximum capture0.389638s, start gap5.000137s and available snapshot
age5.389729s. Main services remained running. Zero model requests; Ruff and diff
checks passed. These short measurements do not prove a fault-free24h window.
