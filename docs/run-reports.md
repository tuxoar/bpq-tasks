[← back to README](../README.md)

# `run-reports` — count NTS traffic in a date range

Runs `LT` and reports the traffic messages in a date range: the matching
lines, then the starting message number, ending message number, and total.

```bash
python bpq_admin.py run-reports mynode.example.com --user N0CALL \
    --from 22-Oct --to 24-Oct
```

Prints the matching `LT` lines, then:

```
starting message: 301
ending message:   316
total messages:   14
```

| Argument | Required | Default | Description |
|---|---|---|---|
| `--from DATE` | yes | — | Start of the date range, inclusive. |
| `--to DATE` | yes | — | End of the date range, inclusive. |
| `--last N` | no | `800` | Only consider the latest `N` traffic messages (the `N` highest message numbers) before applying the date filter. |

`DATE` accepts `YYYY-MM-DD` (e.g. `2025-10-22`) or `DD-Mon` exactly as the
BBS displays it (e.g. `22-Oct`).

**Why `--last` exists:** BBS listing dates carry no year, so a `DD-Mon`
date (typed or listed) is resolved to its most recent occurrence on or
before today. A message from the same day-month a year earlier would be
indistinguishable by date alone; capping to the newest `N` messages keeps
the lookback well under a year on an active node. If your node handles
more than 800 traffic messages a year, raise `--last`. The tool prints a
note whenever the cap actually trims the listing.
