# Host telemetry repair and completed 500-origin calibration replay

Date: 2026-11-12, Asia/Shanghai. Scope is Next only. No legacy access, new unit
tests, CI, dashboard, test email or primary-worker restart was performed.

## Repair and live acceptance

Docker label-filtered image inventory timed out during host collection. Other
successful collections took up to 83 seconds before publication, leaving little
of the existing 90-second freshness window. Owned directory traversal also took
about 12 seconds in an isolated observation and was slower under the host
agent's unchanged 10% CPU quota. The standalone study did not catch
`HOST_TELEMETRY_UNAVAILABLE`, so it exited with 100 baseline and 88 inner fits
durably saved. The original failed container and frozen driver are preserved.

The repair moves image inventory/retirement off physical collection, bounds
images and writable layers by their entire verified backing device, and uses
`scandir` for equivalent owned-file accounting without following symlinks.
Retirement remains single-threaded with the original deletion requirements.
The 90-second gate, ownership, complete accounting, real disk/memory admission,
draw timing and primary training topology remain unchanged.

Actual isolated host collection completed in 4.499 and 5.397 seconds while an
optional retirement operation configured to block for 95 seconds remained in
flight. Old/new logical byte counts matched on the actual source, documentation
and isolated study artifact trees. Real Python 3.12 CPU application calls against
Next PostgreSQL rejected missing, 91-second-old and wrong-owner telemetry with
`HOST_TELEMETRY_UNAVAILABLE`, incomplete data with
`HOST_ACCOUNTING_INCOMPLETE`, and zero free disk with `HOST_LOW_DISK`; fresh
complete physical observations passed.

The deployed host service produced 27 observed complete samples over about nine
minutes, with maximum sampled telemetry age 48.725 seconds. This is bounded live
acceptance, not a completed 24-hour soak. Optional GC delay is not fabricated as
a passed inventory or attributed disk measurement.

## Frozen recovery and actual training

Study: `prior-only-blue-calibration-new500-20261111`.
Frozen protocol: `1f34e8124ba275faed3492d019a9b9bc93501e6b38a8407f176fdcc1ec369326`.
Original driver: `e3f8ddd75b4ee9510ab6de0cf36898847dea1583f88f37fc46982fff41b89dca`.

The recovery runner verifies and executes the original driver, replacing only
its operational pulse. The original frozen hash, data, recipes, seeds, prior64
selection, scoring and qualification thresholds are unchanged. An append-only
study amendment records this recovery. Telemetry interruptions now hold work
until recovery, with the original draw/resource guard and advisory-lock session.
Unknown errors and a lost fencing session still fail.

The original 100 baseline and 88 inner records retain their exact content
digests. Recovery executed the remaining 400 composite baseline fits and 412
inner fits, accounting for 48,480 new gradient steps. The complete study contains
500 composite fits (two neural components each), 500 inner fits and 60,000
gradient steps across 500 unique historical issues. Every recorded baseline and
inner model changed its initial weight digest. Completed work was reused rather
than counted as newly executed recovery work. Recovery exited successfully after
834.714 seconds, finishing at 14:24:48 Shanghai.

A separate Python 3.12 audit in the exact original CPU image used SELECT-only
connections to the real isolated Next study database. It checked every origin,
seed/key identity, prior-only label digest, prior64 alpha selection, weight
update, preserved checkpoint prefix and frozen driver/protocol; it independently
recomputed all before/after qualification and hit metrics and matched the
persisted study result. The final audit exited 0.

The primary worker remained the original container, started 2026-11-11 09:11:47
Shanghai with restart count 0. The primary program advanced from generation
5838 to 5841 during recovery, with fresh completed-origin/parameter-update
receipts throughout. Study execution shared the existing training cgroup and did
not change production recipes or activate calibration.

## Actual historical results

Each row is one disjoint 100-issue block. Red5+ counts an issue once when any
canonical red Top100 combination hits at least five red balls. Hit counts and
red Brier scores are identical before and after calibration.

| Historical issues | Blue Top1 hits | Red5+ issues | Blue log loss before | After | Red Brier | After qualification |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2016127–2017073 | 10/100 | 0/100 | 2.827690 | 2.771020 | 0.149696 | Pass |
| 2017074–2018019 | 4/100 | 0/100 | 2.858459 | 2.789157 | 0.149252 | Pass |
| 2018020–2018119 | 7/100 | 2/100 | 2.858921 | 2.792604 | 0.149971 | Fail |
| 2018120–2019066 | 5/100 | 0/100 | 2.882552 | 2.780765 | 0.149264 | Pass |
| 2019067–2020015 | 8/100 | 0/100 | 2.802438 | 2.774747 | 0.149143 | Pass |
| All 500 unique issues | 34/500 | 2/500 | 2.846012 | 2.781659 | 0.149465 | 4/5 blocks pass |

The failed block has calibrated blue log loss 2.792603757 in its 100-issue window
and 2.807977272 in its nested 50-issue window. Both exceed the unchanged
`log(16)+0.02 = 2.792588722` limit; the nested 10-issue loss is 2.771832701 and
passes. Pooling the 500 origins cannot override this frozen per-window failure.

All five full-block losses decreased, but calibration remains slightly worse
than uniform blue log loss 2.772588722 when pooled. The selected mixing factor
was 0.05 on 271/500 origins, consistent with strong shrinkage toward uniform.
This result supports reducing historical overconfidence; it does not establish
new predictive signal. Blue Top1 stayed 34/500 (6.8%); red5+ stayed 2/500 (0.4%).
All Top1 selections and complete canonical red Top100 lists were preserved.

Conclusion: this older-window replication does not pass all frozen probability
qualification windows and produces no hit promotion. Calibration is not
activated. Retain the current production parent and primary research. These are
historical replay findings, not genuine pre-draw forward evidence. No report or
mail was changed or sent by this operation, and inbox delivery is not claimed.

Private runtime evidence (excluded from Git):

- `runtime/host-telemetry-recovery-20261112/`: isolated sampler/physical-guard
  acceptance, deployment identity and bounded observation history.
- `runtime/blue-temporal-20261110/recovery-20261112.json` and
  `preserved-checkpoints-20261112.json`: continuation receipts.
- `runtime/blue-temporal-20261110/prior-calibration-new500-result.json` and
  `new500-audit-20261112.json`: frozen result and independent recomputation,
  including every nested 100/50/10 metric.
