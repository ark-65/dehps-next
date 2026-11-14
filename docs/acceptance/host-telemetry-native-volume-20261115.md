# Next host volume accounting transport and diagnostics

The real primary Qwen call 7172 failed with `HOST_TELEMETRY_UNAVAILABLE` on
2026-11-15. Retained production samples took 42.525548 and 47.781356 seconds;
the preceding observation exceeded the unchanged 90-second validity limit
before the latter sample was published. The precise historical blocking stage
was not captured. Concurrent image-retirement timeouts alone do not establish
causality; retirement already runs on a separate thread.

## Change

Only the Next PostgreSQL volume command transport changes. The exact command
`du -sb /var/lib/postgresql/data` still runs in
`dehps-next-p0p1-database-1`, after the normal container ownership checks.
The already qualified `observe-qwen-priority.py` Unix API transport checks
framing, output bounds and the actual exec exit status. The complete volume
operation retains its 15-second deadline, including first-use helper loading.
There is no fallback to zero or estimated storage.

Coarse stage records expose wall time, the sampling thread's CPU time and
process CPU time. Process CPU includes other threads; it is not aggregate
container CPU or a billing metric. Errors retain completed stage records.
There is no per-file profiler. Original filesystem traversal, hardlink/sparse
byte accounting, symlink rejection, ownership validation, 10% CPU quota,
15-second post-sample sleep, memory/disk admission and 90-second validity remain.
Optional image lifecycle behavior is unchanged.

## Actual isolated acceptance

All work used the real named Next containers and database volume, under the
existing host-agent 10% CPU, Nice10, idle I/O and 256 MiB limits. No model
requests, training fits, SQL writes or canonical telemetry publications were
performed by these acceptances.

- One preregistered old-CLI/native-API ABBA completed without retries. CLI:
  1.024756 / 0.520114 seconds. Native API: 0.405643 / 0.231014 seconds.
  Every result was exactly 6,107,847,004 bytes from the same live volume.
- Three complete real host samples took 12.494539, 3.485950 and 6.414000 seconds.
  Training was running; no primary Qwen call was active when these samples
  started. This is not an active-primary or sustained-load acceptance claim.
- The final source, after removing an unused import, completed a separate
  actual one-shot in 13.939941 seconds; its volume stage was 0.648842 seconds.
- `size`, `get` and image-retirement function bodies remain identical to the
  previous source. The dependency transport is unchanged.

The source SHA-256 is `173448cd4cf69b9c8d416cd6aed93a4d5e53c9a867394fa374fc786303d3984d`.
The unchanged transport SHA-256 is
`dddd7e6d085945bb84217d4940fa8be96451a5bfd2b8179a0a99db8fb7db30ad`.
Actual receipts and all raw diagnostics stay in ignored Next runtime storage.
No new unit tests, model files, caches, credentials or runtime receipts are
included in this change.

## Preserved negative findings and limits

The proposed batched native-du inventory failed two of three actual sampling
attempts at its proposed stage bound. The directory-FD proposal did not show a
speed benefit in a separate unprofiled ABBA (old 3.193057 / 3.903587 seconds;
proposal 4.094463 / 3.400993 seconds). Neither proposal is delivered.
An earlier expected-directory-metadata assertion and a harness scalar-index
error are preserved as failed engineering attempts. Fine-grained Python
profiler overhead also prevents treating its 40-second stage measurements as
uninstrumented production timings.

The isolated results establish the narrower transport change and complete
sampling behavior. They do not prove the original failure's entire root cause
or a repaired 24-hour soak. Production source/process identity, future fresh
samples during real primary calls and long-term continuity still require live
verification. Qwen qualification, completed-boundary activation, the real
selected-fit feedback loop, mail delivery and predictive improvement remain
separate. Main training topology and the 17:00/official-verification rules are
unchanged; legacy DEHPS is untouched.
