#!/usr/bin/env python3
"""Send a Telegram alert when nobody has connected to the BBS recently.

Reads the node's current BBS log (logLatest_BBS.txt), finds the last
"Incoming Connect from" entry, and sends a Telegram message when that
connect is older than the threshold (default 90 minutes).  Built for a
scheduled run: a state file suppresses repeat alerts for the same gap,
so the alert fires once and again only after a new connect starts (and
ends) a new gap.

The log is fetched over SSH with key auth, like backup_node.sh, unless
--local says the script is running on the node itself.  logLatest links
to a per-day file, so just after midnight it covers less than the
threshold window; the previous day's log is then checked too.  Log
timestamps carry no timezone and may be UTC or node-local time; the
script decides which by comparing the log's last entry against the
file's modification time.

Configuration comes from the environment (see bpq.env.sample):
BPQ_NOTIFY_TELEGRAM_TOKEN and BPQ_NOTIFY_TELEGRAM_CHAT for the alert,
BPQ_BACKUP_HOST or BPQ_HOST for the node when HOST isn't given.

Exit status: 0 when the BBS has seen a connect within the window,
1 when it hasn't (alert sent or suppressed), 2 on errors.
"""

import argparse
import calendar
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# Overridable so tests can point the Telegram sender at a local stub.
TELEGRAM_API = "https://api.telegram.org"

# Relative paths resolve against the home directory on whichever machine
# holds the log (the ssh login's home, or ~ with --local).
DEFAULT_LOG = "linbpq/logLatest_BBS.txt"
DEFAULT_STATE = os.path.join("~", ".local", "state", "bpq-bbs-activity")

STAMP = re.compile(r"^(\d{6} \d{2}:\d{2}:\d{2}) ")
CONNECT = re.compile(
    r"^(\d{6} \d{2}:\d{2}:\d{2}) \|\S+\s+Incoming Connect from (\S+)")
DAILY_LOG = re.compile(r"log_(\d{6})_BBS")


def die(message):
    print("ERROR: " + message, file=sys.stderr)
    sys.exit(2)


def parse_stamp(text):
    try:
        return datetime.strptime(text, "%y%m%d %H:%M:%S")
    except ValueError:
        return None


def tz_minutes(offset):
    """Minutes east of UTC from a date +%z string like -0400."""
    match = re.fullmatch(r"([+-])(\d{2})(\d{2})", offset.strip())
    if not match:
        return 0
    minutes = int(match.group(2)) * 60 + int(match.group(3))
    return -minutes if match.group(1) == "-" else minutes


def ssh_output(host, command):
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             host, command],
            capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        die(f"ssh to {host} timed out")
    except OSError as exc:
        die(f"cannot run ssh: {exc}")
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit status {proc.returncode}"
        die(f"ssh to {host} failed: {detail}")
    return proc.stdout


def read_node(host, log):
    """Resolved path, node UTC offset, mtime, and lines of the log."""
    out = ssh_output(host, (
        'R=$(readlink -f %s) && echo "$R" && date +%%z && '
        'stat -c %%Y "$R" && cat "$R"' % shlex.quote(log)))
    lines = out.split("\n")
    if len(lines) < 3 or not lines[2].isdigit():
        die(f"unexpected reply reading {log} on {host}: {out[:200]!r}")
    return lines[0], tz_minutes(lines[1]), int(lines[2]), lines[3:]


def read_node_extra(host, path):
    return ssh_output(
        host, "cat %s 2>/dev/null || true" % shlex.quote(path)).split("\n")


def local_path(log):
    path = os.path.expanduser(log)
    if not os.path.isabs(path):
        path = os.path.join(os.path.expanduser("~"), path)
    return path


