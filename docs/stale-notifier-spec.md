# Spec: Automated stale-message notifier (`notify-stale`)

Status: **implemented** — the `notify-stale` action in `bpq_admin.py`
follows this design. Sections 5 (channel setup guides) and 6 (scheduling)
remain the operator's reference for wiring it up.

## 1. Overview

An unattended job runs every 6 hours, connects to the BPQ node, finds
traffic messages older than a cutoff, and pushes a short notice to one or
more channels: Discord, Telegram, and/or email (via an SMTP relay). The
notice contains only the list of stale messages and the total count.

Goals:

- **Read-only on the BBS.** The job only lists messages (`LTN`); it never
  reads them with `R`, so nothing is marked read and nothing changes on the
  node. A stale message keeps appearing in every 6-hour notice until the
  sysop deals with it (with `export-stale`, or by killing it) — that
  repetition is intentional: the notice is a standing reminder, not an
  event log.
- **Zero new dependencies.** All three channels are reachable with the
  Python standard library (`urllib.request` for Discord/Telegram webhooks,
  `smtplib` for email), preserving the tool's copy-one-file portability.
- **Cron-friendly.** Quiet when there is nothing to say, loud in the exit
  code when something fails.

## 2. Architecture

A new `notify-stale` action in `bpq_admin.py`, alongside the existing
actions. No new files, no daemon — the scheduler (cron / systemd timer /
Task Scheduler) provides the every-6-hours part.

```
scheduler (every 6h)
  └─ bpq_admin.py notify-stale
       ├─ BpqSession: connect → login → enter BBS        (existing code)
       ├─ find_stale(session, days): LTN → parse → filter (refactored out
       │     of do_export_stale; same TRAFFIC_LINE_RE + most_recent logic)
       ├─ logout                                          (existing code)
       └─ for each configured channel: send notice
             ├─ Discord webhook  (urllib.request)
             ├─ Telegram bot API (urllib.request)
             └─ SMTP relay       (smtplib)
```

Refactor required: the stale-scan block currently inside `do_export_stale`
(LTN → `TRAFFIC_LINE_RE` match → `most_recent` date resolution → cutoff
comparison) moves into a shared helper `find_stale(session, days)` returning
`[(msg_id, listing_line), ...]`; both `export-stale` and `notify-stale`
call it. The BBS session is closed **before** any network calls to
notification services, so a slow webhook can't hold the node link open.

### CLI

```
python bpq_admin.py notify-stale [HOST] [--days N] [--no-heartbeat] [usual common args]
```

| Argument | Default | Description |
|---|---|---|
| `--days N` | `3` | Same staleness cutoff as `export-stale`. |
| `--heartbeat` | **on** | Send a notice even when nothing is stale ("0 stale traffic messages…"), so a silent notifier can be distinguished from a dead one. Disable with `--no-heartbeat`. |

Exit codes: `0` all good (including "nothing stale, nothing sent");
`1` BPQ unreachable/login failed, **or any configured channel failed to
send**; `2` bad arguments / no channel configured.

## 3. Configuration

All notification settings are environment variables, extending the
existing `bpq.env` pattern (no secrets on the command line; the repo's
`.gitignore` already excludes `*.env`, `*.env.ps1`, `*.env.bat`).

A channel is **enabled by being fully configured** — there is no
`--notify` flag. Every fully-set channel receives the notice. If no
channel is fully set, `notify-stale` exits 2 with a message naming the
variables it looked for. A partially-set channel (e.g. Telegram token
without chat id) is also a startup error, not a silent skip.

| Variable | Channel | Meaning |
|---|---|---|
| `BPQ_NOTIFY_DISCORD_WEBHOOK` | Discord | Full webhook URL. |
| `BPQ_NOTIFY_TELEGRAM_TOKEN` | Telegram | Bot token from @BotFather. |
| `BPQ_NOTIFY_TELEGRAM_CHAT` | Telegram | Numeric chat id (user, group, or channel). |
| `BPQ_SMTP_HOST` | Email | Relay hostname. |
| `BPQ_SMTP_PORT` | Email | Relay port; default `587`. |
| `BPQ_SMTP_USER` | Email | Relay login. Empty/unset = unauthenticated relay. |
| `BPQ_SMTP_PASSWORD` | Email | Relay password. |
| `BPQ_SMTP_FROM` | Email | From address. |
| `BPQ_SMTP_TO` | Email | Recipient; comma-separate for several. |

(Existing `BPQ_HOST`, `BPQ_PORT`, `BPQ_USER`, `BPQ_PASSWORD` supply the
node connection as they do for every action.)

## 4. Notice format

Identical content on every channel — a header, the raw listing lines,
nothing else:

```
14 stale traffic messages on mynode.example.com (older than 30 days)

316    24-Oct TF     502 14424  @NTSNY  KC1KVY CANANDAIGUA 585 755
314    23-Oct TF     503 19119  @NTSPA  WO2H   PHILADELPHIA 231 866
...
```

