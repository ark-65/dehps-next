# Qwen recovery: actual primary closed-loop evidence

Date: 2026-11-12, Asia/Shanghai. The actual engineering chain is verified:
Qwen selection → two fresh candidate trainings → both exact outcomes in one
later successful Qwen request, with individual delivery receipts. This adds live
evidence to [pre-deployment acceptance](qwen-output-recovery-20261112.md); it does
not rewrite that earlier pending state or establish predictive improvement.

## Repair and protected transition

[PR48](https://github.com/ark-65/dehps-next/pull/48) was manually squash-merged at
reviewed head, producing `fca1763966e53cab2c312dfea7553a1a5e625004`.
The deployed controller identity is
`981cd97c9e676df7fd3137b026995949922f6a69a5c3cc38ccd6debc3f3371a1`;
the unchanged numeric identity is
`9cbb1aaf437410dce1dbe24d38cbebca2b2018cd2723ebeb757b3f3917ac2b06`.
The source-bound short-output guard identity is
`4a46a8034986e81c17ad863a547b8498618c66357a1b70a0d7b755a265fde9b3`.

The original short repetition escaped a 2,048-character guard and poisoned the
structured answer; the resulting permanent semantic fault suppressed later
provider calls. The added guard rejects demonstrated short loops without
rewriting an answer. Certified recovery permits a genuinely new task after the
existing feedback/time gates; the error remains latched until actual successful
two-stage selection and receipt validation. Failed answers remain evidence.
Native/partial token receipts survive later failures. The existing training
recovery module remains unchanged. See the
[recovery architecture](../architecture/qwen-output-recovery.md).

The original 144-slot native-output replay preserves all 141 formerly valid
outputs and all three invalid cases; the demonstrated failed prefix is detected
at character 285. Original mechanism and latency gates, profile/model, prompts,
512/1024 budgets, 16k context, full GPU offload, 1,800-second/20-feedback cadence,
numeric threads and promotion/qualification gates were retained.

The 17:00 pause stayed active until complete official verification. The normal
source recorded issue 2026130 at **21:58:05.683054**, source
`00ddf72c8b5cc1ec93121e631c4faabf46208c95f225c9bc6a37f748cb27b128`.
The workflow then drained the existing frozen campaign before adopting the
controller at 21:59:41 and deploying at 21:59:47. No clock override or manual
fault clearance was used. Adoption asserted unchanged retained-parent head,
champion spec and already-sent report. The equivalent worker quota is
`1200000/100000`, CPU affinity `0-19`; no Docker daemon restart was required.
Only the named Next application services were recreated; PostgreSQL and the
inference service stayed running. Legacy code/data/services were not accessed.

## New actual selection and training

Production profile:
`9d49fd06c6043c6c8f8f9a8520a9a561b3e018534ebe62ac311de0b492b659b6`.
After 20 new comparable feedback outcomes, selection **6980** started at
22:05:28.787639 with thinking call **6981**. The structured answer stopped
normally and passed the existing validators. Audit **25706** records actual
comparative selection. Recovery audit **25707** at 22:09:26 records
`RECOVERED_BY_ACTUAL_SELECTION`; only then did the fault become null.

Both selected candidates completed real new training. Each updated parameters
across 100 fresh origin fits; score and publication-anchor artifacts were read
and verified. Counts below are historical recent100/50/10, not forward draws.

| Node | Fresh fits | Gradient steps | Red 5+ counts (100/50/10) | Blue Top1 hits (100/50/10) | Verdict |
| --- | ---: | ---: | --- | --- | --- |
| `739497556274514e3e4c3e8592491e83ccc2108076cad1f2ef9a371b00c5128c` | 100 | 8,181 | 3/2/0 | 10/6/1 | INCONCLUSIVE |
| `df610386138e7a4d1e9244eac93687b864a8fac8da4948b6e34d6958db670582` | 100 | 16,059 | 3/2/0 | 9/6/1 | INCONCLUSIVE |

Their completion times were 22:09:43.115975 and 22:10:14.605231. Both identities,
recipe hashes, exact outcomes, execution counts, memory events and artifact
references were frozen in study `qwen-recovery-chain-20261112-6980`, protocol
hash `74cd308b17b22f485146619dd55649474a7842b7553f6218fba004a93fffac7a`.
Neither candidate established joint improvement or replaced the accepted parent.

## Actual feedback delivery

The next selection **6982** started at **22:36:40.896895**, after the unchanged
1,800-second interval and sufficient new comparable outcomes. Thinking call
**6983** and the final answer both succeeded. At 22:42:33, the existing strict
`scripts/verify-qwen-feedback-closure.py` persisted
`BOTH_FEEDBACK_CLOSED_LOOP_VERIFIED` for the frozen study.

The verifier read the actual logical request, native thinking request and final
answer prompt, checked their exact correspondence and source-local provider
receipts, and required both frozen recipes/outcomes in this same later request:

| Original candidate | Actual request key | Delivery memory event | Later audit/call |
| --- | --- | ---: | --- |
| `739497556274…` | f0 | 614928 | 25761 / 6982 |
| `df610386138e…` | f1 | 614929 | 25761 / 6982 |

Both individual acknowledgments were inserted at 22:42:22.413147. This is actual
successful delivery, not a watermark, queued feedback, replay or synthetic input.
Both calls retained full GPU offload: size and VRAM 3,872,391,167 bytes, context
16,384. Native counts and wall times were:

| Call | Role | Input tokens | Output tokens | Completion | Wall seconds |
| --- | --- | ---: | ---: | --- | ---: |
| 6981 | First thinking prefix | 3,301 | 512 | length (bounded prefix) | 128.998 |
| 6980 | First selection | 3,815 | 468 | stop | 238.052 including prefix |
| 6983 | Later thinking prefix | 3,560 | 512 | length (bounded prefix) | 187.101 |
| 6982 | Later selection | 4,074 | 592 | stop | 341.450 including prefix |

The second live call is slow. These two production observations do **not** pass
a new 144-slot latency study, and no latency gate was widened. The original
frozen study remains mean 155.213 / p95 203.339 seconds against 240/300 limits. Current
production latency and sustained stability require further elapsed observations;
this record establishes recovery and the closed loop, not a new performance or
24-hour-soak acceptance.

## Final live snapshot and limits

At **22:44:15**, primary generation **5891** was `RUNNING`, with active/ready
training and planning jobs and the Qwen fault null. Since controller cutover,
140 nodes had completed, 108 with newly executed origin fits: **10,800 new fits
and 1,216,844 gradient steps**. Other completed/reused work is not counted as new
fits. The latest completed training was 22:43:59.616599. Primary training remains
running under the existing draw, resource, lease, storage and integrity gates.

The then-current accepted parent had red counts 3/2/0 and blue hits 14/8/3 in the
historical 100/50/10 windows. Its anchor, scores and dataset artifacts were read
successfully. Normal campaign baseline lineage may advance; the repair did not
reset champion parameters, replace the parent with either inconclusive child,
or change acceptance gates. No blue hit-rate improvement is established here.

Today's actual provider totals are **14,750 input / 2,084 output** tokens,
16,834 combined. Recorded cumulative total is 9,580,354. Today's missing-count
records are 0; the historical 58 remain unestimated. There is no external billing
or artificial daily token/call cutoff.

The original 2026130 PRE_FINAL remains immutable, digest
`9bbcca2c4437bb50141b5e55c6ef4fc48851c6c56650a03355080c5e14032622`,
SMTP accepted 17:00:31.746709. Normal POST was SMTP accepted 21:58:23.045052.
These are transport receipts, not proof of inbox receipt. No test or duplicate
mail was sent. The added Qwen health line was previewed against live state and
applies to future normally queued reports; previously sent mail was not rewritten.

Private runtime evidence remains excluded from Git in
`runtime/operations/qwen-recovery-20261112/`: official gate, controller adoption,
deployment, frozen pair, strict closed-loop proof and final live snapshot. Raw
provider requests/responses, DB receipts, model files and caches are not committed.
