#!/usr/bin/env python3
"""bpq_admin.py - administer a BPQ32/LinBPQ node over its telnet port.

Actions:
    list                connect, log in, enter the BBS, run LPN (list
                        private new messages) and print the listing
    clean-housekeeping  run LPN, find every "SYSTEM Housekeeping Results"
                        message, and kill each one with the K command;
                        --dry-run shows what would be killed
    run-reports         run LT and report the traffic messages whose date
                        falls in --from/--to (inclusive): the matching
                        lines, then starting number, ending number, total
    export-stale        run LTN, find traffic messages --days or more days
                        old, and export each one (read with R) into a new
                        folder named after the run's timestamp

Runs unmodified on Windows and Linux with stock Python 3.8+. It speaks
telnet over a raw socket on purpose: the stdlib telnetlib module was
removed in Python 3.13, and BPQ's telnet server only needs the IAC
option requests refused.

Usage:
    python bpq_admin.py list mynode.example.com --user N0CALL
    python bpq_admin.py clean-housekeeping mynode.example.com --user N0CALL

Connection values can come from environment variables instead of the
command line, so they are not captured in shell history or the process
list: BPQ_HOST, BPQ_PORT, BPQ_USER, BPQ_PASSWORD. Command-line arguments
take precedence; a missing password is prompted for.
"""

import argparse
import datetime as dt
import getpass
import logging
import os
import re
import socket
import sys
import time

log = logging.getLogger("bpq_admin")

# Telnet protocol bytes
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240

LOGIN_PROMPTS = ("user:", "callsign:", "login:")
PASSWORD_PROMPTS = ("password:",)
LOGIN_FAILED = ("invalid", "bad user", "attempts")

# An LPN line for a housekeeping report, and nothing else:
#   3308   31-Aug PN     177 SYSOP          SYSTEM Housekeeping Results
# id, date, type PN, size, then exactly "SYSOP  SYSTEM Housekeeping Results"
# to the end of the line. Kept strict so no other message can match.
HOUSEKEEPING_RE = re.compile(
    r"^\s*(\d+)\s+\d{2}-[A-Za-z]{3}\s+PN\s+\d+\s+"
    r"SYSOP\s+SYSTEM Housekeeping Results\s*$",
    re.MULTILINE,
)

# An LT line for a traffic message (type T-something):
#   316    24-Oct TF     502 14424  @NTSNY  KC1KVY CANANDAIGUA 585 755
TRAFFIC_LINE_RE = re.compile(r"^\s*(\d+)\s+(\d{1,2})-([A-Za-z]{3})\s+T\S\s")

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


