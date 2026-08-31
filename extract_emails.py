#!/usr/bin/env python3
"""extract_emails.py - recover recipient email addresses from BPQ/NTS
traffic message exports, optionally enriched from the QRZ.com XML API.

Radiogram bodies spell addresses out phonetically so they survive voice
and CW relay, e.g.

    BOBLANGE01 ATSIGN ICLOUD DOT COM
    M DOT E DOT PIATTI AT SIGN GMAIL DOT COM

This walks a directory of msg_*.txt exports, decodes those spellings back
into normal addresses, and prints one row per message.

The addressee is the first line of the address block, which follows the
preamble line, e.g.

    NR 751221 R HXCF 11 W2PAX ARL 15 NAPLES FL JULY 7   <- preamble
    MICHAEL PIATTI  N2MEP                               <- addressee

so the trailing callsign on that line (N2MEP) is the recipient. The
callsign in the preamble is the originating station and is never used.

With QRZ enabled (the default when credentials are available) every
recipient callsign is looked up regardless of whether the message
already carried an address, so a QRZ address that differs from the one
sent in the traffic is surfaced rather than hidden.

Usage:
    python extract_emails.py stale-20260831-083709
    python extract_emails.py stale-20260831-083709 --qrz-user N0CALL
    python extract_emails.py stale-20260831-083709 --no-qrz

Credentials can come from environment variables so they are not captured
in shell history or the process list: QRZ_USER, QRZ_PASSWORD.
Command-line arguments take precedence; a missing password is prompted
for. A QRZ XML Logbook Data subscription is required, and QRZ only
returns an email address when the licensee has chosen to publish it.
"""

import argparse
import datetime as dt
import getpass
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

AGENT = "bpq-tasks-extract-emails/1.0"
QRZ_URL = "https://xmldata.qrz.com/xml/current/"
QRZ_NS = "{http://xmldata.qrz.com}"

# ---------------------------------------------------------------- parsing

# Header keys from the export wrapper, and from the mail header some
# messages carry inline. Their values hold BBS/routing addresses that look
# like email but are not, so these lines are dropped before matching.
HEADER_RE = re.compile(
    r"^\s*(from|to|type/status|type|date/time|date|bid|title|body|mbo|subject"
    r"|content-[\w-]+)\s*:",
    re.IGNORECASE,
)

# Routing trace: "R:260706/0032Z 13013@KY2D.#LINC.ME.USA.NOAM BPQ6.0.24"
TRACE_RE = re.compile(r"^\s*R:\d")

END_RE = re.compile(r"^\s*\[End of Message")

# Preamble: optional NR, message number, precedence, then the rest.
#   NR 751221 R HXCF 11 W2PAX ARL 15 NAPLES FL JULY 7
#   3870 R HXC W2PAX ARL 24 NAPLES FL JUL 5
PREAMBLE_RE = re.compile(r"^\s*(?:NR\s+)?\d+\s+[RWPE]\b", re.IGNORECASE)

# Prosigns and separators that can sit between the preamble and the address.
SEPARATOR_RE = re.compile(r"^\s*(BT|AR|NNNN|AA)?\s*$", re.IGNORECASE)

# A callsign: one or two letters, a digit, then a one-to-four letter suffix.
CALLSIGN_RE = re.compile(r"\b([A-Z]{1,2}[0-9][A-Z]{1,4})\b")

# Spoken-form substitutions, applied in order. Longest forms first so that
# "AT SIGN" is consumed before the bare "AT" rule can touch it.
SPOKEN = [
    (re.compile(r"\bAT[\s-]?SIGN\b", re.IGNORECASE), "@"),
    (re.compile(r"\bATSIGN\b", re.IGNORECASE), "@"),
    (re.compile(r"\bAT\b", re.IGNORECASE), "@"),
    (re.compile(r"\bDOT\b", re.IGNORECASE), "."),
    (re.compile(r"\bUNDERSCORE\b|\bUNDERLINE\b", re.IGNORECASE), "_"),
    (re.compile(r"\bDASH\b|\bHYPHEN\b", re.IGNORECASE), "-"),
]

# Noise words that introduce the address on its own line ("EMAL" is a typo
# that occurs in the traffic).
LEAD_NOISE_RE = re.compile(r"^\s*(E\s?MAIL|EMAL)\b[:\s]*", re.IGNORECASE)

ADDRESS_RE = re.compile(
    r"(?<![\w.@+-])"
    r"([A-Za-z0-9][A-Za-z0-9._%+-]*)"
    r"\s*@\s*"
    r"([A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,24})"
    r"(?![\w@-])"
)

