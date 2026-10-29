# DEHPS Next owner workflow

Owner instruction, 2026-10-29. Applies to all future work in this repository.

- After creating every PR, Codex must manually squash-merge it using the exact reviewed head.
  Do not enable automatic merge. Verify the resulting merge commit and remote main.
- Do not write new unit tests. Validate behavior by running the real isolated Next application,
  inspecting its database/artifacts, and recording meaningful live acceptance evidence.
- Do not add useless CI or duplicate push/PR runs. The previous P1 workflow is manual-only.
- Preserve existing tests as historical reference; they are not a requirement to add more tests.
- Do not edit, delete, restart, mount, or write to legacy DEHPS code/data/services.
  P2 uses the already imported Next history; no additional legacy access is needed.
- Never hide failed experiments, fabricate evaluation outcomes, or call history replay forward evidence.
- Ordinary in-policy branch exploration, rollback, pruning and direction changes are autonomous.
- Keep secrets, raw datasets, model files and runtime caches out of Git. Commit only small intended reports.