class BpqSession:
    """A logged-in telnet session with a BPQ node."""

    def __init__(self, host, port, timeout=10.0, verbose=False):
        self.timeout = timeout
        self.verbose = verbose
        self.transcript = ""
        self.bbs_prompt = ">"  # replaced with the real prompt in enter_bbs
        self._pending = b""  # partial IAC sequence split across recv() calls
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(0.2)

    # --- low-level I/O -------------------------------------------------

    def _strip_telnet(self, data):
        """Remove IAC sequences from data, refusing every option request."""
        data = self._pending + data
        self._pending = b""
        out = bytearray()
        i = 0
        while i < len(data):
            if data[i] != IAC:
                out.append(data[i])
                i += 1
                continue
            if i + 1 >= len(data):
                self._pending = data[i:]
                break
            cmd = data[i + 1]
            if cmd == IAC:  # escaped 0xFF data byte
                out.append(IAC)
                i += 2
            elif cmd in (DO, DONT, WILL, WONT):
                if i + 2 >= len(data):
                    self._pending = data[i:]
                    break
                opt = data[i + 2]
                if cmd == DO:
                    self.sock.sendall(bytes([IAC, WONT, opt]))
                elif cmd == WILL:
                    self.sock.sendall(bytes([IAC, DONT, opt]))
                i += 3
            elif cmd == SB:
                end = data.find(bytes([IAC, SE]), i + 2)
                if end == -1:
                    self._pending = data[i:]
                    break
                i = end + 2
            else:
                i += 2
        return bytes(out)

    def _poll(self):
        """Read whatever is available; returns "" on a quiet link."""
        try:
            chunk = self.sock.recv(4096)
        except socket.timeout:
            return ""
        if not chunk:
            raise ConnectionError("connection closed by node")
        text = self._strip_telnet(chunk).decode("utf-8", errors="replace")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.transcript += text
        return text

    def read_until(self, predicate, timeout=None):
        """Accumulate output until predicate(buffer) is true or time runs out.

        Returns (buffer, matched).
        """
        deadline = time.monotonic() + (timeout or self.timeout)
        buf = ""
        while time.monotonic() < deadline:
            buf += self._poll()
            if predicate(buf):
                return buf, True
        return buf, False

    def drain(self, quiet=1.0):
        """Read until the node has been silent for `quiet` seconds.

        A closed connection ends the drain rather than raising, so the
        text the node sent before hanging up is still returned.
        """
        buf = ""
        last = time.monotonic()
        while time.monotonic() - last < quiet:
            try:
                got = self._poll()
            except ConnectionError:
                break
            if got:
                buf += got
                last = time.monotonic()
        return buf

    def send_line(self, line):
        self.sock.sendall((line + "\r\n").encode("utf-8"))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    # --- session steps -------------------------------------------------

    def login(self, user, password):
        buf, ok = self.read_until(contains_any(LOGIN_PROMPTS))
        if not ok:
            raise RuntimeError("never saw a login prompt; got:\n" + buf)
        self.send_line(user)

        buf, ok = self.read_until(contains_any(PASSWORD_PROMPTS))
        if not ok:
            raise RuntimeError("never saw a password prompt; got:\n" + buf)
        self.send_line(password)

        # No fixed prompt follows a good login (the node just sends its
        # CTEXT), so read the banner and check it isn't a rejection.
        banner = self.drain()
        if contains_any(LOGIN_FAILED + LOGIN_PROMPTS)(banner):
            raise RuntimeError("login rejected:\n" + banner)
        log.info("logged in as %s", user)
        return banner

    def enter_bbs(self):
        self.send_line("BBS")
        buf, ok = self.read_until(at_bbs_prompt)
        if not ok:
            raise RuntimeError("no BBS prompt after BBS command; got:\n" + buf)
        # Remember the exact prompt (e.g. "de VK0TST>") so later reads
        # only stop on it, not on any output line that ends in ">" -
        # message bodies read with R can contain such lines.
        last = buf.rstrip().rsplit("\n", 1)[-1].strip()
        if last.endswith(">"):
            self.bbs_prompt = last
        log.info("entered BBS (prompt %r)", self.bbs_prompt)
        print(f"BBS login successful (prompt {self.bbs_prompt!r})",
              file=sys.stderr)
        return buf

    def bbs_command(self, command):
        """Run one BBS command and return its output, prompt stripped."""
        print(f"running {command} ...", file=sys.stderr)
        log.info("running BBS command %r", command)
        started = time.monotonic()
        self.send_line(command)
        prompt = self.bbs_prompt
        buf, ok = self.read_until(lambda b: b.rstrip().endswith(prompt))
        if not ok:
            buf += self.drain()
        lines = buf.strip("\n").split("\n")
        # Drop the echoed command and the trailing prompt line.
        if lines and lines[0].strip().lower() == command.lower():
            lines = lines[1:]
        if lines and lines[-1].rstrip().endswith(prompt):
            lines = lines[:-1]
        log.info("BBS command %r -> %d line(s) of output in %.1fs",
                 command, len(lines), time.monotonic() - started)
        return "\n".join(lines)

    def logout(self):
        """Leave the BBS, then the node. Best-effort - the node may just
        drop the link at any point, which is success too."""
        try:
            self.send_line("B")
            self.drain(quiet=0.5)
            self.send_line("BYE")
            self.drain(quiet=0.5)
        except ConnectionError:
            pass
        log.info("logged out")


def contains_any(needles):
    lowered = tuple(n.lower() for n in needles)
    return lambda buf: any(n in buf.lower() for n in lowered)


def at_bbs_prompt(buf):
    """BPQ's BBS prompt is a line ending in '>' (e.g. 'de G8BPQ>')."""
    return buf.rstrip().endswith(">")


def most_recent(day, month, today):
    """The most recent occurrence of day-month on or before `today`.
    BBS listings show dates without a year, so this is how they (and
    DD-Mon range arguments) are pinned to a real date."""
    d = dt.date(today.year, month, day)
    return d if d <= today else dt.date(today.year - 1, month, day)


def parse_report_date(text):
    """--from/--to value: YYYY-MM-DD, or DD-Mon as the BBS displays it."""
    s = text.strip()
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})", s)
    if m and m.group(2).lower() in MONTHS:
        try:
            return most_recent(int(m.group(1)), MONTHS[m.group(2).lower()],
                               dt.date.today())
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f"invalid date {text!r}: use YYYY-MM-DD or DD-Mon (e.g. 22-Oct)")


def positive_int(text):
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(
            f"invalid count {text!r}: must be a positive integer")
    return value


def housekeeping_ids(listing):
    """Message IDs of the SYSTEM Housekeeping Results entries in an LPN
    listing, in the order they appear. Only lines matching the full
    housekeeping shape count; every other message is left alone."""
    return [int(m.group(1)) for m in HOUSEKEEPING_RE.finditer(listing)]


