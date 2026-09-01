[← back to README](../README.md)

# `notify-stale` — scheduled stale-traffic notices

Unattended monitoring between delivery passes: a scheduled run (cron,
systemd timer, or Task Scheduler — every 6 hours, say) that reports stale
traffic so nothing sits unnoticed. It is **read-only on the BBS** — it
only lists (`LTN`), never reads with `R` — so a stale message keeps
appearing in every notice until you actually deal with it. That
repetition is the point: the notice is a standing reminder, not an event
log.

```bash
python bpq_admin.py notify-stale mynode.example.com --user N0CALL --days 30
```

| Argument | Default | Description |
|---|---|---|
| `--days N` | `3` | Same staleness cutoff as [`export-stale`](stale-traffic.md#export-stale). |
| `--heartbeat` | **on** | Send a notice even when nothing is stale, so a silent notifier can be told from a dead one. |
| `--no-heartbeat` | — | Stay silent when nothing is stale. |

## Channels

Channels are enabled by configuring them — every fully-configured channel
receives the notice, none configured is an error, and a *partially*
configured channel is an error rather than a silent skip:

| Variable | Channel | Meaning |
|---|---|---|
| `BPQ_NOTIFY_DISCORD_WEBHOOK` | Discord | Full webhook URL. |
| `BPQ_NOTIFY_TELEGRAM_TOKEN` | Telegram | Bot token from @BotFather. |
| `BPQ_NOTIFY_TELEGRAM_CHAT` | Telegram | Numeric chat id. |
| `BPQ_SMTP_HOST` | Email | Relay hostname. |
| `BPQ_SMTP_PORT` | Email | Relay port (default `587`). |
| `BPQ_SMTP_USER` | Email | Relay login; empty for an unauthenticated relay. |
| `BPQ_SMTP_PASSWORD` | Email | Relay password (required when `USER` is set). |
| `BPQ_SMTP_FROM` | Email | From address. |
| `BPQ_SMTP_TO` | Email | Recipient(s), comma-separated. |

The notice is the listing lines plus the total, truncated to whole lines
with an `...and N more` marker where the channel demands it (Discord
2000 chars, Telegram 4096); email always carries the full listing, making
it the channel of record. With nothing stale the run still sends a
header-only heartbeat notice by default (`0 stale traffic messages ...`);
pass `--no-heartbeat` to stay quiet instead. A channel that fails to send is a WARNING
in the log and makes the exit code 1 while the other channels still
receive the notice — so cron surfaces the failure. The node link is
closed before any notification is sent, so a slow webhook can never hold
the BBS session open. Authenticated email refuses to run without
STARTTLS; an unauthenticated local relay (postfix on `localhost:25`) is
fine without it.

Step-by-step setup for each channel — creating the Discord webhook, the
@BotFather flow and finding your Telegram chat id, choosing an SMTP
relay — plus cron/systemd/Task Scheduler examples for the 6-hour
schedule, are in [the notifier spec](stale-notifier-spec.md).
