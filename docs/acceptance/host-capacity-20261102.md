# Capacity sampling recovery,2026-11-02

Live Next host receipts showed repeated30second Docker `/system/df` timeouts.
The collector invalidated its entire sample, causing HOST_ACCOUNTING_INCOMPLETE
and aborting one isolated long Qwen request at its renewal boundary. This was
missing telemetry rather than observed low memory/disk; it is not a semantic
candidate-selection error.

The collector now bounds shared-cache storage by the whole verified backing
device. It explicitly reports this as an upper bound, never attributed cache
consumption. Current free disk, memory, container usage and owned-artifact
accounting are still sampled. A separately mounted Docker device fails closed
pending verification. No global disk-usage scan or cache pruning is introduced.
The existing physical admission thresholds, leases, fitting and numerical gates
are unchanged.

Actual Next host sampling returned complete records again, with approximately
18GB available memory while local Qwen and CPU fitting continued. Source/merge,
final host-service reload, continuous observation and model quality are separate
states. The interrupted inference is retained and must be retried at the same
frozen slot; it cannot be scored as an incorrect choice or counted as new fitting.
No new unit tests/CI, test email, or legacy access was used.