def do_list(session, args):
    listing = session.bbs_command("LPN")
    print(listing if listing.strip() else "(no new private messages)")
    return 0


def do_clean_housekeeping(session, args):
    listing = session.bbs_command("LPN")
    ids = housekeeping_ids(listing)
    total_lines = sum(1 for l in listing.splitlines() if l.strip())
    print(f"LPN returned {total_lines} messages; "
          f"{len(ids)} are SYSTEM Housekeeping Results", file=sys.stderr)

    log.info("LPN listed %d message(s); %d matched housekeeping",
             total_lines, len(ids))
    if not ids:
        print("nothing to kill")
        return 0

    if args.dry_run:
        log.info("dry run: would kill %s", " ".join(str(i) for i in ids))
        print("would kill: " + " ".join(str(i) for i in ids))
        return 0

    failures = []
    for msg_id in ids:
        reply = session.bbs_command(f"K {msg_id}")
        if "kill" in reply.lower():
            log.info("killed message %d (confirmed)", msg_id)
            print(f"killed {msg_id}")
        else:
            failures.append(msg_id)
            log.warning("kill of message %d NOT confirmed; reply: %s",
                        msg_id, reply.strip())
            print(f"NOT CONFIRMED for {msg_id}: {reply.strip()}",
                  file=sys.stderr)

    log.info("killed %d of %d housekeeping message(s)",
             len(ids) - len(failures), len(ids))
    print(f"killed {len(ids) - len(failures)} of {len(ids)} "
          f"housekeeping messages")
    return 1 if failures else 0


def do_run_reports(session, args):
    start, end = args.date_from, args.date_to
    today = dt.date.today()
    listing = session.bbs_command("LT")

    traffic = []
    for line in listing.splitlines():
        m = TRAFFIC_LINE_RE.match(line)
        if not m:
            continue
        try:
            msg_date = most_recent(int(m.group(2)),
                                   MONTHS[m.group(3).lower()], today)
        except (KeyError, ValueError):
            continue
        traffic.append((int(m.group(1)), msg_date, line.rstrip()))

    # Listing dates have no year, so bound the lookback: only the --last
    # highest-numbered messages are considered before the date filter.
    if len(traffic) > args.last:
        total = len(traffic)
        keep = set(sorted((t[0] for t in traffic), reverse=True)[:args.last])
        traffic = [t for t in traffic if t[0] in keep]
        log.info("LT: capped to the latest %d of %d traffic message(s)",
                 args.last, total)
        print(f"considering only the latest {args.last} of {total} "
              f"traffic messages", file=sys.stderr)

    matched = [(msg_id, line) for msg_id, msg_date, line in traffic
               if start <= msg_date <= end]
    log.info("LT: %d traffic message(s) dated %s to %s",
             len(matched), start, end)
    if not matched:
        print(f"no traffic messages between {start} and {end}")
        return 0

    for _, line in matched:
        print(line)
    ids = [msg_id for msg_id, _ in matched]
    print()
    print(f"starting message: {min(ids)}")
    print(f"ending message:   {max(ids)}")
    print(f"total messages:   {len(ids)}")
    log.info("report: starting %d, ending %d, total %d",
             min(ids), max(ids), len(ids))
    return 0


