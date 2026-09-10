#!/usr/bin/env python3
"""bpq_admin.py - administer a BPQ32/LinBPQ node over its telnet port.

Actions:
    list                connect, log in, enter the BBS, run LPN (list
                        private new messages) and print the listing
    list-held           run LH and print every held message - traffic
                        the BBS is holding back from forwarding
    clean-housekeeping  run LPN, find every "SYSTEM Housekeeping Results"
                        message, and kill each one with the K command;
                        --dry-run shows what would be killed
    run-reports         run LT and report the traffic messages whose date
                        falls in --from/--to (inclusive): the matching
                        lines, then starting number, ending number, total
    export-stale        run LTN, find traffic messages --days or more days
                        old, and export each one (read with R) into a new
                        folder named after the run's timestamp
    kill-exported       kill the messages whose msg_<id>.txt files sit in
                        an export directory (--dir), once they have been
                        processed; --dry-run lists them without connecting
    list-hxc            scan the msg_<id>.txt files in an export directory
                        (--dir) for radiogram preambles carrying an HXC
                        handling instruction - the originator asked for a
                        delivery confirmation - write the radiogram
                        numbers, grouped by originating station, to a text
                        file, and generate a confirmation radiogram draft
                        per station in hxc_replies/, with each station's
                        name/address/email filled in from the QRZ.com XML
                        API (QRZ_USER/QRZ_PASSWORD or --qrz-user; --no-qrz
                        leaves placeholders). Never connects to the node
    notify-stale        list stale traffic (LTN) and the new private
                        messages nothing is forwarding on (LPN), and
                        send a notice - the listing lines and the totals
                        - to every notification channel configured in
                        the environment: Discord webhook, Telegram bot,
                        and/or SMTP email (see docs/stale-notifier-spec.md).
                        Read-only on the BBS
    check-routing       inspect every LTN traffic message's To header;
                        one that does not look like 13743@NTSNY (US) or
                        B0W2J0@NTSNS (Canada) will not be routed
                        properly, and is reported (exit 1).
                        --senders audits the full LT history instead and
                        reports which senders have created bad headers

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
import email.message
import getpass
import json
import logging
import os
import random
import re
import smtplib
import socket
import sys
import time
import urllib.parse
import urllib.request

log = logging.getLogger("bpq_admin")

# Overridable so tests can point the Telegram sender at a local stub.
TELEGRAM_API = "https://api.telegram.org"

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

# The same line with the To, route, and From columns captured: id, then
# after type and size the To field, the @route only when one is present
# (the From column never starts with '@'), then the sender.
TRAFFIC_FIELDS_RE = re.compile(
    r"^\s*(\d+)\s+\d{1,2}-[A-Za-z]{3}\s+T\S\s+\d+\s+(\S+)"
    r"(?:\s+(@\S+))?\s+(\S+)")

# An LPN line for a private message (type P-something):
#   3309   31-Aug PN      22 W2QS   @W2QS   W2QS   test
PRIVATE_LINE_RE = re.compile(r"^\s*(\d+)\s+\d{1,2}-[A-Za-z]{3}\s+P\S\s")

# A radiogram preamble carrying an HX handling instruction, inside an
# exported message body:
#   3962 R HXC W2PAX ARL 24 NAPLES FL AUG 29
#   363 R HXC WX2DX 10 STORMSTOWN PA 0152Z AUG 12
# number, precedence, the HX group(s) - codes A-G, combined as in HXCG
# or written separately as in "HXC HXG", an HXA/HXB figure allowed -
# then the station of origin.
HX_PREAMBLE_RE = re.compile(
    r"^\s*(\d+)\s+(?:TEST\s+)?(?:EMERGENCY|[RPW])\s+"
    r"(HX[A-G]+\d*(?:\s+HX[A-G]+\d*)*)\s+"
    r"([A-Z0-9]+(?:/[A-Z0-9]+)*)\b[^\n]*",
    re.IGNORECASE | re.MULTILINE)

# The station of origin, place of origin, and signature stamped on the
# HXC delivery-confirmation drafts that list-hxc generates.
REPLY_ORIGIN = "W2QS"
REPLY_PLACE = "DEANSBORO NY"
REPLY_SIGNATURE = "Shaun W2QS DTN 2RN SYSOP"

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# USPS two-letter abbreviations: states, DC, territories, military.
US_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI "
    "MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT "
    "VT VA WA WV WI WY DC PR VI GU AS MP AA AE AP").split()

# Canada Post two-letter province/territory abbreviations.
CA_PROVINCES = "AB BC MB NB NL NS NT NU ON PE QC SK YT".split()

# A routable NTS To header: a US zip @NTS<state> (13743@NTSNY), or a
# Canadian postal code @NTS<province> (B0W2J0@NTSNS). The code style
# must match the region - a US zip routed to a province is flagged.
DEFAULT_ROUTE_PATTERN = (
    r"(?:\d{5}@NTS(?:" + "|".join(US_STATES) + r")"
    r"|[A-Z]\d[A-Z]\d[A-Z]\d@NTS(?:" + "|".join(CA_PROVINCES) + "))")


class BpqSession:
    """A logged-in telnet session with a BPQ node."""

    def __init__(self, host, port, timeout=10.0, verbose=False):
        self.timeout = timeout
        self.verbose = verbose
        self.transcript = ""
        self.bbs_prompt = ">"  # replaced with the real prompt in enter_bbs
        self._pending = b""  # partial IAC sequence split across recv() calls
        try:
            self.sock = socket.create_connection((host, port),
                                                 timeout=timeout)
        except OSError as exc:
            raise OSError(f"cannot connect to {host}:{port}: {exc}") from None
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
        drop the link at any point, which is success too. Idempotent, so
        an action that logs out early is safe."""
        if getattr(self, "_logged_out", False):
            return
        self._logged_out = True
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


