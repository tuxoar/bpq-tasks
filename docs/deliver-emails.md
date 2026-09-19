[← back to README](../README.md)

# Delivering the emails (`deliver_emails.py`)

[`extract_emails.py`](extract-emails.md) leaves you with `emails.txt`: one
ready-to-send block per radiogram that has an address. `deliver_emails.py`
reads that file and puts every block into your mailbox for you — as
**drafts** by default, so you can look each one over in the mail client
and press send there, or **sent outright** with `--send`:

```bash
python deliver_emails.py stale-20260919-082944 --dry-run   # what would happen
python deliver_emails.py stale-20260919-082944             # create drafts
python deliver_emails.py stale-20260919-082944 --send      # send them
```

It talks ordinary IMAP (for drafts) and SMTP (for sending), which is what
**Proton Mail Bridge** exposes on your own machine for a paid Proton
account. Bridge is the only supported way for a program to reach a Proton
mailbox — Proton has no public mail API — and with Bridge running the
script needs just two settings: your Proton address and the password
Bridge generates. The same code also works with any other IMAP/SMTP
mailbox; see [Other servers](#other-servers).

## Setting up Proton Mail Bridge

Bridge requires a paid Proton plan (Mail Plus, Proton Unlimited, ...).
It runs in the background, logs in to Proton once, and serves IMAP on
`127.0.0.1:1143` and SMTP on `127.0.0.1:1025` with STARTTLS and a
self-signed certificate. The username is your Proton address; the password
is a **Bridge-generated password** shown in Bridge's settings — never your
Proton account password.

**Arch Linux** — the headless build is in the official repos:

```bash
sudo pacman -S protonmail-bridge-core     # plus pass or gnome-keyring, below
protonmail-bridge --cli                   # interactive console
>>> login                                 # Proton address, password, 2FA
>>> info                                  # shows IMAP/SMTP ports, security, and the Bridge password
>>> exit
protonmail-bridge --noninteractive &      # keep it running while you deliver
```

Bridge stores its credentials in a secret store; the package's optional
dependencies are the choices: `pass` (initialise it with a GPG key first:
`pass init <gpg-id>`) or a Secret Service such as `gnome-keyring`. Without
one, `login` fails complaining about the keychain. On a desktop that
already runs GNOME Keyring or KWallet nothing extra is needed.

**Other Linux / macOS / Windows** — install the Bridge desktop app from
[proton.me/mail/bridge](https://proton.me/mail/bridge), sign in, then open
*Settings → Mailbox configuration* (or the account's *Mailbox details*) to
read the same values: hostname, IMAP and SMTP ports, security mode, and the
Bridge password. Bridge must be running whenever the script runs.

Then put the two required values in your env file — the repo's
[`bpq.env.sample`](../bpq.env.sample) has the section ready — and check the
connection:

```bash
export BPQ_DELIVER_USER=you@proton.me
export BPQ_DELIVER_PASSWORD='the-bridge-generated-password'
python deliver_emails.py --test
```

```
imap 127.0.0.1:1143 (starttls, verify off (loopback)): login OK
drafts folder: Drafts
smtp 127.0.0.1:1025: login OK
```

`--test` logs in to both servers and finds the Drafts folder without
touching a message. If Bridge shows different ports (it picks others when
1143/1025 are taken) or you switched it to SSL, set the matching variables
from the table below.

## Arguments

| Argument | Default | Description |
|---|---|---|
| `DIR` | `.` | Export folder (positional); reads `emails.txt` in it. |
| `--emails-file PATH` | `DIR/emails.txt` | Read a different file. The ledger then lives next to that file. |
| `--send` | off | Send each message that has exactly one To address. Messages with more become drafts instead — see [Sending](#sending-with---send). |
| `--dry-run` | off | Parse the file, consult the ledger, and print what would happen. No connection, no credentials, nothing written. |
| `--force` | off | Redo messages the ledger says were already drafted or sent. |
| `--only ID[,ID...]` | all | Deliver only these message ids; repeat the flag or separate ids with commas. |
| `--test` | off | Log in to IMAP and SMTP, report the Drafts folder, exit. |
| `--ledger PATH` | `delivered.txt` next to the emails file | Where delivered messages are recorded — see [The ledger](#the-ledger). |
| `--log-file PATH` | `deliver_emails.log` | Append the report to this file. `--log-file ''` disables. |
| `-q`, `--quiet` | off | Write only to the log file, not to stdout. |
| `--user`, `--password`, `--from`, `--imap-host`, `--imap-port`, `--smtp-host`, `--smtp-port`, `--security`, `--ca-cert`, `--drafts-folder` | environment | Command-line overrides for the variables below. Prefer the environment for the password. |

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `BPQ_DELIVER_USER` | — (required) | Login. For Bridge: your Proton address. |
| `BPQ_DELIVER_PASSWORD` | prompt | The Bridge-generated password. Prompted for with hidden input when unset and a terminal is available. |
| `BPQ_DELIVER_FROM` | `BPQ_DELIVER_USER` | The From header. Must be an address on the account; `Shaun W2QS <you@proton.me>` works. |
| `BPQ_DELIVER_IMAP_HOST` | `127.0.0.1` | IMAP host. |
| `BPQ_DELIVER_IMAP_PORT` | `1143` | IMAP port. |
| `BPQ_DELIVER_SMTP_HOST` | `127.0.0.1` | SMTP host. |
| `BPQ_DELIVER_SMTP_PORT` | `1025` | SMTP port. |
| `BPQ_DELIVER_SECURITY` | `starttls` | `starttls` (Bridge's default), `ssl` (implicit TLS — Bridge's SSL mode, Gmail's 993/465), or `none` (no TLS; accepted for loopback hosts only). |
| `BPQ_DELIVER_CA_CERT` | — | A PEM file to verify the server certificate against. |
| `BPQ_DELIVER_DRAFTS` | discovered | Drafts folder name. Normally found from the server's folder list (`\Drafts`), falling back to `Drafts`. |

A value on the command line wins over the environment; the password
resolution order is `--password` (least safe), then `BPQ_DELIVER_PASSWORD`,
then the interactive prompt (safest). The sourced-env-file recipe in
[Configuration](configuration.md#recommended-a-sourced-env-file) applies.

## What a run looks like

```
=== deliver_emails 2026-09-19 09:15:02 ===
source:  /home/n0call/bpq-tasks/stale-20260919-082944/emails.txt
mode:    send
server:  imap 127.0.0.1:1143  smtp 127.0.0.1:1025  starttls, verify off (loopback)
account: you@proton.me

   MSG  TO                                   ACTION  STATUS
  3429  kd2spj@example.net                   send    SENT
  3443  geneschoeb@example.com               send    SENT
  3456  ka2sjg@example.com, ka2sjg@example.org  draft   DRAFTED (2 addresses - not sent)
  3466  collovanj@example.com                -       SKIPPED (sent 2026-09-12)
  3467  greg@example.com                     send    FAILED: greg@example.com: 550 5.1.1 no such user

3 of 5 messages delivered  DRAFTED=1  FAILED=1  SENT=2  SKIPPED=1

FAILED (1) - fix and re-run; delivered messages are skipped automatically
    msg 3467  greg@example.com  greg@example.com: 550 5.1.1 no such user

DRAFTED instead of sent (1) - the To line carries more than one address; pick one in the mail client, or edit emails.txt and re-run with --force
    msg 3456  ka2sjg@example.com, ka2sjg@example.org
```

Both connections are opened and logged in **before** the first message is
touched, so a wrong password fails the run cleanly with nothing half-done.
After that, one message failing never stops the rest; the failures are
listed at the end and the exit code is 1.

**Edit `emails.txt` first, not after.** The file on disk is what gets
delivered, so this is where you settle a `DIFFERS` row by deleting the
address you don't want from its To line (a leftover comma is fine), or fix
anything else. Any block that does not parse — a broken To line, a missing
`Body:` — aborts the whole run before anything is connected to, and the
message names the block; so does a file that is no longer UTF-8 (an editor
that saved it as ANSI). Keep in mind that re-running `extract_emails.py`
rewrites `emails.txt` and discards such edits.

## The ledger

Every message successfully drafted or sent is appended to `delivered.txt`
next to the `emails.txt` being delivered (so, in the export folder) —
timestamp, message id, `drafted` or `sent`, and the To line:

```
2026-09-19T09:15:03-04:00	3429	sent	kd2spj@example.net
2026-09-19T09:15:04-04:00	3456	drafted	ka2sjg@example.com, ka2sjg@example.org
```

On the next run those messages show as `SKIPPED` and nothing is created
twice, so re-running after a failure is the normal way to finish a
delivery pass. `--force` ignores the ledger and does them again (each
attempt is a new message with its own Message-ID). A message that was
*drafted* is skipped by a later `--send` too — the draft already exists in
your mailbox; send it from there, or `--force`. The ledger is checked to
be writable before anything is delivered; should a write still fail
mid-run, the message is reported as delivered but `NOT RECORDED` and the
run exits 1, so you can add the line by hand before running again.
`delivered.txt` is gitignored wherever it ends up, since it holds real
addresses.

## Sending with `--send`

`--send` sends every block whose To line carries **exactly one** address.
A block with two or more addresses — the traffic and QRZ disagreed, and
`extract_emails.py` put both on the To line — is **drafted instead**, never
sent blind, and the report lists it under `DRAFTED instead of sent`. Pick
the address in the draft and send it from the mail client, or edit
`emails.txt` and run again with `--force --only <id>`.

Bridge files a copy of each sent message in your Sent folder itself, so
the script never writes to Sent. Proton applies a daily sending limit
(a few hundred messages on paid plans); a very large export could hit it,
which shows up as per-message `FAILED` rows with the server's reply —
re-run later and the delivered ones are skipped.

## Certificates and security modes

Bridge's certificate is self-signed, so with the defaults — a loopback
host and no `BPQ_DELIVER_CA_CERT` — the script accepts it **without
verification**. That is sound: the connection never leaves your machine,
and Bridge's own TLS to Proton is verified by Bridge. The report says
`verify off (loopback)` so it is never a surprise. For any host that is
not loopback the certificate is always verified, against the system store
or against `BPQ_DELIVER_CA_CERT`; and `BPQ_DELIVER_SECURITY=none` is refused
outright for a non-loopback host, so credentials cannot go over the
network in the clear.

If you would rather verify Bridge too, export its certificate from
Bridge's settings (*Advanced settings → Export TLS certificates*) and point
`BPQ_DELIVER_CA_CERT` at the `cert.pem`. Should hostname checking then
fail against `127.0.0.1`, drop the variable again — loopback is trusted
either way.

### Other servers

Anything with IMAP and SMTP works; only the account values change.

```bash
# hydroxide (unofficial Proton bridge; no TLS, loopback only)
export BPQ_DELIVER_SECURITY=none

# Gmail with an app password
export BPQ_DELIVER_IMAP_HOST=imap.gmail.com  BPQ_DELIVER_IMAP_PORT=993
export BPQ_DELIVER_SMTP_HOST=smtp.gmail.com  BPQ_DELIVER_SMTP_PORT=465
export BPQ_DELIVER_SECURITY=ssl
export BPQ_DELIVER_USER=you@gmail.com BPQ_DELIVER_PASSWORD='abcd efgh ijkl mnop'
```

The Drafts folder is found from the server's folder list (the one flagged
`\Drafts` — Gmail calls it `[Gmail]/Drafts`), falling back to a folder
named `Drafts`; set `BPQ_DELIVER_DRAFTS` if neither fits. Folder names
with non-ASCII characters are not supported.

## First run against a real account

Before trusting a whole export to it, send one message to an address you
own. `send_test_email.sh` does the whole thing: it writes a one-block
`emails.txt` in a temp folder, runs `--test`, then delivers the block —
as a draft, or for real with `--send`:

```bash
source bpq.env
./send_test_email.sh you@otheraddress.com          # lands in Drafts
./send_test_email.sh you@otheraddress.com --send   # actually sent
```

Check that the draft shows the From address you expect (especially with
`BPQ_DELIVER_FROM` set to a secondary address), that the sent copy arrives
and appears exactly once in Sent, and — with a deliberately wrong password
— that the run stops with the server's error before anything is written.

## Troubleshooting

**`connection refused` on 127.0.0.1:1143 or :1025.** Bridge is not
running, or is listening on other ports — `info` in the Bridge console or
the Mailbox configuration page shows the real ones.

**`535` / `AUTHENTICATIONFAILED` with the right Proton password.** It
wants the *Bridge* password, the generated one shown in Bridge, not your
Proton account password.

**`certificate verify failed`.** You are talking to a non-loopback host
(or set `BPQ_DELIVER_CA_CERT`) and the certificate does not check out.
For Bridge on your own machine, drop `BPQ_DELIVER_CA_CERT`; for Bridge on
another machine, export its certificate and point the variable at it.

**`does not offer STARTTLS` / TLS handshake errors.** Bridge is set to
the other mode — match it with `BPQ_DELIVER_SECURITY=ssl` (or back to
`starttls`), together with the ports Bridge shows for that mode.

**The From address is rejected.** `BPQ_DELIVER_FROM` must be an address
on the Proton account (an alias is fine); leave it unset to use the login
address.