def do_export_stale(session, args):
    today = dt.date.today()
    cutoff = today - dt.timedelta(days=args.days)
    listing = session.bbs_command("LTN")

    stale = []
    for line in listing.splitlines():
        m = TRAFFIC_LINE_RE.match(line)
        if not m:
            continue
        try:
            msg_date = most_recent(int(m.group(2)),
                                   MONTHS[m.group(3).lower()], today)
        except (KeyError, ValueError):
            continue
        if msg_date <= cutoff:
            stale.append((int(m.group(1)), line.rstrip()))

    log.info("LTN: %d stale traffic message(s) dated on or before %s",
             len(stale), cutoff)
    if not stale:
        print(f"no stale traffic messages (none dated on or before {cutoff})")
        return 0

    run_dir = os.path.join(args.out_dir, time.strftime("stale-%Y%m%d-%H%M%S"))
    os.makedirs(run_dir)
    log.info("exporting %d message(s) to %s", len(stale), run_dir)
    print(f"exporting {len(stale)} stale message(s) to {run_dir}",
          file=sys.stderr)

    with open(os.path.join(run_dir, "index.txt"), "w",
              encoding="utf-8") as f:
        f.write(f"stale traffic messages dated on or before {cutoff}, "
                f"exported {today}\n\n")
        for _, line in stale:
            f.write(line + "\n")

    for msg_id, _ in stale:
        body = session.bbs_command(f"R {msg_id}")
        path = os.path.join(run_dir, f"msg_{msg_id}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body + "\n")
        log.info("exported message %d to %s", msg_id, path)
        print(f"exported {msg_id}")

    print(f"exported {len(stale)} message(s) to {run_dir}")
    return 0


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("host", nargs="?",
                        default=os.environ.get("BPQ_HOST"),
                        help="hostname or IP of the BPQ node "
                             "(or set BPQ_HOST)")
    common.add_argument("--port", type=int, default=None,
                        help="telnet port of the node "
                             "(or set BPQ_PORT; default 8010)")
    common.add_argument("--user", default=os.environ.get("BPQ_USER"),
                        help="node login user (or set BPQ_USER)")
    common.add_argument("--password",
                        help="node login password (else BPQ_PASSWORD env "
                             "var, else prompted)")
    common.add_argument("--timeout", type=float, default=10.0,
                        help="seconds to wait for each prompt (default 10)")
    common.add_argument("--log-file", default="bpq_admin.log",
                        help="append a timestamped record of each action to "
                             "this file (default bpq_admin.log; use "
                             "--log-file '' to disable)")
    common.add_argument("--verbose", action="store_true",
                        help="dump the full session transcript on exit")

    parser = argparse.ArgumentParser(
        description="Administer a BPQ node's BBS over telnet."
    )
    sub = parser.add_subparsers(dest="action", required=True,
                                metavar="action")
    sub.add_parser("list", parents=[common],
                   help="list private new messages (LPN)")
    clean = sub.add_parser(
        "clean-housekeeping", parents=[common],
        help="kill every 'SYSTEM Housekeeping Results' message in LPN")
    clean.add_argument("--dry-run", action="store_true",
                       help="show the message IDs that would be killed, "
                            "without killing anything")
    reports = sub.add_parser(
        "run-reports", parents=[common],
        help="report traffic messages (LT) within a date range")
    reports.add_argument("--from", dest="date_from", required=True,
                         type=parse_report_date, metavar="DATE",
                         help="start of range, inclusive "
                              "(YYYY-MM-DD or DD-Mon, e.g. 22-Oct)")
    reports.add_argument("--to", dest="date_to", required=True,
                         type=parse_report_date, metavar="DATE",
                         help="end of range, inclusive "
                              "(YYYY-MM-DD or DD-Mon, e.g. 24-Oct)")
    reports.add_argument("--last", type=positive_int, default=800,
                         metavar="N",
                         help="only consider the latest N traffic messages "
                              "from LT, since listing dates carry no year "
                              "(default 800)")
    stale = sub.add_parser(
        "export-stale", parents=[common],
        help="export traffic messages (LTN) older than --days to a "
             "timestamped folder")
    stale.add_argument("--days", type=positive_int, default=30, metavar="N",
                       help="a message N or more days old is stale "
                            "(default 30)")
    stale.add_argument("--out", dest="out_dir", default=".", metavar="DIR",
                       help="parent directory in which the per-run "
                            "stale-YYYYMMDD-HHMMSS folder is created "
                            "(default: current directory)")
    return parser


def setup_logging(path):
    """Append INFO-and-up records to `path`; empty path disables logging."""
    if not path:
        log.addHandler(logging.NullHandler())
        return
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.host:
        parser.error("host is required (positional HOST, or set BPQ_HOST)")
    if not args.user:
        parser.error("--user is required (or set BPQ_USER)")
    if args.port is None:
        port_env = os.environ.get("BPQ_PORT", "")
        if port_env and not port_env.isdigit():
            parser.error(f"invalid BPQ_PORT {port_env!r}: must be a number")
        args.port = int(port_env) if port_env else 8010
    if args.action == "run-reports" and args.date_from > args.date_to:
        parser.error(f"--from {args.date_from} is after --to {args.date_to}")
    actions = {"list": do_list, "clean-housekeeping": do_clean_housekeeping,
               "run-reports": do_run_reports, "export-stale": do_export_stale}
    setup_logging(args.log_file)

    password = args.password or os.environ.get("BPQ_PASSWORD")
    if not password:
        password = getpass.getpass("BPQ password: ")

    session = None
    try:
        log.info("--- %s: connecting to %s:%d as %s",
                 args.action, args.host, args.port, args.user)
        session = BpqSession(args.host, args.port, timeout=args.timeout,
                             verbose=args.verbose)
        print(f"Connected to {args.host}:{args.port}", file=sys.stderr)
        session.login(args.user, password)
        print("Logged in, entering BBS...", file=sys.stderr)
        session.enter_bbs()
        rc = actions[args.action](session, args)
        session.logout()
        log.info("--- %s finished with exit code %d", args.action, rc)
        return rc
    except (OSError, RuntimeError) as exc:
        log.error("--- %s failed: %s", args.action, exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if session is not None:
            if args.verbose:
                print("\n--- full transcript ---\n" + session.transcript,
                      file=sys.stderr)
            session.close()


if __name__ == "__main__":
    sys.exit(main())
