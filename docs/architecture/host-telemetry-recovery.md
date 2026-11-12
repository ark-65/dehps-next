# Fresh physical telemetry and frozen-study recovery

The host agent must publish a complete physical observation within the existing
90-second freshness gate. Docker image enumeration and image retirement can
block long enough to make otherwise valid memory/disk observations stale. They
are not prerequisites for reading current physical capacity.

Physical collection reads only the explicitly named Next containers, verifies
their ownership, and reads current container statistics, host memory, free disk,
the named Next PostgreSQL volume and owned files. It does not request Docker
image inventory or per-container rootfs sizing. All Docker images and writable
layers are conservatively bounded by the entire backing device, after verifying
that Docker storage and the repository share that device. The environment and
shared-cache bounds overlap; neither is attributed Next usage or a measured
capacity demand. Admission continues to use actual free disk and memory.

Owned directory accounting uses `scandir` metadata without following symlinks.
This retains the owned-scope symlink rejection while avoiding repeated Path and
stat operations on the growing artifact tree. Missing, incomplete, wrong-owner
or older-than-90-second physical observations still close admission. Observation
time remains collection start, rather than publication time.

Image retirement runs in one background thread with at least 300 seconds
between attempts. Its slow or failed inventory cannot hold publication of
physical observations. The original owner-label, seven-day age, unreferenced
image, tag and immediate recheck requirements remain in force. A one-shot
physical observation does not start image retirement.

`scripts/resume-frozen-calibration.py` verifies the original driver hash and
executes the same source statements, replacing only its operational `pulse`.
The original file remains unchanged, including its hash in the frozen protocol.
An append-only recovery amendment records the frozen protocol and runner hash.
Completed baseline and inner-fit records are reused with their original keys;
startup receipts record their counts and content digests. Fresh fits continue
with the original data, seeds, mathematical code and scoring/eligibility rules.

The replacement pulse waits on missing telemetry, physical pressure or the
existing draw-window gate. It performs no parameter update while held, retains
the original advisory-lock session and fails if that session is lost. Unknown
domain errors still fail rather than being silently retried. The runner uses
the original Python 3.12 CPU image, isolated Next study database, memory limit
and shared training cgroup. It neither restarts the primary training worker nor
automatically activates the studied calibration.

Completing the calibration study establishes only its frozen historical
probability and output-invariance results. Hit-rate promotion, forward evidence,
long-duration stability and mail delivery remain separate acceptance states.