def do_list_held(session, args):
    listing = session.bbs_command("LH")
    print(listing if listing.strip() else "(no held messages)")
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

    failures = kill_messages(session, ids)
    log.info("killed %d of %d housekeeping message(s)",
             len(ids) - len(failures), len(ids))
    print(f"killed {len(ids) - len(failures)} of {len(ids)} "
          f"housekeeping messages")
    return 1 if failures else 0


def kill_messages(session, ids):
    """Kill each message with K, verifying every BBS reply. Returns the
    IDs whose kill the BBS did not confirm."""
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
    return failures


def exported_ids(directory):
    """Message IDs of the msg_<id>.txt files in an export directory."""
    try:
        names = os.listdir(directory)
    except OSError as exc:
        raise RuntimeError(f"cannot read {directory}: {exc}")
    return sorted(int(m.group(1)) for m in
                  (re.fullmatch(r"msg_(\d+)\.txt", n) for n in names) if m)


def do_kill_exported(session, args):
    ids = exported_ids(args.export_dir)
    log.info("killing %d message(s) exported to %s", len(ids), args.export_dir)
    print(f"killing the {len(ids)} message(s) exported to {args.export_dir}",
          file=sys.stderr)
    failures = kill_messages(session, ids)
    log.info("killed %d of %d exported message(s)",
             len(ids) - len(failures), len(ids))
    print(f"killed {len(ids) - len(failures)} of {len(ids)} "
          f"exported messages")
    return 1 if failures else 0


def find_hxc(directory):
    """Scan the msg_<id>.txt files in an export directory for radiogram
    preambles whose HX group contains C - the originator asked for a
    delivery confirmation. Returns [(bbs_id, radiogram_nr, hx, origin,
    preamble_line), ...] sorted by BBS message id."""
    found = []
    for bbs_id in exported_ids(directory):
        path = os.path.join(directory, f"msg_{bbs_id}.txt")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError as exc:
            raise RuntimeError(f"cannot read {path}: {exc}")
        for m in HX_PREAMBLE_RE.finditer(body):
            hx = m.group(2).upper()
            if "C" in hx[2:]:
                found.append((bbs_id, int(m.group(1)), hx,
                              m.group(3).upper(),
                              m.group(0).strip()))
    return found


