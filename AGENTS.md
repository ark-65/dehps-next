# DEHPS Next development boundaries

- Read and follow `AGENT.md`: the owner requires manual Codex squash merges after every PR,
  no new unit tests and no useless CI. Use actual isolated runtime acceptance instead.

- Work only in this repository and its explicitly named Next containers/database.
- Never edit, delete, restart or mount legacy DEHPS code, data or services.
- The owner authorizes read-only history export from the legacy draw table into Next.
  Use SELECT-only transactions with limits/timeouts; no legacy training-table reads or writes.
- Keep the v1.1 architecture under docs/architecture. P0-P3 include learning, bounded research,
  resource admission and owned-artifact lifecycle. Sustained shadow/business acceptance is P4.
- Red Top100 and a single blue Top1 are separate outputs. Blue 50% is an unproven target.
- Historical replay, synthetic tests and genuine pre-draw forward evidence must stay distinct.
- Protect prior-only features, immutable sealed predictions, real parameter updates,
  consumed-label provenance, automatic next tasks, lease fencing and bounded artifact writes.
- Read git status before edits. Preserve unexpected user changes.
- Do not commit credentials, runtime receipts, model files, volumes or generated caches.
- Use the isolated Python 3.12 CPU container environment and real Next PostgreSQL for live validation.
- Report code/test, live execution, sustained soak, report delivery and predictive evidence separately.
- Latest owner scope: mail is the primary interface; do not develop a dashboard.
  Keep existing read-only status APIs. Do not migrate or mutate the legacy mail/update services.
  Reuse only the explicitly authorized recipient/SMTP configuration via a private Next-only file.