# Pseudo-TLDs from the packet radio hierarchical addressing scheme.
BBS_TLDS = {"noam", "usa", "eura", "asia", "soam", "afri", "aunz", "mdrs", "ampr"}


def body_lines(text):
    """The message body: everything bar routing traces, embedded headers
    and the export footer."""
    kept = []
    for line in text.splitlines():
        if TRACE_RE.match(line) or HEADER_RE.match(line):
            continue
        if END_RE.match(line):
            break
        kept.append(line)
    return kept


def decode(line):
    """Turn one spoken-form line into something an email regex can read."""
    out = LEAD_NOISE_RE.sub("", line)
    for pattern, repl in SPOKEN:
        out = pattern.sub(repl, out)
    # The spoken words were whitespace-separated, so the punctuation they
    # became is too: "M . E . PIATTI @ GMAIL . COM" -> "M.E.PIATTI@GMAIL.COM".
    return re.sub(r"\s*([@._-])\s*", r"\1", out)


def plausible(local, domain):
    if "#" in domain or ".." in domain:
        return False
    return bool(local) and domain.rsplit(".", 1)[-1].lower() not in BBS_TLDS


def find_address(lines):
    """The email address spelled out in the body, if any."""
    for line in lines:
        if "@" not in line and not re.search(r"\bAT\b|\bATSIGN\b", line, re.IGNORECASE):
            continue
        for match in ADDRESS_RE.finditer(decode(line)):
            local, domain = match.group(1), match.group(2)
            if plausible(local, domain):
                return f"{local}@{domain}".lower()
    return None


def find_recipient(lines):
    """The addressee's callsign: the trailing callsign on the first line of
    the address block, which is the first real line after the preamble."""
    for index, line in enumerate(lines):
        if not PREAMBLE_RE.match(line):
            continue
        for candidate in lines[index + 1:]:
            if SEPARATOR_RE.match(candidate):
                continue
            calls = CALLSIGN_RE.findall(candidate.upper())
            return calls[-1] if calls else None
    return None


# ------------------------------------------------------------------- qrz

class QrzError(Exception):
    pass


class Qrz:
    """Minimal QRZ.com XML API client: log in once, then look up callsigns."""

    def __init__(self, username, password, timeout=15.0, delay=0.5):
        self.timeout = timeout
        self.delay = delay
        self.cache = {}
        self.last_call = 0.0
        self.key = self._login(username, password)

    def _get(self, params):
        url = QRZ_URL + "?" + urllib.parse.urlencode(params)
        wait = self.delay - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                payload = response.read()
        except OSError as exc:
            raise QrzError(f"QRZ request failed: {exc}") from exc
        finally:
            self.last_call = time.monotonic()
        try:
            return ET.fromstring(payload)
        except ET.ParseError as exc:
            raise QrzError(f"QRZ returned unparseable XML: {exc}") from exc

    @staticmethod
    def _fields(root, tag):
        node = root.find(QRZ_NS + tag)
        if node is None:
            return {}
        return {child.tag.replace(QRZ_NS, ""): (child.text or "").strip()
                for child in node}

    def _login(self, username, password):
        session = self._fields(
            self._get({"username": username, "password": password, "agent": AGENT}),
            "Session")
        if not session.get("Key"):
            raise QrzError(session.get("Error") or "QRZ login failed (no session key)")
        if session.get("SubExp", "").lower().startswith("non-sub"):
            print("warning: this QRZ account is a non-subscriber; the XML "
                  "service will not return full records (including email).",
                  file=sys.stderr)
        return session["Key"]

    def email(self, callsign):
        """The published email address for a callsign, or None.

        Returns None both when QRZ has no record and when the record has no
        public email; the two are distinguished on stderr.
        """
        if callsign in self.cache:
            return self.cache[callsign]
        root = self._get({"s": self.key, "callsign": callsign})
        session = self._fields(root, "Session")
        error = session.get("Error", "")
        if error:
            if "not found" in error.lower():
                self.cache[callsign] = None
                return None
            raise QrzError(error)
        address = self._fields(root, "Callsign").get("email") or None
        self.cache[callsign] = address.lower() if address else None
        return self.cache[callsign]


# ------------------------------------------------------------------ main

def classify(msg_email, qrz_email, callsign):
    if msg_email and qrz_email:
        return "SAME" if msg_email == qrz_email else "DIFFERS"
    if qrz_email:
        return "ADDED"
    if msg_email:
        return "MSG ONLY"
    return "NO CALLSIGN" if not callsign else "NONE"


# Statuses a human has to do something about, and why.
ACTIONS = {
    "DIFFERS": "QRZ address differs from the one in the traffic - confirm which to use",
    "ADDED": "address recovered from QRZ - not present in the traffic",
    "NONE": "no address in the traffic, and none found for the callsign",
    "NO CALLSIGN": "no callsign in the address block - cannot be looked up",
}