def hxc_reply_text(nr, origin, numbers, today, contact):
    """A delivery-confirmation radiogram draft for one originating
    station: their radiogram `numbers` were delivered via email today,
    headed by the BBS filing lines (TO: zip@NTS<state>, SUBJECT: city
    and callsign). `contact` is a qrz_contact() dict; unknown fields
    fall back to fill-in placeholders, except the email line, which is
    dropped - the preamble only carries the callsign."""
    date = f"{today.strftime('%b').upper()} {today.day}"
    now = time.localtime()
    zone = "EDT" if now.tm_isdst else "EST"
    if contact.get("zip") and contact.get("state"):
        # A zip+4 or a spaced Canadian postal code would not route
        # (see check-routing): keep the 5-digit zip / packed code only.
        code = contact["zip"].split("-")[0].replace(" ", "")
        route = f"{code}@NTS{contact['state']}"
    else:
        route = "<ZIPCODE>@NTS<ST>"
    text = [f"YOUR MSG {' '.join(str(n) for n in numbers)}",
            f"delivered via email on {date} "
            f"{time.strftime('%H%M', now)} {zone}"]
    check = sum(len(line.split()) for line in text)
    # No email line at all when QRZ has none - not a placeholder.
    return ("\n".join(
        [f"TO: {route}",
         f"SUBJECT: {contact.get('city') or '<CITY>'} {origin}",
         f"NR {nr} R {REPLY_ORIGIN} {check} {REPLY_PLACE} {date}",
         f"{contact.get('name') or '<FULL NAME>'} {origin}",
         contact.get("address") or "<ONE LINE ADDRESS>"]
        + ([contact["email"]] if contact.get("email") else [])
        + ["BT"] + text + ["BT", REPLY_SIGNATURE]) + "\n").upper()


def qrz_contact(qrz, callsign):
    """Addressee details for a callsign from its QRZ record: a dict of
    name, address (one line), email, city, state, and zip - each None
    when QRZ does not carry it. (QRZ's addr2 field is the city.)"""
    record = qrz.record(callsign) or {}
    fields = {key: (record.get(key) or "").strip() or None
              for key in ("fname", "name", "addr1", "addr2", "state",
                          "zip", "email")}
    name = " ".join(p for p in (fields["fname"], fields["name"]) if p)
    address = " ".join(p for p in (fields["addr1"], fields["addr2"],
                                   fields["state"], fields["zip"]) if p)
    return {"name": name or None, "address": address or None,
            "email": fields["email"], "city": fields["addr2"],
            "state": fields["state"], "zip": fields["zip"]}


def do_list_hxc(args):
    """Never connects to the node; only the export directory is read
    and the addressee details are fetched from QRZ."""
    rows = find_hxc(args.export_dir)
    scanned = len(exported_ids(args.export_dir))
    log.info("list-hxc: %d HXC radiogram(s) in the %d message file(s) "
             "under %s", len(rows), scanned, args.export_dir)
    if not rows:
        print(f"no HXC radiograms in the {scanned} message file(s) "
              f"under {args.export_dir}")
        return 0

    # The service reply goes to the originating station and quotes the
    # originator's radiogram number, so group the numbers by origin.
    by_origin = {}
    for _, nr, _, origin, _ in rows:
        by_origin.setdefault(origin, set()).add(nr)

    out_path = args.out or os.path.join(args.export_dir, "hxc_list.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"radiograms requesting a delivery confirmation (HXC), "
                f"found in {args.export_dir}, generated {dt.date.today()}\n"
                f"\nradiogram numbers by originating station:\n")
        for origin in sorted(by_origin):
            f.write(f"  {origin}: "
                    + " ".join(str(n) for n in sorted(by_origin[origin]))
                    + "\n")
        f.write("\ndetail (BBS message, preamble):\n")
        for bbs_id, _, _, _, line in rows:
            f.write(f"  msg_{bbs_id}  {line}\n")

    # The addressee details come from QRZ; the preamble only carries
    # the callsign. Shares extract_emails.py's client and credentials.
    qrz = None
    if not args.no_qrz:
        try:
            import extract_emails
        except ImportError:
            raise RuntimeError(
                "QRZ lookups need extract_emails.py next to bpq_admin.py "
                "(or run with --no-qrz)")
        password = args.qrz_password or getpass.getpass(
            f"QRZ password for {args.qrz_user}: ")
        try:
            qrz = extract_emails.Qrz(args.qrz_user, password)
        except extract_emails.QrzError as exc:
            raise RuntimeError(f"QRZ login failed: {exc}")

    # One confirmation draft per originating station. Distinct random
    # message numbers, so two drafts from the same run never collide.
    replies_dir = os.path.join(args.export_dir, "hxc_replies")
    os.makedirs(replies_dir, exist_ok=True)
    today = dt.date.today()
    reply_nrs = random.sample(range(10000, 100000), len(by_origin))
    incomplete = []
    for nr, origin in zip(reply_nrs, sorted(by_origin)):
        contact = {}
        if qrz:
            try:
                contact = qrz_contact(qrz, origin)
            except extract_emails.QrzError as exc:
                log.warning("list-hxc: QRZ lookup of %s failed: %s",
                            origin, exc)
                print(f"warning: QRZ lookup of {origin} failed: {exc}",
                      file=sys.stderr)
        # A missing email drops its line entirely; any other missing
        # field leaves a placeholder to fill in.
        if not all(contact.get(k)
                   for k in ("name", "address", "city", "state", "zip")):
            incomplete.append(origin)
        # Windows-safe: a portable call like W2PAX/4 must not become a path.
        path = os.path.join(replies_dir,
                            f"reply_{origin.replace('/', '-')}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(hxc_reply_text(nr, origin, sorted(by_origin[origin]),
                                   today, contact))
        log.info("list-hxc: wrote confirmation draft %s", path)

    for origin in sorted(by_origin):
        print(f"{origin}: "
              + " ".join(str(n) for n in sorted(by_origin[origin])))
    log.info("list-hxc: wrote %s", out_path)
    print(f"{len(rows)} HXC radiogram(s) from {len(by_origin)} station(s) "
          f"written to {out_path}")
    print(f"{len(by_origin)} confirmation draft(s) written to {replies_dir}")
    if incomplete:
        print("placeholders left to fill in by hand: "
              + " ".join(incomplete))
    return 0


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