Rendering notes per channel:

- **Discord**: wrap the listing in a code fence so columns align; hard
  limit 2000 characters per message. When over, keep the header + as many
  whole lines as fit and end with `…and N more`.
- **Telegram**: send as plain text (no parse_mode — listing lines contain
  characters that Markdown parsing would mangle); hard limit 4096
  characters, same truncation rule.
- **Email**: subject `[BPQ] 14 stale traffic messages on mynode`; the
  full untruncated listing goes in the plain-text body (email has no
  practical limit, so email is the channel of record).

With the default heartbeat on and nothing stale, the notice is the header only:
`0 stale traffic messages on mynode.example.com (older than 30 days)`.

## 5. Integration setup guides

### 5.1 Discord (webhook — no bot account needed)

1. In your Discord server, pick or create the channel for notices
   (e.g. `#bpq-node`).
2. Channel settings (gear icon) → **Integrations** → **Webhooks** →
   **New Webhook**. Name it (e.g. `BPQ Notifier`), confirm the channel,
   **Copy Webhook URL**.
3. Put it in `bpq.env`:
   ```bash
   export BPQ_NOTIFY_DISCORD_WEBHOOK='https://discord.com/api/webhooks/1234567890/AbCdEf...'
   ```
4. Test it before wiring anything else:
   ```bash
   curl -H 'Content-Type: application/json' \
        -d '{"content": "BPQ notifier test"}' \
        "$BPQ_NOTIFY_DISCORD_WEBHOOK"
   ```
   The message should appear in the channel within a second.

Notes: the URL **is** the credential — anyone holding it can post to the
channel (but read nothing), so treat it like a password. Rate limits are
irrelevant at one message per 6 hours. Message cap 2000 chars (see §4).
Implementation detail: send with header `Content-Type: application/json`
and a JSON body `{"content": "..."}`; Discord returns HTTP 204 on success.

### 5.2 Telegram (bot API)

1. In Telegram, open **@BotFather**, send `/newbot`, follow the prompts
   (a display name, then a username ending in `bot`). BotFather replies
   with the **bot token** — the credential.
2. Get the **chat id** of wherever notices should land:
   - *Direct to you*: send any message to your new bot first (bots cannot
     message you until you do), then fetch
     `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and
     read `"chat":{"id": 123456789, ...}` from the JSON.
   - *A group*: add the bot to the group, send a message in the group,
     then `getUpdates` again — group ids are negative numbers (keep the
     minus sign).
3. Put both in `bpq.env`:
   ```bash
   export BPQ_NOTIFY_TELEGRAM_TOKEN='123456789:AAF...your-token...'
   export BPQ_NOTIFY_TELEGRAM_CHAT='123456789'
   ```
4. Test:
   ```bash
   curl -d "chat_id=$BPQ_NOTIFY_TELEGRAM_CHAT" -d "text=BPQ notifier test" \
        "https://api.telegram.org/bot$BPQ_NOTIFY_TELEGRAM_TOKEN/sendMessage"
   ```

Notes: message cap 4096 chars (see §4). The implementation POSTs
`chat_id` and `text` (no `parse_mode`) and treats HTTP 200 with
`"ok":true` as success. If `getUpdates` returns an empty result, send the
bot another message and retry — updates are only retained briefly.

### 5.3 Email (SMTP relay)

Pick a relay:

- **Your ISP or hosting provider's relay** — often unauthenticated from
  your own network; check their SMTP host/port.
- **Gmail** — host `smtp.gmail.com`, port `587`. Requires an **app
  password** (Google Account → Security → 2-Step Verification → App
  passwords); your normal password will not work.
- **Self-hosted** (postfix on the node machine) — host `localhost`,
  port `25`, usually no auth; simplest if the node already runs Linux,
  but deliverability to external addresses depends on your IP reputation.

Configure:

```bash
export BPQ_SMTP_HOST='smtp.gmail.com'
export BPQ_SMTP_PORT='587'
export BPQ_SMTP_USER='you@gmail.com'
export BPQ_SMTP_PASSWORD='abcd efgh ijkl mnop'   # app password
export BPQ_SMTP_FROM='you@gmail.com'
export BPQ_SMTP_TO='sysop@example.com'
```

Implementation detail: `smtplib.SMTP(host, port)` → `starttls()` →
`login()` when `BPQ_SMTP_USER` is set → `send_message()` with an
`email.message.EmailMessage`. Port 465 (implicit TLS / `SMTP_SSL`) is out
of scope for v1; use a 587 STARTTLS relay.

Caveats: the first automated mail often lands in spam — mark it "not
spam" once. Some relays rewrite the From address to the authenticated
user; set `BPQ_SMTP_FROM` to match `BPQ_SMTP_USER` unless you know your
relay allows otherwise.

## 6. Scheduling every 6 hours

### cron (Linux, simplest)

```cron
# crontab -e
0 */6 * * * . /home/sysop/bpq-tasks/bpq.env && /usr/bin/python3 /home/sysop/bpq-tasks/bpq_admin.py notify-stale --days 30 --log-file /home/sysop/bpq-tasks/bpq_admin.log >/dev/null 2>&1
```

Cron provides no environment, hence the explicit `. bpq.env` and absolute
paths. Drop the `>/dev/null 2>&1` while testing so cron mails you the
output on failure — or keep stderr (`>/dev/null` only) permanently, since
the tool puts errors on stderr and results on stdout.

### systemd timer (Linux, better logging)

`/etc/systemd/system/bpq-notify.service`:
```ini
[Unit]
Description=BPQ stale-message notifier

