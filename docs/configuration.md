[← back to README](../README.md)

# Configuration

## Common arguments (all `bpq_admin.py` actions)

| Argument | Required | Default | Description |
|---|---|---|---|
| `HOST` | yes* | — | Hostname or IP address of the BPQ node (positional, after the action). |
| `--user USER` | yes* | — | Node login user (typically your callsign). |
| `--port PORT` | no | `8010` | Telnet port of the node, from the Telnet Server section of `bpq32.cfg`. |
| `--password PASSWORD` | no | see below | Node login password. Prefer the env var or the interactive prompt — a password on the command line is visible in shell history and the process list. |
| `--timeout SECONDS` | no | `10` | How long to wait for each expected prompt (login, password, BBS `>`) before giving up. Raise this for slow links. |
| `--log-file PATH` | no | `bpq_admin.log` | Append a timestamped record of each action to this file (see [Logging](logging.md)). Pass `--log-file ''` to disable. |
| `--verbose` | no | off | On exit, dump the full session transcript to stderr. The first thing to reach for when something doesn't work. |

\* Every connection value can come from an environment variable instead of
the command line — see the next section. A value given on the command line
wins over the environment.

## Environment variables

Anything typed on the command line is captured in shell history and
visible in the process list while the command runs. To keep connection
details out of both, set them as environment variables instead:

| Variable | Replaces |
|---|---|
| `BPQ_HOST` | the positional `HOST` argument |
| `BPQ_PORT` | `--port` |
| `BPQ_USER` | `--user` |
| `BPQ_PASSWORD` | `--password` |

With all four set, the command is just `python bpq_admin.py list`.
Command-line values always override the environment. The password
resolution order is: `--password` (least safe), then `BPQ_PASSWORD`, then
an interactive prompt with hidden input (safest).

The [`notify-stale`](notify-stale.md) channels and the
[QRZ credentials](extract-emails.md#qrz-credentials-and-limits) for
`extract_emails.py` follow the same pattern; their variables are listed on
those pages.

## Recommended: a sourced env file

Typing `export BPQ_PASSWORD=...` at the prompt still lands in shell
history. Instead, put the exports in a file the shell reads, and lock it
down. The repo ships [`bpq.env.sample`](../bpq.env.sample) with every
variable both scripts understand — connection, QRZ, and the
`notify-stale` channels — ready to copy:

```bash
# Linux / macOS - once:
cp bpq.env.sample bpq.env      # then edit in your values
chmod 600 bpq.env

# per session:
source bpq.env
python bpq_admin.py list
```

```powershell
# Windows (PowerShell) - create bpq.env.ps1 with:
#   $env:BPQ_HOST = 'mynode.example.com'
#   $env:BPQ_PORT = '8010'
#   $env:BPQ_USER = 'N0CALL'
#   $env:BPQ_PASSWORD = 'yourpassword'
# then dot-source it per session:
. .\bpq.env.ps1
python bpq_admin.py list
```

The repo's `.gitignore` excludes `*.env`, `*.env.ps1`, and `*.env.bat`, so
a credential file created next to the script can't be committed by
accident. The variables live only in that shell session; environment
variables of a running process are readable by your own other processes
(and root), which is still a large improvement over shell history, where
they persist on disk indefinitely.
