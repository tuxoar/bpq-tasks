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

`bpq_admin.py ACTION`:

| Action | What it does |
|---|---|
| `list` | Run `LPN` and print your private new messages. |
| `clean-housekeeping` | Find every `SYSTEM Housekeeping Results` message in `LPN` and kill each one with `K <id>`. Nothing else is touched, and every kill is verified against the BBS reply. Supports `--dry-run`. |
| `run-reports` | Run `LT` and report the traffic messages in a date range: the matching lines, then the starting message number, ending message number, and total. |
| `export-stale` | Run `LTN`, find traffic messages older than a cutoff, read each with `R <id>`, and save them to a timestamped folder — one file per message plus an index. |

`extract_emails.py` then reads that folder — see
[Recovering email addresses](#recovering-email-addresses-extract_emailspy).

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

   (Or just download the script you need — each is self-contained.)

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
| `--timeout SECONDS` | no | `10` | How long to wait for each expected prompt (login, password, BBS `>`) before giving up. Raise this for slow links. |
| `--log-file PATH` | no | `bpq_admin.log` | Append a timestamped record of each action to this file (see Logging). Pass `--log-file ''` to disable. |
| `--verbose` | no | off | On exit, dump the full session transcript to stderr. The first thing to reach for when something doesn't work. |

\* Every connection value can come from an environment variable instead of
the command line — see the next section. A value given on the command line
wins over the environment.

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

## Recovering email addresses (`extract_emails.py`)

Delivering stale traffic means contacting the addressee, and radiograms
spell email addresses out phonetically so they survive voice and CW relay:

```
BOBLANGE01 ATSIGN ICLOUD DOT COM
M DOT E DOT PIATTI AT SIGN GMAIL DOT COM
N2WLH AT YAHOO DOT COM
```

`extract_emails.py` reads an `export-stale` folder, decodes those spellings
back into ordinary addresses, and looks up anything missing on QRZ.com:

```bash
# Parse the messages only - no network, no credentials needed
python extract_emails.py stale-20260831-083709 --no-qrz

# Same, plus a QRZ lookup for every recipient
QRZ_USER=N0CALL python extract_emails.py stale-20260831-083709
```

```
   MSG  CALL    FROM MESSAGE           FROM QRZ               STATUS
  2872  N2WLH   n2wlh@yahoo.com        n2wlh@yahoo.com        SAME
  2882  KE2IRV  NONE                   ke2irv@example.net     ADDED
  2915  N2MEP   m.e.piatti@gmail.com   -                      MSG ONLY
  3072  N2GPX   NONE                   -                      NONE
```

| Argument | Default | Description |
|---|---|---|
| `DIR` | `.` | Directory of `msg_*.txt` exports (positional). |
| `--qrz-user USER` | — | QRZ.com username. Required unless `--no-qrz`. |
| `--qrz-password PASSWORD` | see below | QRZ.com password. Prefer the env var or the prompt. |
| `--no-qrz` | off | Parse the message text only; make no network calls. |
| `--emails-file PATH` | `emails.txt` in `DIR` | Where to write the ready-to-send emails (below). `--emails-file ''` disables. |
| `--letters-dir PATH` | `letters/` in `DIR` | Where to write printable letters for messages with no address (below). `--letters-dir ''` disables. |
| `--log-file PATH` | `extract_emails.log` | Append the report to this file. `--log-file ''` disables. |
| `-q`, `--quiet` | off | Write only to the log file, not to stdout. |

**Ready-to-send emails.** Besides the report, every message with an
address gets a copy-paste email block, all collected into one file
(`emails.txt` in the export folder by default). Each block holds the To
line, a subject, a fixed delivery notice, and the radiogram itself with
the BBS headers, routing traces, and export footer stripped:

```
########## msg 2872 ##########

To: n2wlh@yahoo.com
Subject: Digital NTS Traffic for N2WLH

Body: 
The message(s) below was received for you via the Digital National Traffic System. For more on the National Traffic system visit https://nts2.arrl.org/ or https://radiorelay.org/

73, Shaun W2QS Region 2 Hub Sysop

====
NR 7439 R AA5AF 21 SEGUIN TX JUL 2ND
STEVEN H JACKSON N2WLH
...
NNNN
```

When the traffic and QRZ disagree (`DIFFERS`), the To line carries both
addresses. The file is rewritten on every run, and the export folder is
gitignored, so the generated emails stay out of the public repo.

**Printable letters for everyone else.** Messages with no address at all
(no email in the traffic, none on QRZ) each get their own file —
`letters/letter_<id>.txt` in the export folder — formatted like the
emails but with no To/Subject header, ready to print and mail (see
[Printing the letters](#printing-the-letters)). The
radiogram's address block carries the recipient's street address, so the
printout itself tells you how to address the envelope. Every message in
the export therefore ends up in exactly one place: `emails.txt` if an
address was found, `letters/` if not.

**Who the address belongs to.** The addressee is the first line of the
address block, which follows the preamble:

```
NR 751221 R HXCF 11 W2PAX ARL 15 NAPLES FL JULY 7   <- preamble
MICHAEL PIATTI  N2MEP                               <- addressee
```

so the trailing callsign on that line (`N2MEP`) is the recipient. The
callsign in the preamble is the *originating* station (`W2PAX` here) and is
never used for lookups.

**Every recipient is looked up, including those whose message already
carried an address.** That is deliberate: it surfaces the case where QRZ
has a different address from the one sent in the traffic, rather than
hiding it. Each row gets a status:

| Status | Meaning |
|---|---|
| `SAME` | The message and QRZ agree. |
| `DIFFERS` | Both have an address and they disagree — decide which to use. |
| `ADDED` | No address in the traffic; recovered from QRZ. |
| `MSG ONLY` | Address in the traffic; QRZ has none published. |
| `NONE` | No address in the traffic, and none found for the callsign. |

In the `FROM QRZ` column, `-` means QRZ was queried and had no published
address, `no callsign` means the address block had no callsign to look up,
and `not queried` means the run used `--no-qrz`.

### Printing the letters

Each letter is a plain text file that fits on a single page, so anything
that prints a text file works. From the command line:

**Linux / macOS** — both print through CUPS, which formats plain text on
its own. `lp` sends a file to the default printer:

```bash
cd stale-20260831-081810        # your export folder
for f in letters/letter_*.txt; do lp "$f"; done
```

The loop gives each letter its own print job, so re-printing a single one
is just `lp letters/letter_2882.txt`. If the wrong printer (or no
printer) is the default, list your queues with `lpstat -p`, send to a
specific one with `lp -d QUEUE-NAME file`, and make that choice stick
with `lpoptions -d QUEUE-NAME`. Watch the queue with `lpstat -o` — an
empty listing means everything has printed.

**Windows (PowerShell)** — `Out-Printer` sends text to the default
printer:

```powershell
Get-ChildItem letters\letter_*.txt | ForEach-Object { Get-Content $_ | Out-Printer }
```

Add `-Name "Printer Name"` to `Out-Printer` to target a specific printer;
`Get-Printer` lists what's installed.

The printout carries the recipient's street address from the radiogram's
address block, so addressing the envelope is a matter of copying it off
the page.

### QRZ credentials and limits

Same pattern as the node password — set them in the environment to keep
them out of shell history and the process list:

| Variable | Replaces |
|---|---|
| `QRZ_USER` | `--qrz-user` |
| `QRZ_PASSWORD` | `--qrz-password` |

Resolution order for the password is `--qrz-password` (least safe), then
`QRZ_PASSWORD`, then an interactive prompt with hidden input (safest). The
env-file recipe in [Environment variables](#environment-variables) works
here too.

Two limits worth knowing before you trust an empty result:

- The QRZ **XML Logbook Data subscription** is required. A non-subscriber
  account logs in fine but does not receive full records, so every lookup
  would come back empty; the script prints a warning to stderr rather than
  letting that read as "nobody has an email on file".
- QRZ returns an address **only when the licensee has chosen to publish
  it**. A `-` means "not published", not "does not exist".

Lookups are cached per callsign within a run (a callsign appearing in three
messages costs one query) and spaced 0.5 s apart.

## Logging

### `bpq_admin.py`

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

### `extract_emails.py`

Each run appends its full report to `extract_emails.log` (default), under a
header recording the time, the source folder, and whether QRZ was queried —
so runs accumulate into a history rather than overwriting one another. The
report is the table above, the summary counts, and then the rows that need
a human decision, grouped by status:

```
=== extract_emails 2026-08-31 08:50:42 ===
source: /home/n0call/bpq-tasks/stale-20260831-083709
QRZ:    queried

   MSG  CALL    FROM MESSAGE           FROM QRZ               STATUS
  ...

20 of 23 messages have an address  ADDED=6  DIFFERS=1  MSG ONLY=5  NONE=3  SAME=8

DIFFERS (1) - QRZ address differs from the one in the traffic - confirm which to use
    msg 2955  N2XDD  traffic=n2dxx@arrl.org  qrz=n2xdd@arrl.org
ADDED (6) - address recovered from QRZ - not present in the traffic
    msg 2882  KE2IRV  ke2irv@example.net
```

Use `-q` to log without printing, for scheduled runs. The log holds real
names and addresses; see the note below.

Logs and exported messages contain real callsigns, hostnames, and message
content — the repo's `.gitignore` keeps them out of version control.
Leave it that way if you fork this publicly.

## Output and exit codes

- Action results (listings, `killed <id>` lines, summaries) go to
  **stdout**; status and errors go to **stderr**, so stdout pipes and
  redirects cleanly. `extract_emails.py` follows the same split: the report
  on stdout, per-callsign QRZ warnings on stderr.
- Exit code `0` on success, `1` on any failure (connection refused, login
  rejected, expected prompt never seen, an unconfirmed kill, or a rejected
  QRZ login), `2` for invalid arguments. Failure messages include the text
  the node or QRZ actually sent.
- A QRZ lookup that fails for one callsign warns and leaves that row's
  `FROM QRZ` empty rather than aborting the run, so one bad record cannot
  cost you the whole report.

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

**Every QRZ lookup comes back empty.** Almost always the subscription: the
XML Logbook Data service returns full records only to subscribers. The
script warns on stderr when QRZ reports the account as a non-subscriber.
Check also that the callsigns in the `CALL` column are the ones you expect
— a message whose address block omits the callsign shows `no callsign` and
is never looked up.

**A recovered address looks wrong.** Compare it against the message text
with `--no-qrz`. Addresses are transcribed by hand through several relays,
so the traffic itself can carry a typo — a `DIFFERS` row is exactly that
case, and QRZ is usually, though not always, the better source.

## Technical notes

The script speaks telnet over a raw socket on purpose: Python's stdlib
`telnetlib` was removed in 3.13, and BPQ's telnet server only needs IAC
option requests refused. On entering the BBS it captures the node's exact
prompt line (e.g. `de N0CALL>`) and only stops reading on that string, so
message bodies containing `>` — routine in NTS traffic — can't truncate a
read. The `BpqSession` class in `bpq_admin.py` (login / enter_bbs /
bbs_command / logout) is the extension point if you want to script other
BBS commands.