def find_stale(session, days):
    """Traffic messages in LTN that are `days` or more days old, as
    (cutoff_date, [(msg_id, listing_line), ...]). Read-only on the BBS -
    it only lists, never reads with R."""
    today = dt.date.today()
    cutoff = today - dt.timedelta(days=days)
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
    return cutoff, stale


def find_stuck_private(session):
    """New private messages in LPN, as [(msg_id, listing_line), ...].
    Nothing forwards these on - they sit on the BBS until the sysop
    deals with them - so every one is worth a notice. SYSTEM
    Housekeeping Results are left out: clean-housekeeping owns those,
    and they would otherwise crowd out the real mail. Read-only."""
    listing = session.bbs_command("LPN")
    housekeeping = set(housekeeping_ids(listing))

    stuck = []
    for line in listing.splitlines():
        m = PRIVATE_LINE_RE.match(line)
        if m and int(m.group(1)) not in housekeeping:
            stuck.append((int(m.group(1)), line.rstrip()))
    return stuck


def do_export_stale(session, args):
    cutoff, stale = find_stale(session, args.days)
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
                f"exported {dt.date.today()}\n\n")
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


def do_check_routing(session, args):
    # --senders audits the full LT history to find repeat offenders;
    # the default checks only the new traffic in LTN.
    command = "LT" if args.senders else "LTN"
    listing = session.bbs_command(command)

    rows = []  # (msg_id, header, sender, ok, listing_line)
    for line in listing.splitlines():
        m = TRAFFIC_FIELDS_RE.match(line)
        if not m:
            continue
        header = m.group(2) + (m.group(3) or "")
        ok = bool(args.route_re.fullmatch(header))
        rows.append((m.group(1), header, m.group(4), ok, line.rstrip()))
        if not ok:
            log.warning("msg %s from %s has unroutable To header %r",
                        m.group(1), m.group(4), header)

    checked = len(rows)
    bad = [row for row in rows if not row[3]]
    log.info("%s: checked %d traffic message(s), %d with a bad To header",
             command, checked, len(bad))

    if args.senders:
        return sender_report(rows, args.show_all)

    if args.show_all:
        for msg_id, header, _, ok, _ in rows:
            print(f"{msg_id:>6}  {'OK ' if ok else 'BAD'}  {header}")
        if rows:
            print()
    if not bad:
        print(f"all {checked} traffic messages have a proper To header")
        return 0
    if not args.show_all:
        for msg_id, header, _, _, line in bad:
            print(line)
            print(f"    msg {msg_id}: To reads {header!r} - expected "
                  f"13743@NTSNY (US) or B0W2J0@NTSNS (Canada)")
        print()
    print(f"{len(bad)} of {checked} traffic message(s) will not be "
          f"routed properly")
    return 1