[Service]
Type=oneshot
User=sysop
EnvironmentFile=/home/sysop/bpq-tasks/bpq.env
ExecStart=/usr/bin/python3 /home/sysop/bpq-tasks/bpq_admin.py notify-stale --days 30
```

`/etc/systemd/system/bpq-notify.timer`:
```ini
[Unit]
Description=Run BPQ stale-message notifier every 6 hours

[Timer]
OnCalendar=00/6:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now bpq-notify.timer
journalctl -u bpq-notify.service     # full run history
```

Note: `EnvironmentFile` wants plain `KEY=value` lines — either keep a
second file without the `export ` prefixes, or write `bpq.env` without
`export` from the start (POSIX `. bpq.env` still works for cron if the
cron line uses `set -a; . bpq.env; set +a`).

`Persistent=true` runs a missed timer at boot — useful when the machine
isn't always on.

### Windows Task Scheduler

```powershell
schtasks /Create /TN "BPQ stale notifier" /SC HOURLY /MO 6 `
  /TR "powershell -NoProfile -Command \". C:\bpq-tasks\bpq.env.ps1; py C:\bpq-tasks\bpq_admin.py notify-stale --days 30\""
```

Or create it in the Task Scheduler GUI: trigger "Daily", repeat every
6 hours; action runs the PowerShell command above. Run the task once
manually ("Run" in the GUI) to verify before trusting the schedule.

## 7. Failure handling and edge cases

| Situation | Behavior |
|---|---|
| Node unreachable / login rejected | ERROR in audit log, message on stderr, exit 1. Nothing sent (a channel notice about tool failure is a v2 idea — for v1, cron mail / journalctl is the failure channel). |
| Nothing stale with `--no-heartbeat` | Log "0 stale", send nothing, exit 0. |
| One channel fails, others succeed | WARNING in log for the failed channel (with HTTP status / SMTP error), other channels still receive the notice, exit 1. |
| No channel configured | Exit 2 before touching the node, naming the env vars checked. |
| Notice exceeds channel limit | Truncate whole lines + `…and N more` (Discord/Telegram); email always full. |
| Year-less listing dates | Same caveat as `export-stale`: a message >1 year old looks recent. The 6-hour cadence makes this moot in practice — messages get noticed long before wraparound. |
| Duplicate notices every 6h for the same messages | By design (§1). If it ever becomes noise, a v2 `--only-changes` could hash the id list and stay quiet when unchanged since the last run (state file next to the log). Not in v1. |

All sends are recorded in the existing audit log (`running notify:discord`,
`notice sent to discord (14 messages)`, etc.), passwords/tokens never
logged — consistent with current logging rules.

## 8. Security notes

- The Discord webhook URL, Telegram bot token, and SMTP password are all
  **write-capable credentials**. Keep them in `bpq.env` with `chmod 600`,
  never on the command line. The repo `.gitignore` already excludes
  `*.env`, `*.env.ps1`, `*.env.bat`.
- Notices contain callsigns and city/phone fragments from the LTN listing
  — send them only to channels the sysop controls (a private Discord
  channel / Telegram chat, not a public one).
- Telegram `getUpdates` responses and Discord webhook URLs pasted into
  issues/chats are the common leak paths; rotate via BotFather
  (`/revoke`) or by deleting/recreating the webhook if exposed.

## 9. Implementation checklist

1. Refactor the stale scan out of `do_export_stale` into
   `find_stale(session, days)`; `export-stale` behavior unchanged
   (regression-test against the mock).
2. Add notifier functions: `send_discord(webhook, text)`,
   `send_telegram(token, chat, text)`, `send_email(cfg, subject, body)` —
   stdlib only, each returning success/failure, WARNING-logged on failure.
3. Add `channels_from_env()` → list of configured channels; error on none
   or on partial configuration.
4. Add `do_notify_stale` + `notify-stale` subparser (`--days`,
   `--heartbeat`); wire into the `actions` dict.
5. Truncation helper honoring the 2000/4096 caps with `…and N more`.
6. Tests against the mock BPQ server plus a local `http.server` stub for
   Discord/Telegram and `smtpd`-style stub (or `aiosmtpd`-free minimal
   socket accept) for SMTP; verify exit codes for the failure matrix in §7.
7. README: new action row, env var table additions, scheduling section
   pointer to this spec.