def read_local(log):
    real = os.path.realpath(local_path(log))
    try:
        with open(real, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().split("\n")
        mtime = int(os.stat(real).st_mtime)
    except OSError as exc:
        die(f"cannot read {log}: {exc}")
    offset = datetime.now().astimezone().utcoffset() or timedelta()
    return real, int(offset.total_seconds() // 60), mtime, lines


def read_local_extra(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().split("\n")
    except OSError:
        return []


def connects(lines):
    found = []
    for line in lines:
        match = CONNECT.match(line)
        if match:
            stamp = parse_stamp(match.group(1))
            if stamp:
                found.append((stamp, match.group(2)))
    return found


def last_stamp(lines):
    for line in reversed(lines):
        match = STAMP.match(line)
        if match:
            stamp = parse_stamp(match.group(1))
            if stamp:
                return stamp
    return None


def previous_log_path(realpath):
    """Yesterday's per-day log, derived from the resolved logLatest."""
    base = os.path.basename(realpath)
    match = DAILY_LOG.search(base)
    if not match:
        return None
    try:
        day = datetime.strptime(match.group(1), "%y%m%d") - timedelta(days=1)
    except ValueError:
        return None
    previous = base[:match.start(1)] + day.strftime("%y%m%d") + base[match.end(1):]
    return os.path.join(os.path.dirname(realpath), previous)


def pick_offset(newest, mtime, node_minutes):
    """Log timestamps' UTC offset: whichever candidate basis (UTC or the
    node's local time) puts the newest entry closest to the file mtime."""
    if newest is None:
        return 0

    def distance(off):
        epoch = calendar.timegm(newest.timetuple()) - off * 60
        return abs(mtime - epoch)

    return min({0, node_minutes}, key=lambda off: (distance(off), abs(off)))


def send_telegram(token, chat, text):
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, payload = exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        die(f"telegram send failed: {exc}")
    if status != 200 or b'"ok":true' not in payload.replace(b" ", b""):
        die(f"telegram returned HTTP {status}: "
            f"{payload[:200].decode('utf-8', 'replace')}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Alert on Telegram when the BBS has had no incoming "
                    "connect within the threshold window.")
    parser.add_argument(
        "host", nargs="?",
        help="node to ssh to (default: BPQ_BACKUP_HOST or BPQ_HOST)")
    parser.add_argument(
        "--log", default=DEFAULT_LOG,
        help=f"path to logLatest_BBS.txt (default: {DEFAULT_LOG})")
    parser.add_argument(
        "--minutes", type=int, default=90,
        help="alert when no connect within this many minutes (default: 90)")
    parser.add_argument(
        "--local", action="store_true",
        help="read the log from this machine instead of over ssh")
    parser.add_argument(
        "--state", default=DEFAULT_STATE,
        help="file remembering the gap already alerted on "
             f"(default: {DEFAULT_STATE})")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print the alert instead of sending it; never touches state")
    args = parser.parse_args(argv)
    if args.minutes <= 0:
        parser.error("--minutes must be positive")

    token = os.environ.get("BPQ_NOTIFY_TELEGRAM_TOKEN", "")
    chat = os.environ.get("BPQ_NOTIFY_TELEGRAM_CHAT", "")
    if not args.dry_run and not (token and chat):
        parser.error("set BPQ_NOTIFY_TELEGRAM_TOKEN and "
                     "BPQ_NOTIFY_TELEGRAM_CHAT (see bpq.env.sample), "
                     "or use --dry-run")

    host = (args.host or os.environ.get("BPQ_BACKUP_HOST")
            or os.environ.get("BPQ_HOST"))
    if args.local:
        real, node_off, mtime, lines = read_local(args.log)
        where = "this node"
    else:
        if not host:
            parser.error("no node host: pass HOST, set BPQ_BACKUP_HOST or "
                         "BPQ_HOST, or use --local")
        real, node_off, mtime, lines = read_node(host, args.log)
        where = host

    seen = connects(lines)
    if not seen:
        # Today's log has no connects yet; the last one may sit in
        # yesterday's log, still inside the window.
        previous = previous_log_path(real)
        if previous:
            extra = (read_local_extra(previous) if args.local
                     else read_node_extra(host, previous))
            seen = connects(extra)

    offset = pick_offset(last_stamp(lines), mtime, node_off)
    zone = ("UTC" if offset == 0 else "UTC%s%02d:%02d" % (
        "+" if offset > 0 else "-", abs(offset) // 60, abs(offset) % 60))
    now = (datetime.now(timezone.utc)
           + timedelta(minutes=offset)).replace(tzinfo=None)

    if seen:
        when, call = max(seen)
        age = int((now - when).total_seconds() // 60)
        key = when.strftime("%y%m%d %H:%M:%S")
    else:
        when = call = age = None
        key = "none"

    state_path = os.path.expanduser(args.state)
    idle = when is None or age > args.minutes

    if not idle:
        print(f"OK: last connect {call} {age} min ago "
              f"(at {when:%Y-%m-%d %H:%M} {zone})")
        if os.path.exists(state_path):
            os.remove(state_path)
        return 0

    if when is not None:
        message = (f"BBS alert: no one has connected to the BBS on {where} "
                   f"for {age} minutes (threshold {args.minutes}). "
                   f"Last connect: {call} at {when:%Y-%m-%d %H:%M} {zone}.")
    else:
        message = (f"BBS alert: no connects found on {where} in the current "
                   f"or previous day's BBS log "
                   f"(threshold {args.minutes} minutes).")

    if args.dry_run:
        print("DRY RUN - would send:")
        print(message)
        return 1

    already = ""
    try:
        with open(state_path, encoding="utf-8") as handle:
            already = handle.read().strip()
    except OSError:
        pass
    if already == key:
        print(f"still idle; alert for this gap already sent (last connect "
              f"{key}) - not re-sending")
        return 1

    send_telegram(token, chat, message)
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as handle:
        handle.write(key + "\n")
    print("alert sent: " + message)
    return 1


if __name__ == "__main__":
    sys.exit(main())
