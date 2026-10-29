# DEHPS Next development boundaries

- Work only in this repository and its explicitly named Next containers/database.
- Never edit, delete, restart or mount legacy DEHPS code, data or services.
- The owner authorizes read-only history export from the legacy draw table into Next.
  Use SELECT-only transactions with limits/timeouts; no legacy training-table reads or writes.
- Keep the v1.1 architecture under docs/architecture. P0/P1 is an execution and learning core;
  branch intelligence, math research, full retention and business acceptance are later stages.
- Red Top100 and a single blue Top1 are separate outputs. Blue 50% is an unproven target.
- Historical replay, synthetic tests and genuine pre-draw forward evidence must stay distinct.
- Protect prior-only features, immutable sealed predictions, real parameter updates,
  consumed-label provenance, automatic next tasks, lease fencing and bounded artifact writes.
- Read git status before edits. Preserve unexpected user changes.
- Do not commit credentials, runtime receipts, model files, volumes or generated caches.
- Use the isolated Python 3.12 CPU container environment and real Next PostgreSQL for tests.
- Report code/test, live execution, sustained soak, report delivery and predictive evidence separately.
