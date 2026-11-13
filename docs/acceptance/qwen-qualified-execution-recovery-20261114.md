# Recovery replay for a separately qualified execution profile

Previously the recovery replay tool selected only the active profile and required
the historical failure to have that profile ID. This prevented certifying a new
execution profile before activation. The optional `--profile-id` now selects a
registered profile without activating it or clearing recovery state.

Explicit selection requires that profile's completed 144-slot qualification to
match the current controller, numerical identity and output guard. It also
requires complete 144/288 logical/native hardware bindings and complete primary
interval observation with no overlap. The existing quality and latency gates
remain unchanged. The historical failed prefix must belong to the same model,
semantic framing, sampling, budgets and cadence; only the execution backend and
explicit batch size 512 may differ. All original answers remain intact.

Actual validation used Python 3.12.13 and one repeatable-read, read-only Next
primary PostgreSQL transaction, with an eight-second statement timeout:

- Replayed the original 144 actual answers: 141 valid, zero valid answers rejected,
  and all three invalid answers preserved.
- Detected the retained historical failed prefix at character 285 of 869.
- Rejected explicit use of the historical qualification for the current source.
- Native row count remained 69 within that snapshot; no inference, fitting,
  profile activation, state change or certificate registration occurred.

The earlier isolated clone lacked profile records. A subsequent startup check
also confirmed that `Database` supplies connection options overriding
`PGOPTIONS`. Those failed validation attempts remain recorded. The completed
validation explicitly used a pinned read-only transaction for every query.

This validates historical replay and refusal of stale qualification. A genuinely
new profile's positive path still requires its actual fresh qualification and
runtime acceptance. These results do not establish generation repair, deployment,
a live feedback loop, 24-hour stability, report delivery or predictive benefit.
