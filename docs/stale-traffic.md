[← back to README](../README.md)

# The stale-traffic workflow: `export-stale` and `kill-exported`

Traffic that sits undelivered on the node eventually needs a human: export
it, contact the addressees, then remove it from the BBS. The full workflow
is three commands:

```bash
python bpq_admin.py export-stale mynode.example.com --user N0CALL --days 60
python extract_emails.py stale-20260831-081810           # emails.txt + letters/
# ... send the emails, print and mail the letters ...
python bpq_admin.py kill-exported mynode.example.com --user N0CALL \
    --dir stale-20260831-081810
```

The middle step is `extract_emails.py`, documented on its own page:
[Recovering email addresses](extract-emails.md). For unattended monitoring
*between* delivery passes, see [`notify-stale`](notify-stale.md).

## `export-stale`

Runs `LTN`, finds traffic messages older than a cutoff, reads each with
`R <id>`, and saves them to a timestamped folder — one file per message
plus an index.

```bash
# Export traffic messages 60+ days old into exports/stale-YYYYMMDD-HHMMSS/
python bpq_admin.py export-stale mynode.example.com --user N0CALL \
    --days 60 --out exports
```

| Argument | Default | Description |
|---|---|---|
| `--days N` | `3` | A message is stale when it is `N` or more days old. |
| `--out DIR` | `.` | Parent directory in which the per-run folder is created. |

Each run creates a folder named `stale-YYYYMMDD-HHMMSS` (Windows-safe, no
colons) containing one `msg_<id>.txt` per exported message — the full
output of `R <id>` — plus an `index.txt` listing everything exported and
the cutoff date used.

Two things to know: reading a message marks it read on the BBS, so exported
messages drop out of future `LTN` listings; and the year-less-date caveat
applies in reverse — a message over a year old looks recent by its listing
date, so export more often than yearly.

## `kill-exported`

The last step of the workflow: once an export folder's messages have been
delivered (emailed via `emails.txt`, letters printed and mailed), remove
them from the BBS. The folder itself is the kill list — every
`msg_<id>.txt` in it names one message to kill:

```bash
# Preview - reads only the folder, no connection, no credentials needed
python bpq_admin.py kill-exported --dir stale-20260831-081810 --dry-run

# Kill them on the node
python bpq_admin.py kill-exported mynode.example.com --user N0CALL \
    --dir stale-20260831-081810
```

| Argument | Default | Description |
|---|---|---|
| `--dir DIR` | required | Export folder whose `msg_<id>.txt` files name the messages to kill. Other files in the folder (`index.txt`, `emails.txt`, `letters/`) are ignored. |
| `--dry-run` | off | Print the message IDs that would be killed and exit — without connecting to the node at all. |

Every kill is verified against the BBS reply, exactly like
[`clean-housekeeping`](clean-housekeeping.md): an unconfirmed kill (for
example a message that was already killed by hand) is reported on stderr
and makes the exit code 1, while the remaining kills still proceed.
Because the export folder never changes, re-running after a partial
failure is safe — already-dead messages just show up as unconfirmed.
