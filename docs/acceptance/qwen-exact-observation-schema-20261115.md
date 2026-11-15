# Exact observation copying before Qwen generation

Primary call7194 returned a complete response after801.591 seconds, but assigned
utilities0 or1 to all six untried candidates whose supplied utilities were null.
The original comparison validator correctly rejected it. Its two real training
feedback records were present in the actual request; their presence alone did
not establish a successful feedback closure. The failed response remains intact.

The optional profile field
`observation_grammar: candidate-utility-enum-v1` adds a singleton enum to each
candidate's `known_utility` generation property. It copies the exact supplied
value, including zero, negative numbers and null. Candidate records are copied
separately because the original schema shares one record object across IDs.
Rankings and selections retain their original alternatives; no oracle choice is
inserted. The returned response is never repaired. Profiles without the field
retain their original schema.

This changes the declared request schema for a new profile, rather than claiming
byte-identical requests or relabelling an old qualification. The original
selection-validation body is unchanged: its actual Python3.12 AST hash remains
`dcb9682b5d3acc3e1e71e2cbef55f8a57eefb6fbe42c11f7e704743acd425758`.
The new source and guard have their own identities, and the guard identity also
covers the new binding module. All nine numerical training files are unchanged.

The installed Python3.12.13 CPU application, Torch2.15.0+cpu and NumPy2.5.4 ran
against a dedicated real Next PostgreSQL database with an explicitly synthetic
loopback provider. All five cases passed: legacy schema, new null values, mixed
null/zero/positive/negative values, a deliberately violating provider response,
and an unknown profile version. The violating response remained unchanged and
was rejected by the original validator; the unknown version was rejected before
any provider request. Actual stored logical requests and both provider phases
confirmed the schema reached the real inference path. Removing only the new
utility enums reproduced the original schema. Write accounting stayed bounded.

These were eight synthetic provider requests, zero actual Qwen calls and zero
new fits, with no primary mutation, GPU, weights, official draws or mail. They
validate application wiring and refusal behavior, not decoder support, selection
quality, latency or predictive benefit. The first build's stale guard expectation
and the interrupted image-publication attempts remain recorded separately.

The source has not been deployed or activated. A new profile still requires fresh
frozen144-call quality/latency validation, the original fixed24-pair comparison,
completed-boundary deployment, actual selected training and later feedback, and
its own completed24-hour observation. Preserve the original inputs, seeds,
512/1024 budgets,16k context, accuracy/stability/position/lift and240/300-second
criteria, negative futility rule,17:00 pause and authoritative-result-only resume.
Previously performed answers, failed studies and observation hours are retained;
none become evidence for the new profile. Legacy DEHPS is untouched.
