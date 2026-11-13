# Qwen observation across campaign retirement

The old selection observer read only `research_model_calls`. Bounded lifecycle
retirement had already moved calls 7030–7035 into immutable `CAMPAIGN_ARCHIVE`
memory events. Live-table statistics therefore fell from 20 logical calls to
19 when another call finished, dropping old successes and failures from the
same fixed observation window. The underlying archive remained intact.

`scripts/observe-qwen-selection.py` reads the named primary database with one
consistent, read-only snapshot and the original eight-second statement timeout.
It combines live calls with exact campaign call receipts found through the
immutable Qwen audit and campaign-event identities. It does not disable GC,
restore deleted graph rows or alter primary execution. Duplicate conflicting
identities fail closed.

A counted accepted choice must have its immutable `QWEN_COMPARATIVE` audit and
both actual successful native phases. The thinking receipt must bind to the
prefix call's request, response, campaign, model and all three reported counts.
Missing counts are not estimated. Terminal metadata is retained in bounded,
content-addressed observation files; repeated samples create no duplicate
receipts, and losing previously seen identities stops publication. The 32MiB
observer storage bound can stop only this observer, never training or inference.

Actual isolated acceptance used the Python 3.12 CPU image `e0be16654d65`, the
unchanged primary source `981cd97c9e67`, one CPU on CPU0–19 and 512MiB memory,
against the real Next PostgreSQL database:

- Two actual snapshots recovered all 22 logical calls: 6 accepted and 16 failed.
- All six accepted choices had complete, bound two-phase receipts; their mean
  latency was 443.985533s and nearest-rank P95 was 574.2109s.
- Calls 7030–7035 came from immutable archives; call 7034 was verified in actual
  event sequence 653334. All 44 native observations were retained.
- Repeating observation created no duplicate terminal files. Actual captures
  took 0.029191s and 0.032431s.
- A real lookup for a nonexistent soak exited unsuccessfully and preserved both
  the existing output bytes and its modification timestamp.

These operations generated no model requests, fits or database writes, and no
unit tests or CI were added. This is an observation repair, not generation or
latency recovery. Neither the failed original mechanism study nor either old
24-hour window is reset or certified. The new KV-cache diagnostic, fresh
qualification, live feedback closure and repaired-source 24 hours remain
separate work. Main training, draw-day 17:00 pause, official-result-only resume
and legacy retirement remain unchanged.
