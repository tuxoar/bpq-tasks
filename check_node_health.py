#!/usr/bin/env python3
"""Watch the node's programs and logs and send a Telegram alert on trouble.

Runs locally on the node (unlike check_bbs_activity.py there is no ssh
mode - schedule it from the node's own crontab). Each run it checks:

- **Processes**: linbpq64, VARA.exe (under Wine), and direwolf must be
  running. A vanished process alerts once, and a recovery notice goes
  out when it comes back. Dire Wolf has no log file in this setup, so
  the process check is its whole story.
- **VARA's log** (C:\\VARA\\VARAHF.log in the Wine prefix) for error
  lines - above all "Soundcard Input/Output Device missing in action !",
  plus generic error/failure text and rejected commands.
- **The BBS log** (logLatest_BBS.txt) for error text on its system
  lines, and for "Mail Starting" entries, which mark linbpq itself
  (re)starting - several in a row means it is crashing and coming back.

Only lines newer than the scan window (default 15 minutes) count, and a
state file remembers what was already reported, so an error that keeps
repeating alerts once when it starts, not on every run; when it stops
and later returns, it alerts again. Findings are batched into one
Telegram message per run.

Log timestamps carry no timezone and may be UTC or node-local time; the
script decides per file by comparing the newest entry against the
file's modification time.

Configuration comes from the environment (see bpq.env.sample):
BPQ_NOTIFY_TELEGRAM_TOKEN and BPQ_NOTIFY_TELEGRAM_CHAT.

Exit status: 0 quiet, 1 when anything was alerted, 2 on errors.
"""

import argparse
import calendar
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# Overridable so tests can point the Telegram sender at a local stub.
TELEGRAM_API = "https://api.telegram.org"

DEFAULT_PROCS = "linbpq64,VARA.exe,direwolf"
DEFAULT_VARA_LOG = os.path.join("~", ".wine", "drive_c", "VARA", "VARAHF.log")
DEFAULT_BBS_LOG = os.path.join("~", "linbpq", "logLatest_BBS.txt")
DEFAULT_STATE = os.path.join("~", ".local", "state", "bpq-node-health.json")

VARA_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(.*\S)")
BBS_LINE = re.compile(r"^(\d{6} \d{2}:\d{2}:\d{2}) (.)\s*(.*\S)")

VARA_ERROR = re.compile(
    r"soundcard|missing in action|error|fail|wrong command|denied"
    r"|invalid|cannot|can't|unable", re.IGNORECASE)
BBS_ERROR = re.compile(
    r"error|fail|crash|unable|cannot|can't|denied|no such|invalid"
    r"|corrupt|lost", re.IGNORECASE)
BBS_RESTART = re.compile(r"^Mail Starting\b")


def die(message):
    print("ERROR: " + message, file=sys.stderr)
    sys.exit(2)