def sender_report(rows, show_all):
    """Per-sender bad-header summary over the scanned messages."""
    stats = {}
    for msg_id, header, sender, ok, _ in rows:
        entry = stats.setdefault(sender, {"bad": 0, "total": 0, "eg": []})
        entry["total"] += 1
        if not ok:
            entry["bad"] += 1
            if len(entry["eg"]) < 3:
                entry["eg"].append(f"{header} (msg {msg_id})")

    offenders = {s: e for s, e in stats.items() if e["bad"]}
    shown = stats if show_all else offenders
    if shown:
        width = max([len(s) for s in shown] + [len("SENDER")])
        print(f"{'SENDER':<{width}}  {'BAD':>4}  {'TOTAL':>5}  EXAMPLES")
        for sender, entry in sorted(shown.items(),
                                    key=lambda kv: (-kv[1]["bad"],
                                                    -kv[1]["total"], kv[0])):
            print(f"{sender:<{width}}  {entry['bad']:>4}  "
                  f"{entry['total']:>5}  {', '.join(entry['eg'])}")
        print()

    bad_total = sum(e["bad"] for e in stats.values())
    print(f"{len(offenders)} of {len(stats)} sender(s) have created bad "
          f"headers ({bad_total} of {len(rows)} message(s))")
    return 1 if offenders else 0


# ------------------------------------------------------------ notifications

def channels_from_env(parser):
    """The notification channels fully configured in the environment, as
    (name, config) pairs. Partial configuration is an error, not a silent
    skip; so is no channel at all."""
    env = os.environ.get
    channels = []

    webhook = env("BPQ_NOTIFY_DISCORD_WEBHOOK")
    if webhook:
        channels.append(("discord", {"webhook": webhook}))

    token = env("BPQ_NOTIFY_TELEGRAM_TOKEN")
    chat = env("BPQ_NOTIFY_TELEGRAM_CHAT")
    if token or chat:
        if not (token and chat):
            parser.error("telegram is partially configured: set both "
                         "BPQ_NOTIFY_TELEGRAM_TOKEN and "
                         "BPQ_NOTIFY_TELEGRAM_CHAT")
        channels.append(("telegram", {"token": token, "chat": chat}))

    smtp = {name: env("BPQ_SMTP_" + name, "")
            for name in ("HOST", "PORT", "USER", "PASSWORD", "FROM", "TO")}
    if any(smtp.values()):
        missing = ["BPQ_SMTP_" + name for name in ("HOST", "FROM", "TO")
                   if not smtp[name]]
        if smtp["USER"] and not smtp["PASSWORD"]:
            missing.append("BPQ_SMTP_PASSWORD")
        if missing:
            parser.error("email is partially configured: missing "
                         + ", ".join(missing))
        if smtp["PORT"] and not smtp["PORT"].isdigit():
            parser.error(f"invalid BPQ_SMTP_PORT {smtp['PORT']!r}: "
                         "must be a number")
        channels.append(("email", smtp))

    if not channels:
        parser.error(
            "no notification channel configured: set "
            "BPQ_NOTIFY_DISCORD_WEBHOOK, BPQ_NOTIFY_TELEGRAM_TOKEN + "
            "BPQ_NOTIFY_TELEGRAM_CHAT, and/or BPQ_SMTP_HOST/FROM/TO "
            "(see docs/stale-notifier-spec.md)")
    return channels


def http_post(url, data, headers):
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=15.0) as response:
        return response.status, response.read()


def send_discord(webhook, text):
    body = json.dumps({"content": text}).encode("utf-8")
    status, _ = http_post(webhook, body,
                          {"Content-Type": "application/json"})
    if status not in (200, 204):
        raise RuntimeError(f"discord returned HTTP {status}")


