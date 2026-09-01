[← back to README](../README.md)

# `check-routing` — find traffic that won't route

NTS traffic only moves if its To header is
`<postal code>@NTS<two-letter region>` — a US zip with a real USPS
state/territory abbreviation (`13743@NTSNY`), or a Canadian postal code
with a real Canada Post province abbreviation (`B0W2J0@NTSNS`). The code
style must match the region: a US zip routed to a province
(`13743@NTSNS`) or a Canadian code routed to a state (`B0W2J0@NTSNY`) is
flagged too. A message that arrives with anything else — a bare zip with
no route (`08753`), a callsign where the zip belongs, junk glued to the
zip (`NTS11234@NTSNY`), or a made-up region (`14424@NTSZZ`) — sits on
the node unrouted. This action inspects every traffic message in `LTN`
and reports the offenders:

```bash
python bpq_admin.py check-routing mynode.example.com --user N0CALL
```

```
320    25-Oct TF     400 08753          W2QS   TOMS RIVER
    msg 320: To reads '08753' - expected the form 13743@NTSNY

1 of 18 traffic message(s) will not be routed properly
```

| Argument | Default | Description |
|---|---|---|
| `--pattern REGEX` | US or Canadian form | What a routable To header must fully match, case-insensitively. The default accepts a 5-digit zip `@NTS` + a genuine USPS state/territory abbreviation, or a Canadian postal code (`A9A9A9`) `@NTS` + a genuine Canada Post province abbreviation. Override if your hub routes on a different scheme. |
| `--show-all` | off | Print every message checked and the routing header it carries — `OK` or `BAD` per message — not just the offenders. With `--senders`, include senders with a clean record. |
| `--senders` | off | Audit the **full `LT` history** instead of just the new traffic in `LTN`, grouped by sender — see below. |

With `--show-all` the output is one row per traffic message:

```
   316  OK   14424@NTSNY
   317  BAD  14424@NTSZZ
   320  BAD  08753
```

## Which senders keep doing this

`--senders` answers the follow-up question: it scans every traffic
message in the full `LT` history (not just the new ones) and groups the
bad headers by the From callsign, so the stations that repeatedly
originate unroutable traffic stand out — useful for a polite word with
the sender rather than fixing messages one at a time forever:

```bash
python bpq_admin.py check-routing mynode.example.com --user N0CALL --senders
```

```
SENDER   BAD  TOTAL  EXAMPLES
W2PAX      3     41  08753 (msg 2872), NTS11234@NTSNY (msg 2901), 07724 (msg 2955)
KD2XYZ     1      2  BOB@NTSNY (msg 3010)

2 of 9 sender(s) have created bad headers (4 of 118 message(s))
```

Up to three example headers are shown per sender, with the message IDs
to inspect. `TOTAL` is how many traffic messages that station sent in
the scanned history, so a 3-of-41 sender reads differently from a
1-of-1.

Read-only on the BBS (it only lists), so it is safe to run on a schedule;
the exit code is 1 whenever anything is flagged, 0 when every header is
clean — so a cron run surfaces bad traffic the moment it arrives. Fixing
a flagged header is done outside this tool (edit the message from the BPQ
web interface or sysop console).
