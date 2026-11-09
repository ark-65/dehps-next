# Continuous training contention repair, 2026-11-09

Observed the Next lifecycle backend holding advisory lock740139 while workers
waited and exceeded their three-second lock timeout. The holder was scanning
artifacts/references in an idle-in-transaction client phase. Independently, an
actual primary Qwen call outlasted the two-candidate compute queue.

Isolated acceptance uses Python3.12 CPU, real Next PostgreSQL, the existing
eight-process/one-thread numerical contract and the shared eight-CPU training
slice. Next-only history/provenance is copied read-only into a separate Next
database. An explicitly labelled in-flight native-request fixture exercises
continuation scheduling; it is not new Qwen participation evidence.

Four continuation children executed400 fresh historical-origin fits and40,400
gradient steps. Every origin reported changed parameters, and every current
anchor had a distinct persisted weight hash. The primary retained-parent head
was unchanged, duplicate continuation admission was rejected, and all four
campaigns completed. Continuous container samples averaged2.49 CPU cores and
peaked at7.30; all90 intervals registered CPU work. These are short acceptance
observations, not a passed24h soak or a predictive improvement claim.

On the primary database, recursively extracted artifact-reference sets matched
the prior traversal exactly for2,095 retained nodes. An optimized dry collection
recorded2.496 seconds inside the claim fence; inventory outside that fence was
included separately in the4.652-second whole operation. Initial failed isolated
attempts remain preserved, including the logical-request lookup correction and
an acceptance assertion corrected to compare against the existing parent head.

Deployment and post-release runtime verification are recorded separately after
the current frozen primary campaign finishes. No unit tests, CI, dashboard or
test mail are added, and no legacy code/data/service is accessed.

After initial deployment, an actual sweep with retirement held the fence2.8739
seconds. An additional refinement moves historical node-reference registration
outside the fence, while freshly resolving every protected root inside it. The
primary-scale dry collection then held the fence0.4217 seconds (3.961 seconds
whole operation including inventory). Metadata discovery is separate from the
still-serialized deletion and graph-retirement decisions.