def send_telegram(token, chat, text):
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    status, payload = http_post(
        url, body, {"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200 or b'"ok":true' not in payload.replace(b" ", b""):
        raise RuntimeError(f"telegram returned HTTP {status}: "
                           f"{payload[:200].decode('utf-8', 'replace')}")


def send_email(cfg, subject, body_text):
    message = email.message.EmailMessage()
    message["From"] = cfg["FROM"]
    message["To"] = cfg["TO"]
    message["Subject"] = subject
    message.set_content(body_text)
    with smtplib.SMTP(cfg["HOST"], int(cfg["PORT"] or 587),
                      timeout=30) as relay:
        relay.ehlo()
        if relay.has_extn("starttls"):
            relay.starttls()
            relay.ehlo()
        elif cfg["USER"]:
            raise RuntimeError("relay does not offer STARTTLS; refusing "
                               "to send credentials in the clear")
        if cfg["USER"]:
            relay.login(cfg["USER"], cfg["PASSWORD"])
        relay.send_message(message)


def render_notice(sections, limit, fence=False):
    """Render (header, lines) sections - stale traffic, then stuck
    private mail - into a notice of at most `limit` characters. When it
    does not fit, whole listing lines are dropped from the longest
    section, each shortened section ending with its own '...and N more'
    marker, so neither kind of message can be silently squeezed out by
    the other. `fence` wraps each listing in a Discord code fence."""
    kept = [list(lines) for _, lines in sections]
    while True:
        blocks = []
        for (header, lines), keep in zip(sections, kept):
            block = [header]
            if keep:
                block += (["```"] + keep + ["```"]) if fence \
                    else [""] + keep
            if len(keep) != len(lines):
                block.append(f"...and {len(lines) - len(keep)} more")
            blocks.append("\n".join(block))
        text = "\n\n".join(blocks)
        longest = max(range(len(kept)), key=lambda i: len(kept[i]))
        if len(text) <= limit or not kept[longest]:
            return text
        kept[longest].pop()


def do_notify_stale(session, args):
    cutoff, stale = find_stale(session, args.days)
    stuck = find_stuck_private(session)
    # Close the node link before any network sends - a slow webhook must
    # not hold the BBS session open.
    session.logout()
    session.close()

    count, stuck_count = len(stale), len(stuck)
    log.info("LTN: %d stale traffic message(s) dated on or before %s",
             count, cutoff)
    log.info("LPN: %d new private message(s) not forwarding", stuck_count)
    if not stale and not stuck and not args.heartbeat:
        print("0 stale traffic messages, 0 new private messages - "
              "nothing to send")
        return 0

    plural = "" if count == 1 else "s"
    stuck_plural = "" if stuck_count == 1 else "s"
    summary = (f"{count} stale traffic message{plural}, "
               f"{stuck_count} new private message{stuck_plural}")
    sections = [
        (f"{count} stale traffic message{plural} on {args.host} "
         f"(older than {args.days} days)",
         [line for _, line in stale]),
        (f"{stuck_count} new private message{stuck_plural} on {args.host} "
         f"(not forwarding)",
         [line for _, line in stuck]),
    ]

    failures = []
    for name, cfg in args.channels:
        print(f"sending notice to {name} ...", file=sys.stderr)
        log.info("sending notice to %s", name)
        try:
            if name == "discord":
                send_discord(cfg["webhook"],
                             render_notice(sections, 2000, fence=True))
            elif name == "telegram":
                send_telegram(cfg["token"], cfg["chat"],
                              render_notice(sections, 4096))
            else:
                send_email(cfg, f"[BPQ] {summary} on {args.host}",
                           render_notice(sections, sys.maxsize))
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(name)
            log.warning("notice to %s failed: %s", name, exc)
            print(f"notice to {name} FAILED: {exc}", file=sys.stderr)
        else:
            log.info("notice sent to %s (%s)", name, summary)
            print(f"notice sent to {name}")

    print(f"sent to {len(args.channels) - len(failures)} of "
          f"{len(args.channels)} channel(s); {summary}")
    return 1 if failures else 0


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
    sub.add_parser("list-held", parents=[common],
                   help="list held messages (LH)")
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
    stale.add_argument("--days", type=positive_int, default=3, metavar="N",
                       help="a message N or more days old is stale "
                            "(default 3)")
    stale.add_argument("--out", dest="out_dir", default=".", metavar="DIR",
                       help="parent directory in which the per-run "
                            "stale-YYYYMMDD-HHMMSS folder is created "
                            "(default: current directory)")
    killx = sub.add_parser(
        "kill-exported", parents=[common],
        help="kill the messages whose msg_<id>.txt files are in an "
             "export directory")
    killx.add_argument("--dir", dest="export_dir", required=True,
                       metavar="DIR",
                       help="export directory containing the msg_<id>.txt "
                            "files of the processed messages")
    killx.add_argument("--dry-run", action="store_true",
                       help="print the message IDs that would be killed, "
                            "without connecting to the node")
    hxc = sub.add_parser(
        "list-hxc", parents=[common],
        help="list the exported radiograms that ask for a delivery "
             "confirmation (HXC), grouped by originating station, and "
             "draft a confirmation per station (addressee filled in "
             "from QRZ); never connects to the node")
    hxc.add_argument("--dir", dest="export_dir", required=True,
                     metavar="DIR",
                     help="export directory containing the msg_<id>.txt "
                          "files to scan")
    hxc.add_argument("--out", default=None, metavar="FILE",
                     help="write the list to this file (default: "
                          "hxc_list.txt inside --dir)")
    hxc.add_argument("--qrz-user", default=os.environ.get("QRZ_USER"),
                     help="QRZ.com username, for filling each draft's "
                          "name/address/email (or set QRZ_USER)")
    hxc.add_argument("--qrz-password",
                     default=os.environ.get("QRZ_PASSWORD"),
                     help="QRZ.com password (or set QRZ_PASSWORD; prompted "
                          "for if a user is given without one)")
    hxc.add_argument("--no-qrz", action="store_true",
                     help="skip QRZ lookups and leave the name/address/"
                          "email placeholders in each draft")
    notify = sub.add_parser(
        "notify-stale", parents=[common],
        help="send a stale-traffic and stuck-private-mail notice to the "
             "Discord/Telegram/email channels configured in the "
             "environment")
    notify.add_argument("--days", type=positive_int, default=3, metavar="N",
                        help="a traffic message N or more days old is stale "
                             "(default 3); private mail is reported as soon "
                             "as it appears, whatever its age")
    notify.add_argument("--heartbeat", action="store_true", default=True,
                        help="send a notice even when there is nothing to "
                             "report, so a silent notifier can be told from "
                             "a dead one (default: on)")
    notify.add_argument("--no-heartbeat", dest="heartbeat",
                        action="store_false",
                        help="stay silent when there is nothing to report")
    check = sub.add_parser(
        "check-routing", parents=[common],
        help="report LTN traffic messages whose To header will not route "
             "(not of the form 13743@NTSNY)")
    check.add_argument("--pattern", default=None,
                       help="regex a routable To header must fully match, "
                            "case-insensitively (default: a 5-digit zip "
                            "@NTS + a real US state/territory, or a "
                            "Canadian postal code @NTS + a real province)")
    check.add_argument("--show-all", action="store_true",
                       help="print every message checked and the routing "
                            "header it carries, not just the offenders "
                            "(with --senders: include clean senders)")
    check.add_argument("--senders", action="store_true",
                       help="scan the full LT history instead of LTN and "
                            "report which senders have created bad headers")
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
    if args.action == "kill-exported":
        # Validate the directory (and satisfy --dry-run) before requiring
        # credentials or touching the node - a preview is filesystem-only.
        try:
            ids = exported_ids(args.export_dir)
        except RuntimeError as exc:
            parser.error(str(exc))
        if not ids:
            parser.error(f"no msg_<id>.txt files in {args.export_dir}")
        if args.dry_run:
            print("would kill: " + " ".join(str(i) for i in ids))
            return 0
    if args.action == "list-hxc":
        # Never touches the node: scan, ask QRZ for the addressees,
        # write the list and drafts, and return before any node
        # connection value is required.
        if not args.no_qrz and not args.qrz_user:
            parser.error("no QRZ credentials: set QRZ_USER (and "
                         "QRZ_PASSWORD), pass --qrz-user, or run with "
                         "--no-qrz")
        setup_logging(args.log_file)
        try:
            return do_list_hxc(args)
        except RuntimeError as exc:
            parser.error(str(exc))
    if args.action == "check-routing":
        pattern = args.pattern or DEFAULT_ROUTE_PATTERN
        try:
            args.route_re = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            parser.error(f"invalid --pattern {args.pattern!r}: {exc}")
    if args.action == "notify-stale":
        if args.host and args.host.lower() in ("discord", "telegram", "email"):
            parser.error(
                f"{args.host!r} looks like a channel name, but the "
                "positional argument is the node HOST. Channels are "
                "selected by configuring their environment variables - "
                "every fully-configured channel gets the notice.")
        # Channel misconfiguration must fail before touching the node.
        args.channels = channels_from_env(parser)
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
    actions = {"list": do_list, "list-held": do_list_held,
               "clean-housekeeping": do_clean_housekeeping,
               "run-reports": do_run_reports, "export-stale": do_export_stale,
               "kill-exported": do_kill_exported,
               "notify-stale": do_notify_stale,
               "check-routing": do_check_routing}
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
