[← back to README](../README.md)

# `notify-stale` — scheduled stale-traffic notices

Unattended monitoring between delivery passes: a scheduled run (cron,
systemd timer, or Task Scheduler — every 6 hours, say) that reports stale
traffic so nothing sits unnoticed. It is **read-only on the BBS** — it
only lists (`LTN` and `LPN`), never reads with `R` — so a message keeps
appearing in every notice until you actually deal with it. That
repetition is the point: the notice is a standing reminder, not an event
log.

Each run reports two things:

- **Stale traffic** — the `LTN` messages `--days` or more days old, the
  same cutoff [`export-stale`](stale-traffic.md#export-stale) uses.
- **New private mail** — everything `LPN` lists. Nothing forwards these
  on, so a private message sits on the node until the sysop deals with
  it; it is reported the first time the notifier sees it, whatever its
  age, rather than after `--days`. `SYSTEM Housekeeping Results` reports
  are left out — [`clean-housekeeping`](clean-housekeeping.md) is the
  action for those, and they would otherwise crowd out the real mail.

```bash
python bpq_admin.py notify-stale mynode.example.com --user N0CALL --days 30
```

| Argument | Default | Description |
|---|---|---|
| `--days N` | `3` | Same staleness cutoff as [`export-stale`](stale-traffic.md#export-stale). Traffic only — private mail is always reported. |
| `--heartbeat` | **on** | Send a notice even when there is nothing to report, so a silent notifier can be told from a dead one. |
| `--no-heartbeat` | — | Stay silent when there is nothing to report. |

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

The notice carries both listings under their own headers and totals:

```
1 stale traffic message on mynode.example.com (older than 3 days)

316    22-Aug TF     502 14424  @NTSNY  KC1KVY CANANDAIGUA 585 755

2 new private messages on mynode.example.com (not forwarding)

3309   31-Aug PN      22 W2QS   @W2QS   W2QS   test
3310   01-Sep PN      44 KC1KVY @KC1KVY W2QS   qsl please
```

Where a channel demands it (Discord 2000 chars, Telegram 4096) the
notice is truncated to whole lines with an `...and N more` marker —
taken from the longer listing first, so a flood of stale traffic cannot
squeeze the private mail out of the notice entirely. Email always
carries both listings in full, making it the channel of record. With
nothing to report the run still sends a headers-only heartbeat notice by
default (`0 stale traffic messages ... 0 new private messages ...`);
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
