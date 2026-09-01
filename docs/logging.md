[← back to README](../README.md)

# Logging, output, and exit codes

## `bpq_admin.py`

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

## `extract_emails.py`

Each run appends its full report to `extract_emails.log` (default), under a
header recording the time, the source folder, and whether QRZ was queried —
so runs accumulate into a history rather than overwriting one another. The
report is the table from [the extractor page](extract-emails.md), the
summary counts, and then the rows that need a human decision, grouped by
status:

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
