# bpq-tasks

Command-line administration tooling for a [BPQ32/LinBPQ](https://www.cantab.net/users/john.wiseman/Documents/) packet-radio node.

Two scripts:

- **`bpq_admin.py`** connects to your node's telnet port, logs in, enters
  the BBS, performs one action, and logs out cleanly — so routine chores
  (checking mail, clearing housekeeping reports, counting NTS traffic,
  archiving old messages) become single commands you can run by hand or on
  a schedule.
- **`extract_emails.py`** works on the message files `export-stale`
  produces, recovering each recipient's email address from the radiogram
  text and, optionally, from [QRZ.com](https://www.qrz.com) — then writes
  a ready-to-send email for each message it finds an address for, and a
  printable letter for postal delivery for each message it doesn't.

Both are single Python files with **no dependencies**, and run unmodified
on Windows, macOS, and Linux.

## What it can do

`bpq_admin.py ACTION` — each action links to its own page:

| Action | What it does |
|---|---|
| [`list`](docs/listing.md) | Run `LPN` and print your private new messages. |
| [`list-held`](docs/listing.md) | Run `LH` and print every held message — traffic the BBS is holding back from forwarding. |
| [`clean-housekeeping`](docs/clean-housekeeping.md) | Find every `SYSTEM Housekeeping Results` message in `LPN` and kill each one, verified against the BBS reply. Supports `--dry-run`. |
| [`run-reports`](docs/run-reports.md) | Run `LT` and report the traffic messages in a date range: the matching lines, then the starting message number, ending message number, and total. |
| [`export-stale`](docs/stale-traffic.md#export-stale) | Find traffic messages older than a cutoff, read each one, and save them to a timestamped folder — one file per message plus an index. |
| [`kill-exported`](docs/stale-traffic.md#kill-exported) | Kill the messages named by an export folder — the cleanup step once those messages have been delivered. Supports `--dry-run`. |
| [`notify-stale`](docs/notify-stale.md) | List stale traffic and the new private mail nothing is forwarding on (read-only), and send a notice to every Discord webhook, Telegram bot, and/or email relay configured in the environment. Built for a scheduled run. |
| [`check-routing`](docs/check-routing.md) | Report every traffic message whose To header will not route (`13743@NTSNY` / `B0W2J0@NTSNS` are proper forms), optionally audited by sender. Read-only; exit 1 when anything is flagged. |

[`extract_emails.py`](docs/extract-emails.md) then reads an exported
folder, decodes the phonetically-spelled addresses, looks up the rest on
QRZ, and writes `emails.txt` plus printable letters.

## Quick start

You need Python **3.8 or newer** and nothing else — see
[Getting started](docs/getting-started.md) for per-platform install notes.

```bash
git clone <this-repo-url>
cd bpq-tasks
python bpq_admin.py list mynode.example.com --port 8010 --user N0CALL
```

You'll be prompted for your password, then see your new private messages.
Every other action is the same command shape:
`python bpq_admin.py ACTION HOST --user USER [options]`.

Connection details can live in environment variables (`BPQ_HOST`,
`BPQ_USER`, `BPQ_PASSWORD`, ...) instead of the command line — the safer
default. See [Configuration](docs/configuration.md).

## Documentation

- [Getting started](docs/getting-started.md) — installing Python, first run.
- [Configuration](docs/configuration.md) — common arguments, environment
  variables, and the sourced-env-file recipe that keeps credentials out of
  shell history.
- [Listing messages](docs/listing.md) — `list` and `list-held`.
- [Clearing housekeeping reports](docs/clean-housekeeping.md) — `clean-housekeeping`.
- [Traffic reports](docs/run-reports.md) — `run-reports`, and why `--last` exists.
- [The stale-traffic workflow](docs/stale-traffic.md) — `export-stale` and
  `kill-exported`, end to end.
- [Recovering email addresses](docs/extract-emails.md) — `extract_emails.py`,
  printing the letters, QRZ credentials and limits.
- [Stale-traffic notices](docs/notify-stale.md) — `notify-stale` on a
  schedule, covering stale traffic and stuck private mail; channel setup
  detail in the [notifier spec](docs/stale-notifier-spec.md).
- [Routing checks](docs/check-routing.md) — `check-routing` and the
  per-sender audit.
- [Logging, output, and exit codes](docs/logging.md)
- [Troubleshooting](docs/troubleshooting.md)

## Technical notes

`bpq_admin.py` speaks telnet over a raw socket on purpose: Python's stdlib
`telnetlib` was removed in 3.13, and BPQ's telnet server only needs IAC
option requests refused. On entering the BBS it captures the node's exact
prompt line (e.g. `de N0CALL>`) and only stops reading on that string, so
message bodies containing `>` — routine in NTS traffic — can't truncate a
read. The `BpqSession` class in `bpq_admin.py` (login / enter_bbs /
bbs_command / logout) is the extension point if you want to script other
BBS commands.
