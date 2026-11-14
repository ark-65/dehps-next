# Qwen admission observer native transport acceptance

After the owner rebooted the host on 2026-11-14, the existing admission observer intermittently timed out while reading Docker metadata. It correctly retained the previous observation timestamp, which held candidate work under the unchanged 30-second freshness guard.

The observer now reads its three owned primary containers through the local Docker Unix socket and runs the same read-only PostgreSQL query and authoritative draw-window function through bounded exec requests. It validates multiplexed output and the completed exec exit code. The original aggregate 8-second running-state deadline, 12-second exec deadlines, 8-second SQL timeout, admission fields, 30-second freshness, 900/60-second priority rules, and verified-result-only resume remain unchanged. Missing or incomplete metadata still cannot refresh an observation.

Actual read-only measurements on the running Next system:

| Measurement | Previous CLI | Native Unix API |
| --- | ---: | ---: |
| Eight paired running-state reads, mean seconds | 0.470041 | 0.033519 |
| Eight paired running-state reads, maximum seconds | 1.517806 | 0.155135 |
| Ten paired complete observations, mean seconds | 3.339508 | 2.034854 |
| Ten paired complete observations, maximum seconds | 8.294349 | 4.905283 |
| Complete-observation failures | 0/10 | 0/10 |

Verified official-draw fields matched in every successful whole-observer read. Model calls, new fits, primary database writes, and soak-clock resets were all zero. No new unit tests or CI were added. Private measurement artifacts remain outside Git under `runtime/operations/qwen-host-telemetry-transport-20261114`.

These measurements demonstrate reduced metadata overhead. They do not establish the sole cause of earlier timeouts, a completed 24-hour observation, a Qwen generation repair, deployment of the candidate backend, report delivery, or predictive improvement. Earlier failures and the host-reboot interruption remain retained.
