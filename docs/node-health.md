[← back to README](../README.md)

# Node health alert (`check_node_health.py`)

Watches the programs that keep the node on the air and sends a
**Telegram** message when one of them dies or starts logging errors —
above all VARA's `Soundcard Input/Output Device missing in action !`.
Runs **locally on the node** (there is no ssh mode — schedule it from
the node's own crontab).

```bash
source bpq.env
python3 check_node_health.py            # check, alert on anything new
python3 check_node_health.py --dry-run  # print instead of sending
```

## What it checks

| Check | How |
|---|---|
| **linbpq64, VARA.exe, direwolf running** | `pgrep` per process. A vanished process alerts once; a recovery notice goes out when it comes back. Dire Wolf logs only to its terminal in this setup, so the process check is its whole story. |
| **VARA's log** (`~/.wine/drive_c/VARA/VARAHF.log`) | Scans recent lines for soundcard-missing, error/failure text, and rejected commands (`Wrong command: ...`). |
| **The BBS log** (`~/linbpq/logLatest_BBS.txt`) | Scans recent *system* lines (`!` / `?` flagged — message traffic can't false-trigger) for error text, and reports `Mail Starting` entries, which mark linbpq itself starting or restarting — several in a row means it's crashing and coming back. |

Findings are batched into **one message per run**:

> BPQ node health on bpqnode:
> - VARA: 15x "Soundcard Input Device missing in action !" (latest 2026-09-11 00:45 UTC)
> - BPQ BBS: 3x "Mail Starting (linbpq started or restarted)" (latest 2026-09-11 00:55 UTC)

## Noise control

- Only log lines from the last `--minutes` window count (default 15 —
  set it a little above the cron cadence).
- The state file (`~/.local/state/bpq-node-health.json`) remembers what
  was already reported: an error repeating every 40 seconds alerts once
  when it starts, not on every cron run. Once it stops for a full run
  and later returns, it alerts again. Down processes work the same way.
- Log timestamps carry no timezone and may be UTC or node-local time;
  the script decides per file by comparing the newest entry against the
  file's modification time.

## Options

| Option | Meaning |
|---|---|
| `--minutes N` | Log scan window (default 15). |
| `--procs a,b,c` | Processes that must be running (default `linbpq64,VARA.exe,direwolf`; empty to skip). |
| `--vara-log PATH` | VARA log (default `~/.wine/drive_c/VARA/VARAHF.log`; `skip` to disable). |
| `--bbs-log PATH` | BBS log (default `~/linbpq/logLatest_BBS.txt`; `skip` to disable). |
| `--state PATH` | Where already-reported findings are remembered. |
| `--dry-run` | Print the would-be alert; sends nothing, touches no state. |

Telegram credentials come from `BPQ_NOTIFY_TELEGRAM_TOKEN` and
`BPQ_NOTIFY_TELEGRAM_CHAT` (see [Configuration](configuration.md)).
Exit status: `0` quiet, `1` when anything was alerted, `2` on errors.

## Scheduling

Every 10 minutes on the node, with a 15-minute window so nothing falls
between runs:

```cron
*/10 * * * * /bin/bash -c 'source /home/shaun/bpq-tasks/bpq.env && exec /usr/bin/python3 /home/shaun/bpq-tasks/check_node_health.py' >> /home/shaun/bpq-tasks/bpq_admin.log 2>&1
```
