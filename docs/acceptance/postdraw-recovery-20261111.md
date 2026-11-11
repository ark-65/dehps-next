# Postdraw recovery, 2026-11-11

The externally sealed forecast loop has no training recipe. Resource admission
incorrectly required one for its EVALUATE job, causing the worker to restart and
blocking both settlement and subsequent research. Evaluation now reserves one
CPU without inventing a training recipe. Training admission remains unchanged.

Verified official results can now receive an independent DRAW_RESULT outbox
identity while settlement is pending. This requires the complete official CWL
publication/source receipt and a prior final report. Repeated ticks deduplicate
it; later POST settlement remains independent. Prior reports are immutable.

Actual isolated Python3.12/Next PostgreSQL acceptance imported exact historical
facts (with prediction insertion triggers disabled only during the isolated
historical copy, restored transactionally). Actual report ticks produced one
result outbox row before settlement, repeated ticks kept one row, a real Worker
settled the actual sealed prediction, and a subsequent tick generated POST.
No acceptance SMTP attempt was made. Numeric identity is unchanged.

Production recovery settled2026129 from the original sealed prediction: blue06
missed official05, redTop100 maximum3/6. Official red is03 09 16 20 25 30.
The POST delivery was SMTP_ACCEPTED at2026-11-11 09:07:11 Shanghai; this is provider
acceptance, not recipient inbox confirmation. Production research then resumed
with newly successful tasks. Longer soak and predictive improvements are separate.

The frozen temporal study completed40 evaluations/4000 origin fits. All red
probabilities and Top100 lists stayed identical. Earlier500 blue totals were
parent32, small29, dense33, guarded37; losses2.836094/2.774608/2.844211/2.774782.
All three failed joint current/outer promotion. Current blue13 fell to7/6/7;
no replacement was activated. Uniform loss is2.772589, so smaller loss alone is
not established signal. A separate frozen prior-only probability-calibration
study now retains every parent blueTop1/red output while selecting shrinkage
on64 excluded earlier labels, with actual new inner fitting and explicit cached
baseline provenance. It does not claim a hit promotion or retune these holdouts.

Private receipts remain under runtime/postdraw-repair-20261111 and
runtime/blue-temporal-20261110. No new tests/CI, legacy changes or duplicate mail.
