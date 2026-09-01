[← back to README](../README.md)

# Recovering email addresses (`extract_emails.py`)

Delivering stale traffic means contacting the addressee, and radiograms
spell email addresses out phonetically so they survive voice and CW relay:

```
BOBLANGE01 ATSIGN ICLOUD DOT COM
M DOT E DOT PIATTI AT SIGN GMAIL DOT COM
N2WLH AT YAHOO DOT COM
```

`extract_emails.py` reads an [`export-stale`](stale-traffic.md) folder,
decodes those spellings back into ordinary addresses, and looks up
anything missing on QRZ.com:

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
| `NO CALLSIGN` | No address in the traffic and no callsign in the address block — there is nothing to look up. |

In the `FROM QRZ` column, `-` means QRZ was queried and had no published
address, `no callsign` means the address block had no callsign to look up,
and `not queried` means the run used `--no-qrz`.

## Printing the letters

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

## QRZ credentials and limits

Same pattern as the node password — set them in the environment to keep
them out of shell history and the process list:

| Variable | Replaces |
|---|---|
| `QRZ_USER` | `--qrz-user` |
| `QRZ_PASSWORD` | `--qrz-password` |

Resolution order for the password is `--qrz-password` (least safe), then
`QRZ_PASSWORD`, then an interactive prompt with hidden input (safest). The
env-file recipe in [Configuration](configuration.md#recommended-a-sourced-env-file)
works here too.

Two limits worth knowing before you trust an empty result:

- The QRZ **XML Logbook Data subscription** is required. A non-subscriber
  account logs in fine but does not receive full records, so every lookup
  would come back empty; the script prints a warning to stderr rather than
  letting that read as "nobody has an email on file".
- QRZ returns an address **only when the licensee has chosen to publish
  it**. A `-` means "not published", not "does not exist".

Lookups are cached per callsign within a run (a callsign appearing in three
messages costs one query) and spaced 0.5 s apart.