def build_report(rows, queried, directory):
    """The full human-readable report, as a list of lines."""
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    width = max([len(r[2] or "") for r in rows] + [len("FROM MESSAGE")])
    out = [
        f"=== extract_emails {stamp} ===",
        f"source: {os.path.abspath(directory)}",
        f"QRZ:    {'queried' if queried else 'not queried (--no-qrz)'}",
        "",
        f"{'MSG':>6}  {'CALL':<7} {'FROM MESSAGE':<{width}}  "
        f"{'FROM QRZ':<{width}}  STATUS",
    ]
    for msg_id, callsign, msg_email, qrz_email, status in rows:
        if qrz_email:
            qrz_cell = qrz_email
        elif not queried:
            qrz_cell = "not queried"
        elif not callsign:
            # Distinct from "-": QRZ was up, but there was no callsign to ask about.
            qrz_cell = "no callsign"
        else:
            qrz_cell = "-"
        out.append(f"{msg_id:>6}  {callsign or '-':<7} {msg_email or 'NONE':<{width}}  "
                   f"{qrz_cell:<{width}}  {status}")

    counts = {}
    for row in rows:
        counts[row[4]] = counts.get(row[4], 0) + 1
    resolved = sum(1 for r in rows if r[2] or r[3])
    out += ["",
            f"{resolved} of {len(rows)} messages have an address  "
            + "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))]

    for status, why in ACTIONS.items():
        flagged = [r for r in rows if r[4] == status]
        if flagged:
            out += ["", f"{status} ({len(flagged)}) - {why}"]
            for msg_id, callsign, msg_email, qrz_email, _ in flagged:
                detail = ""
                if status == "DIFFERS":
                    detail = f"  traffic={msg_email}  qrz={qrz_email}"
                elif status == "ADDED":
                    detail = f"  {qrz_email}"
                out.append(f"    msg {msg_id}  {callsign or '(no callsign)'}{detail}")
    return out


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", nargs="?", default=".",
                        help="directory of msg_*.txt exports (default: cwd)")
    parser.add_argument("--qrz-user", default=os.environ.get("QRZ_USER"),
                        help="QRZ.com username (or set QRZ_USER)")
    parser.add_argument("--qrz-password", default=os.environ.get("QRZ_PASSWORD"),
                        help="QRZ.com password (or set QRZ_PASSWORD; prompted "
                             "for if a user is given without one)")
    parser.add_argument("--no-qrz", action="store_true",
                        help="parse the messages only, skip QRZ lookups")
    parser.add_argument("--log-file", default="extract_emails.log",
                        help="append the report to this file for later reading "
                             "(default: %(default)s; --log-file '' to disable)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="write only to the log file, not to stdout")
    args = parser.parse_args()

    names = sorted(n for n in os.listdir(args.directory)
                   if re.fullmatch(r"msg_\d+\.txt", n))
    if not names:
        sys.exit(f"no msg_*.txt files found in {args.directory}")

    qrz = None
    if not args.no_qrz:
        if not args.qrz_user:
            sys.exit("no QRZ credentials: set QRZ_USER (and QRZ_PASSWORD), pass "
                     "--qrz-user, or run with --no-qrz")
        password = args.qrz_password or getpass.getpass(
            f"QRZ password for {args.qrz_user}: ")
        try:
            qrz = Qrz(args.qrz_user, password)
        except QrzError as exc:
            sys.exit(f"QRZ login failed: {exc}")

    rows, warnings = [], []
    for name in names:
        with open(os.path.join(args.directory, name),
                  encoding="utf-8", errors="replace") as handle:
            lines = body_lines(handle.read())
        msg_id = re.search(r"\d+", name).group()
        callsign = find_recipient(lines)
        msg_email = find_address(lines)

        qrz_email = None
        if qrz and callsign:
            try:
                qrz_email = qrz.email(callsign)
            except QrzError as exc:
                warnings.append(f"warning: msg {msg_id} {callsign}: {exc}")
                print(warnings[-1], file=sys.stderr)
        rows.append((msg_id, callsign, msg_email, qrz_email,
                     classify(msg_email, qrz_email, callsign)))

    report = build_report(rows, qrz is not None, args.directory)
    if warnings:
        report += [""] + warnings

    if not args.quiet:
        print("\n".join(report))
    if args.log_file:
        with open(args.log_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(report) + "\n\n")
        if not args.quiet:
            print(f"\nreport appended to {os.path.abspath(args.log_file)}")


if __name__ == "__main__":
    main()
