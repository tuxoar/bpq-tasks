[← back to README](../README.md)

# BBS activity alert (`check_bbs_activity.py`)

Watches the node's live BBS log and sends a **Telegram** message when no
one has connected to the BBS within a threshold window (default **90
minutes**). Built for a scheduled run.

```bash
source bpq.env
python check_bbs_activity.py              # ssh to the node, check, alert
python check_bbs_activity.py --dry-run    # print instead of sending
```

## How it works

- Fetches `~/linbpq/logLatest_BBS.txt` from the node over SSH (key
  auth, same as `backup_node.sh`), or reads it straight off disk with
  `--local` when the script runs on the node itself.
- Scans for `Incoming Connect from` entries and takes the newest one.
  `logLatest` points at a per-day file, so just after midnight — when
  the current log covers less than the window — the previous day's log
  is checked too.
- Log timestamps carry no timezone and can be UTC or node-local time
  depending on the BPQ build; the script works out which by comparing
  the newest entry against the file's modification time, so ages are
  computed on the right clock either way.
- If the newest connect is older than the threshold (or there are no
  connects at all), it sends one Telegram message:

  > BBS alert: no one has connected to the BBS on 100.69.92.43 for 132
  > minutes (threshold 90). Last connect: W2QS at 2026-09-11 00:56 UTC.

- A state file (`~/.local/state/bpq-bbs-activity`) remembers the gap it
  alerted on, so a 15-minute cron cadence produces **one** alert per
  outage, not one every 15 minutes. The next connect clears the state,
  re-arming the alert for the next gap.

## Configuration

From the environment (see [Configuration](configuration.md) and
`bpq.env.sample`):

| Variable | Meaning |
|---|---|
| `BPQ_NOTIFY_TELEGRAM_TOKEN` | Bot token from @BotFather — same variable `notify-stale` uses. |
| `BPQ_NOTIFY_TELEGRAM_CHAT` | Chat id to alert. |
| `BPQ_BACKUP_HOST` / `BPQ_HOST` | Node to ssh to when no `HOST` argument is given. |

Options:

| Option | Meaning |
|---|---|
| `HOST` | Node to ssh to (positional, optional). |
| `--minutes N` | Alert threshold in minutes (default 90). |
| `--log PATH` | Log path (default `linbpq/logLatest_BBS.txt`, relative to the remote home). |
| `--local` | Read the log from this machine — for running on the node itself. |
| `--state PATH` | Where the sent-alert marker lives. |
| `--dry-run` | Print the would-be alert; sends nothing, touches no state. |

Exit status: `0` when the BBS is active, `1` when idle past the
threshold (alert sent or already sent), `2` on errors.

## Scheduling

Every 15 minutes from the workstation:

```cron
*/15 * * * * . "$HOME/workspace/bpq-tasks/bpq.env" && python3 "$HOME/workspace/bpq-tasks/check_bbs_activity.py" >> "$HOME/workspace/bpq-tasks/bpq_admin.log" 2>&1
```

To run it on the node instead, copy the script there, set the two
Telegram variables in the node's crontab, and add `--local`.

## Testing

```bash
# See the current verdict without sending anything
python check_bbs_activity.py --dry-run

# Force the alert path (a real message to your Telegram chat)
python check_bbs_activity.py --minutes 1 --state /tmp/bbs-test-state
```
