# bpq-tasks

Command-line administration tooling for a [BPQ32/LinBPQ](https://www.cantab.net/users/john.wiseman/Documents/) packet-radio node.

The tool, `bpq_admin.py`, connects to your node's telnet port, logs in,
enters the BBS, performs one action, and logs out cleanly — so routine
chores (checking mail, clearing housekeeping reports, counting NTS traffic,
archiving old messages) become single commands you can run by hand or on a
schedule.

It is a single Python file with **no dependencies**, and runs unmodified on
Windows, macOS, and Linux.

## What it can do

| Action | What it does |
|---|---|
| `list` | Run `LPN` and print your private new messages. |
| `clean-housekeeping` | Find every `SYSTEM Housekeeping Results` message in `LPN` and kill each one with `K <id>`. Nothing else is touched, and every kill is verified against the BBS reply. Supports `--dry-run`. |
| `run-reports` | Run `LT` and report the traffic messages in a date range: the matching lines, then the starting message number, ending message number, and total. |
| `export-stale` | Run `LTN`, find traffic messages older than a cutoff, read each with `R <id>`, and save them to a timestamped folder — one file per message plus an index. |

## Getting Python

You need Python **3.8 or newer** (3.13+ works — the script doesn't use the
removed `telnetlib` module). No packages to install; the standard library
is enough.

**Windows** — install from [python.org/downloads](https://www.python.org/downloads/)
(check **"Add python.exe to PATH"** during install), or from a terminal:

```powershell
winget install Python.Python.3.12
```

Then run scripts with either `python` or the `py` launcher:

```powershell
py bpq_admin.py list mynode.example.com --user N0CALL
```

If typing `python` opens the Microsoft Store instead of Python, use `py`,
or disable the Store alias under *Settings → Apps → Advanced app settings →
App execution aliases*.

**macOS** — macOS no longer ships Python. Install with
[Homebrew](https://brew.sh) (`brew install python`) or the
[python.org](https://www.python.org/downloads/) installer, then use
`python3`:

```bash
python3 bpq_admin.py list mynode.example.com --user N0CALL
```

**Linux** — almost always preinstalled as `python3`. If not:
`sudo apt install python3` (Debian/Ubuntu), `sudo dnf install python3`
(Fedora), or `sudo pacman -S python` (Arch).

```bash
python3 bpq_admin.py list mynode.example.com --user N0CALL
# or make it directly executable:
chmod +x bpq_admin.py
./bpq_admin.py list mynode.example.com --user N0CALL
```

Check your install with `python3 --version` (or `py --version` on Windows).

> The examples below use `python`; substitute `python3` or `py` as your
> system requires.

## Quick start

1. Get the tool:

   ```bash
   git clone <this-repo-url>
   cd bpq-tasks
   ```

   (Or just download `bpq_admin.py` — it is self-contained.)

2. Find your node's telnet details: the host is wherever your node runs,
   and the port is the one configured in the Telnet Server section of
   `bpq32.cfg` (commonly `8010`). Your login is usually your callsign and
   the password from your node user entry.

3. List your new private messages:

   ```bash
   python bpq_admin.py list mynode.example.com --port 8010 --user N0CALL
   ```

   You'll be prompted for your password, then see something like:

   ```
   Connected to mynode.example.com:8010
   Logged in, entering BBS...
   BBS login successful (prompt 'de N0CALL>')
   running LPN ...
   3309   31-Aug PN      22 W2QS   @W2QS   W2QS   test
   ```

If that works, everything else is the same command shape:
`python bpq_admin.py ACTION HOST --user USER [options]`.

## Usage reference

### Common arguments (all actions)

| Argument | Required | Default | Description |
|---|---|---|---|
| `HOST` | yes* | — | Hostname or IP address of the BPQ node (positional, after the action). |
| `--user USER` | yes* | — | Node login user (typically your callsign). |
| `--port PORT` | no | `8010` | Telnet port of the node, from the Telnet Server section of `bpq32.cfg`. |
| `--password PASSWORD` | no | see below | Node login password. Prefer the env var or the interactive prompt — a password on the command line is visible in shell history and the process list. |

\* Every connection value can come from an environment variable instead of
the command line — see the next section. A value given on the command line
wins over the environment.
| `--timeout SECONDS` | no | `10` | How long to wait for each expected prompt (login, password, BBS `>`) before giving up. Raise this for slow links. |
| `--log-file PATH` | no | `bpq_admin.log` | Append a timestamped record of each action to this file (see Logging). Pass `--log-file ''` to disable. |
| `--verbose` | no | off | On exit, dump the full session transcript to stderr. The first thing to reach for when something doesn't work. |

### Environment variables

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

**Recommended: a sourced env file.** Typing `export BPQ_PASSWORD=...` at
the prompt still lands in shell history. Instead, put the exports in a
file the shell reads, and lock it down:

```bash
# Linux / macOS - create bpq.env (once), then source it per session
cat > bpq.env <<'EOF'
export BPQ_HOST=mynode.example.com
export BPQ_PORT=8010
export BPQ_USER=N0CALL
export BPQ_PASSWORD=yourpassword
EOF
chmod 600 bpq.env

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

### `clean-housekeeping`

```bash
# Preview first - prints the IDs it would kill, sends no K commands
python bpq_admin.py clean-housekeeping mynode.example.com --user N0CALL --dry-run

# Actually kill them
python bpq_admin.py clean-housekeeping mynode.example.com --user N0CALL
```

| Argument | Default | Description |
|---|---|---|
| `--dry-run` | off | Print the message IDs that would be killed, then exit without killing anything. Run this first. |

Only lines matching the exact shape
`<id> <date> PN <size> SYSOP SYSTEM Housekeeping Results` are killed — an
ordinary user message, even one mentioning housekeeping in its subject,
cannot match. Any kill the BBS does not confirm is reported and makes the
exit code 1.

### `run-reports`

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

### `export-stale`

```bash
# Export traffic messages 60+ days old into exports/stale-YYYYMMDD-HHMMSS/
python bpq_admin.py export-stale mynode.example.com --user N0CALL \
    --days 60 --out exports
```

| Argument | Default | Description |
|---|---|---|
| `--days N` | `30` | A message is stale when it is `N` or more days old. |
| `--out DIR` | `.` | Parent directory in which the per-run folder is created. |

Each run creates a folder named `stale-YYYYMMDD-HHMMSS` (Windows-safe, no
colons) containing one `msg_<id>.txt` per exported message — the full
output of `R <id>` — plus an `index.txt` listing everything exported and
the cutoff date used.

Two things to know: reading a message marks it read on the BBS, so exported
messages drop out of future `LTN` listings; and the year-less-date caveat
applies in reverse — a message over a year old looks recent by its listing
date, so export more often than yearly.

## Logging

Every run appends a timestamped audit record to the log file (default
`bpq_admin.log` in the current directory):

```
2026-08-31 08:00:00 INFO --- clean-housekeeping: connecting to mynode:8010 as N0CALL
2026-08-31 08:00:01 INFO logged in as N0CALL
2026-08-31 08:00:01 INFO entered BBS (prompt 'de N0CALL>')
2026-08-31 08:00:01 INFO running BBS command 'LPN'
2026-08-31 08:00:03 INFO BBS command 'LPN' -> 27 line(s) of output in 2.1s
2026-08-31 08:00:03 INFO killed message 3308 (confirmed)
2026-08-31 08:00:04 INFO killed 26 of 26 housekeeping message(s)
2026-08-31 08:00:04 INFO logged out
2026-08-31 08:00:04 INFO --- clean-housekeeping finished with exit code 0
```

What gets logged: connections, logins (username only — the password is
never written), every BBS command with its duration, every kill and
whether the BBS confirmed it (unconfirmed kills are WARNING records),
dry-run would-kill lists, and the final exit code. Failures are ERROR
records with the reason. The file grows without rotation; trim it
externally if you run on a schedule long-term.

Logs and exported messages contain real callsigns, hostnames, and message
content — the repo's `.gitignore` keeps them out of version control.
Leave it that way if you fork this publicly.

## Output and exit codes

- Action results (listings, `killed <id>` lines, summaries) go to
  **stdout**; status and errors go to **stderr**, so stdout pipes and
  redirects cleanly.
- Exit code `0` on success, `1` on any failure (connection refused, login
  rejected, expected prompt never seen, or an unconfirmed kill), `2` for
  invalid arguments. Failure messages include the text the node actually
  sent.

## Troubleshooting

**It hangs, then reports "never saw a login prompt".** Run with
`--verbose` to see exactly what the node sent. The script recognizes login
prompts containing `user:`, `callsign:`, or `login:` and password prompts
containing `password:` (case-insensitive) — BPQ's defaults. If your
`bpq32.cfg` uses custom `LOGINPROMPT`/`PASSWORDPROMPT` values, adjust the
`LOGIN_PROMPTS`/`PASSWORD_PROMPTS` tuples near the top of `bpq_admin.py`.

**Listings seem cut short.** If your BBS user has paging enabled, long
listings may pause mid-output. Disable paging for the account the script
logs in as.

**`python` isn't found.** Use `python3` (macOS/Linux) or `py` (Windows),
and see Getting Python above.

## Technical notes

The script speaks telnet over a raw socket on purpose: Python's stdlib
`telnetlib` was removed in 3.13, and BPQ's telnet server only needs IAC
option requests refused. On entering the BBS it captures the node's exact
prompt line (e.g. `de N0CALL>`) and only stops reading on that string, so
message bodies containing `>` — routine in NTS traffic — can't truncate a
read. The `BpqSession` class in `bpq_admin.py` (login / enter_bbs /
bbs_command / logout) is the extension point if you want to script other
BBS commands.