def running(name):
    try:
        return subprocess.run(
            ["pgrep", "-x", name], stdout=subprocess.DEVNULL,
            timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        die(f"cannot run pgrep: {exc}")


def pick_offset(newest, mtime, local_minutes):
    """Log timestamps' UTC offset: whichever candidate basis (UTC or
    this machine's local time) puts the newest entry closest to the
    file's mtime."""
    if newest is None:
        return 0

    def distance(off):
        epoch = calendar.timegm(newest.timetuple()) - off * 60
        return abs(mtime - epoch)

    return min({0, local_minutes}, key=lambda off: (distance(off), abs(off)))


def zone_label(offset):
    return ("UTC" if offset == 0 else "UTC%s%02d:%02d" % (
        "+" if offset > 0 else "-", abs(offset) // 60, abs(offset) % 60))


def parse_vara(line):
    match = VARA_LINE.match(line)
    if not match:
        return None
    try:
        stamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    text = match.group(2)
    return (stamp, text) if VARA_ERROR.search(text) else None


def parse_bbs(line):
    match = BBS_LINE.match(line)
    if not match or match.group(2) not in "!?":
        return None
    try:
        stamp = datetime.strptime(match.group(1), "%y%m%d %H:%M:%S")
    except ValueError:
        return None
    text = match.group(3)
    if BBS_RESTART.match(text):
        return stamp, "Mail Starting (linbpq started or restarted)"
    return (stamp, text) if BBS_ERROR.search(text) else None


def newest_stamp(lines, parse_stamp_only):
    for line in reversed(lines):
        stamp = parse_stamp_only(line)
        if stamp:
            return stamp
    return None


def scan_log(label, path, parser_fn, stamp_fn, window_minutes,
             local_minutes, missing):
    """Grouped error lines within the window: {text: (count, stamp, zone)}.

    Timestamp-based rather than offset-based on purpose: VARA rewrites
    VARAHF.log in place to cap its size, so byte offsets do not survive,
    but timestamps only ever move forward.
    """
    real = os.path.realpath(os.path.expanduser(path))
    try:
        with open(real, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().split("\n")
        mtime = int(os.stat(real).st_mtime)
    except OSError:
        missing.append(f"{label}: cannot read {path}")
        return {}, ""
    offset = pick_offset(newest_stamp(lines, stamp_fn), mtime, local_minutes)
    zone = zone_label(offset)
    now = (datetime.now(timezone.utc)
           + timedelta(minutes=offset)).replace(tzinfo=None)
    boundary = now - timedelta(minutes=window_minutes)

    groups = {}
    for line in lines:
        parsed = parser_fn(line)
        if not parsed or parsed[0] <= boundary:
            continue
        stamp, text = parsed
        count, latest = groups.get(text, (0, stamp))
        groups[text] = (count + 1, max(latest, stamp))
    return groups, zone


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


def load_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
        if isinstance(state, dict):
            return state
    except (OSError, ValueError):
        pass
    return {}


def save_state(path, state):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Alert on Telegram when linbpq, VARA, or direwolf "
                    "stops running or logs errors. Runs on the node.")
    parser.add_argument(
        "--minutes", type=int, default=15,
        help="scan log lines from the last N minutes (default: 15; "
             "set a little above the cron cadence)")
    parser.add_argument(
        "--procs", default=DEFAULT_PROCS,
        help=f"comma-separated process names that must be running "
             f"(default: {DEFAULT_PROCS}; empty string to skip)")
    parser.add_argument(
        "--vara-log", default=DEFAULT_VARA_LOG,
        help=f"VARA log to scan (default: {DEFAULT_VARA_LOG}; "
             "'skip' to disable)")
    parser.add_argument(
        "--bbs-log", default=DEFAULT_BBS_LOG,
        help=f"BBS log to scan (default: {DEFAULT_BBS_LOG}; "
             "'skip' to disable)")
    parser.add_argument(
        "--state", default=DEFAULT_STATE,
        help="file remembering what was already alerted "
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

    local_offset = datetime.now().astimezone().utcoffset() or timedelta()
    local_minutes = int(local_offset.total_seconds() // 60)

    state_path = os.path.expanduser(args.state)
    state = load_state(state_path)
    was_down = set(state.get("down", []))
    known_errors = set(state.get("errors", []))

    # --- processes -------------------------------------------------------
    procs = [name.strip() for name in args.procs.split(",") if name.strip()]
    down = [name for name in procs if not running(name)]
    newly_down = [name for name in down if name not in was_down]
    recovered = [name for name in was_down if name in procs
                 and name not in down]

    # --- logs ------------------------------------------------------------
    def bbs_stamp(line):
        match = BBS_LINE.match(line)
        if match:
            try:
                return datetime.strptime(match.group(1), "%y%m%d %H:%M:%S")
            except ValueError:
                pass
        return None

    def vara_stamp(line):
        match = VARA_LINE.match(line)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        return None

    missing = []
    sources = []
    if args.vara_log != "skip":
        sources.append(("VARA", args.vara_log, parse_vara, vara_stamp))
    if args.bbs_log != "skip":
        sources.append(("BPQ BBS", args.bbs_log, parse_bbs, bbs_stamp))

    seen_errors = set()
    fresh, ongoing = [], []
    for label, path, parser_fn, stamp_fn in sources:
        groups, zone = scan_log(label, path, parser_fn, stamp_fn,
                                args.minutes, local_minutes, missing)
        for text, (count, latest) in sorted(groups.items(),
                                            key=lambda item: item[1][1]):
            signature = f"{label}|{text}"
            seen_errors.add(signature)
            times = "" if count == 1 else f"{count}x "
            item = (f'{label}: {times}"{text}" '
                    f"(latest {latest:%Y-%m-%d %H:%M} {zone})")
            (ongoing if signature in known_errors else fresh).append(item)

    for note in missing:
        signature = "missing|" + note
        seen_errors.add(signature)
        if signature not in known_errors:
            fresh.append(note)

    # --- report ----------------------------------------------------------
    host = socket.gethostname()
    lines = [f"{name} is NOT running" for name in newly_down] + fresh
    if recovered:
        lines += [f"{name} is running again" for name in recovered]

    for item in ongoing:
        print(f"still occurring (already alerted): {item}")
    for name in down:
        if name not in newly_down:
            print(f"still down (already alerted): {name}")

    if not lines:
        active = len(down) + len(ongoing)
        print(f"OK: no new findings in the last {args.minutes} min"
              + (f" ({active} known issue(s) still active)" if active
                 else ""))
        if not args.dry_run and (state.get("down") != down
                                 or set(state.get("errors", []))
                                 != seen_errors):
            save_state(state_path, {"down": down,
                                    "errors": sorted(seen_errors)})
        return 0

    message = f"BPQ node health on {host}:\n" + "\n".join(
        "- " + line for line in lines)
    if len(message.encode()) > 3900:
        message = message.encode()[:3900].decode("utf-8", "ignore") \
            + "\n- ... (truncated)"

    if args.dry_run:
        print("DRY RUN - would send:")
        print(message)
        return 1

    send_telegram(token, chat, message)
    print("alert sent:")
    print(message)
    save_state(state_path, {"down": down, "errors": sorted(seen_errors)})
    return 1


if __name__ == "__main__":
    sys.exit(main())
