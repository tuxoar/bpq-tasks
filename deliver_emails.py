#!/usr/bin/env python3
"""deliver_emails.py - put the emails in emails.txt into your mailbox as
drafts, or send them, over IMAP/SMTP. Built for Proton Mail Bridge.

extract_emails.py writes emails.txt: one ready-to-send block per radiogram
that has an email address. Until now each block was copied by hand into
the mail client. This script reads that file and, for every block, either

    creates a DRAFT in your mailbox (the default) - review it in the mail
    client and press send there, or
    SENDS it outright (--send).

It speaks plain IMAP (drafts) and SMTP (sending), which is what Proton
Mail Bridge exposes on localhost for a paid Proton account: IMAP on
127.0.0.1:1143 and SMTP on 127.0.0.1:1025, STARTTLS with a self-signed
certificate, username = your Proton address, password = the password
Bridge generates (not your Proton password). With Bridge running, only
BPQ_DELIVER_USER and BPQ_DELIVER_PASSWORD need to be set; every other
value defaults to Bridge's. The same code works against hydroxide
(BPQ_DELIVER_SECURITY=none) or any ordinary IMAP/SMTP account such as
Gmail (BPQ_DELIVER_SECURITY=ssl with the provider's hosts and ports).

emails.txt on disk is the source of truth, so edit it before running -
for instance to pick one of the two addresses on a DIFFERS row. Any block
that does not parse aborts the whole run before anything is connected to,
so a half-edited file cannot be half-delivered.

Every message drafted or sent is recorded in a ledger (delivered.txt in
the export directory) and skipped on later runs, so re-running is safe;
--force redoes them. With --send, a block whose To line carries more than
one address (the traffic and QRZ disagreed) is drafted instead of sent,
so nothing goes out to an address a human has not chosen.

Usage:
    python deliver_emails.py stale-20260919-082944 --dry-run
    python deliver_emails.py stale-20260919-082944            # drafts
    python deliver_emails.py stale-20260919-082944 --send
    python deliver_emails.py --test                           # check the connection

Environment (command-line flags of the same name take precedence):
    BPQ_DELIVER_USER        login - for Bridge, your Proton address (required)
    BPQ_DELIVER_PASSWORD    Bridge-generated password (prompted for if unset)
    BPQ_DELIVER_FROM        From header (default: the user)
    BPQ_DELIVER_IMAP_HOST   default 127.0.0.1     BPQ_DELIVER_IMAP_PORT  default 1143
    BPQ_DELIVER_SMTP_HOST   default 127.0.0.1     BPQ_DELIVER_SMTP_PORT  default 1025
    BPQ_DELIVER_SECURITY    starttls (default) | ssl | none (loopback only)
    BPQ_DELIVER_CA_CERT     PEM file to verify the server certificate against
    BPQ_DELIVER_DRAFTS      Drafts folder name (default: discovered, else "Drafts")

A loopback host with no CA certificate is trusted without verification -
Bridge's certificate is self-signed and the connection never leaves the
machine. Any other host is always verified.
"""

import argparse
import datetime as dt
import email.message
import email.policy
import email.utils
import getpass
import imaplib
import ipaddress
import os
import re
import smtplib
import socket
import ssl
import sys
import time

TIMEOUT = 30.0
ENV_PREFIX = "BPQ_DELIVER_"
SECURITY_MODES = ("starttls", "ssl", "none")
DEFAULTS = {
    "IMAP_HOST": "127.0.0.1", "IMAP_PORT": "1143",
    "SMTP_HOST": "127.0.0.1", "SMTP_PORT": "1025",
    "SECURITY": "starttls",
}
DRAFT_FLAGS = "(\\Draft \\Seen)"

# ---------------------------------------------------------------- parsing

# Block marker written by extract_emails.py: "########## msg 3429 ##########".
# Tolerant of a mangled number of hashes from hand editing.
MARKER_RE = re.compile(r"^#{3,}\s*msg\s+(\d+)\s*#{3,}\s*$", re.IGNORECASE)
HEADER_RE = re.compile(r"^(To|Subject)\s*:\s*(.*)$", re.IGNORECASE)
BODY_RE = re.compile(r"^Body\s*:\s*$", re.IGNORECASE)

# An address as it must look after email.utils has split the To line.
ADDR_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[A-Za-z]{2,}$")

# One IMAP LIST reply: (\HasNoChildren \Drafts) "/" "Drafts"
LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?:"(?P<delim>[^"]*)"|NIL)\s+(?P<name>.+)$')


class DeliveryError(Exception):
    """A connection, login or protocol failure, already worded for people."""


class Block:
    """One email from emails.txt."""
    __slots__ = ("msg_id", "addresses", "subject", "body")

    def __init__(self, msg_id, addresses, subject, body):
        self.msg_id = msg_id
        self.addresses = addresses
        self.subject = subject
        self.body = body

    @property
    def to(self):
        return ", ".join(self.addresses)


def parse_addresses(value):
    """The addresses on a To line, validated and deduplicated in order.
    Raises ValueError naming the first thing that is not an address."""
    if not value.strip():
        raise ValueError("empty To line")
    addresses = []
    for _, addr in email.utils.getaddresses([value]):
        if not addr:
            continue  # a stray comma, e.g. after deleting one of two addresses
        if not ADDR_RE.match(addr):
            raise ValueError(f"not an email address: {addr or value.strip()!r}")
        if addr.lower() not in (a.lower() for a in addresses):
            addresses.append(addr)
    if not addresses:
        raise ValueError(f"no address in To line {value.strip()!r}")
    return addresses


def parse_blocks(text):
    """Every block in an emails.txt, or ValueError listing every problem.

    A block is a marker line, then To: and Subject: lines in any order
    (blank lines ignored), then "Body:" and everything up to the next
    marker. Nothing else is accepted before Body:, so a hand edit that
    breaks a header is reported rather than silently swallowed."""
    blocks, errors, seen = [], [], set()
    current = None
    text = text.lstrip("\ufeff")  # a BOM from Notepad, if the caller kept it

    def finish():
        if current is None:
            return
        msg_id = current["id"]
        where = f"msg {msg_id} (line {current['line']})"
        if msg_id in seen:
            errors.append(f"{where}: duplicate message id")
        seen.add(msg_id)
        problems = []
        addresses = []
        if current["to"] is None:
            problems.append("no To: line")
        else:
            try:
                addresses = parse_addresses(current["to"])
            except ValueError as exc:
                problems.append(str(exc))
        if not (current["subject"] or "").strip():
            problems.append("no Subject: line")
        body = current["body"]
        if body is None:
            problems.append("no 'Body:' line")
        else:
            while body and not body[-1].strip():
                body.pop()
            while body and not body[0].strip():
                body.pop(0)
            if not body:
                problems.append("empty body")
        if problems:
            errors.append(f"{where}: " + "; ".join(problems))
        else:
            blocks.append(Block(msg_id, addresses, current["subject"].strip(),
                                "\n".join(body)))

    for lineno, line in enumerate(text.splitlines(), 1):
        marker = MARKER_RE.match(line)
        if marker:
            finish()
            current = {"id": marker.group(1), "to": None, "subject": None,
                       "body": None, "line": lineno}
            continue
        if current is None:
            if line.strip():
                errors.append(f"line {lineno}: text before the first "
                              f"'########## msg N ##########' marker")
            continue
        if current["body"] is not None:
            current["body"].append(line)
            continue
        if not line.strip():
            continue
        if BODY_RE.match(line):
            current["body"] = []
            continue
        header = HEADER_RE.match(line)
        if header:
            current[header.group(1).lower()] = header.group(2)
            continue
        errors.append(f"msg {current['id']} (line {lineno}): unexpected line "
                      f"before 'Body:': {line.strip()[:60]!r}")
    finish()

    if not blocks and not errors:
        errors.append("no message blocks found")
    if errors:
        raise ValueError("\n".join(errors))
    return blocks


def load_blocks(path):
    try:
        with open(path, encoding="utf-8-sig") as handle:
            text = handle.read()
    except OSError as exc:
        sys.exit(f"cannot read {path}: {exc.strerror}")
    except UnicodeDecodeError as exc:
        sys.exit(f"{path} is not UTF-8 (byte {exc.start}: {exc.reason}) - "
                 "an editor may have saved it as ANSI; re-save as UTF-8 and "
                 "re-run. Nothing was delivered.")
    try:
        return parse_blocks(text)
    except ValueError as exc:
        sys.exit(f"{path} has problems - fix them and re-run; nothing was "
                 f"delivered:\n    " + str(exc).replace("\n", "\n    "))


# ----------------------------------------------------------------- ledger

def read_ledger(path):
    """msg_id -> (action, timestamp, to) for every message already
    delivered; the last line for an id wins."""
    entries = {}
    if not os.path.exists(path):
        return entries
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) >= 3 and parts[1]:
                entries[parts[1]] = (parts[2], parts[0],
                                     parts[3] if len(parts) > 3 else "")
    return entries


def check_ledger_writable(path):
    """Open the ledger for append once, before anything is delivered, so a
    read-only folder or a locked file is found out while it is still
    harmless."""
    existed = os.path.exists(path)
    try:
        with open(path, "a", encoding="utf-8"):
            pass
        if not existed:
            os.remove(path)  # leave nothing behind if the run stops here
    except OSError as exc:
        raise DeliveryError(f"cannot write the ledger {path}: {exc.strerror}") from exc


def record(path, msg_id, action, to):
    stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{stamp}\t{msg_id}\t{action}\t{to}\n")
        handle.flush()


# ------------------------------------------------------------ config, tls

def is_loopback(host):
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip()).is_loopback
    except ValueError:
        return False


def config_from_env(parser, args, need_account):
    """Merge environment and command line (command line wins), validate,
    and prompt for the password when a terminal is available."""
    env = os.environ.get

    def pick(name, cli, default=""):
        return cli if cli is not None else env(ENV_PREFIX + name, default)

    cfg = {
        "USER": pick("USER", args.user),
        "PASSWORD": pick("PASSWORD", args.password),
        "FROM": pick("FROM", args.from_addr),
        "IMAP_HOST": pick("IMAP_HOST", args.imap_host, DEFAULTS["IMAP_HOST"]),
        "IMAP_PORT": pick("IMAP_PORT", args.imap_port, DEFAULTS["IMAP_PORT"]),
        "SMTP_HOST": pick("SMTP_HOST", args.smtp_host, DEFAULTS["SMTP_HOST"]),
        "SMTP_PORT": pick("SMTP_PORT", args.smtp_port, DEFAULTS["SMTP_PORT"]),
        "SECURITY": pick("SECURITY", args.security, DEFAULTS["SECURITY"]).lower(),
        "CA_CERT": pick("CA_CERT", args.ca_cert),
        "DRAFTS": pick("DRAFTS", args.drafts_folder),
    }
    for name in ("IMAP_PORT", "SMTP_PORT"):
        if not str(cfg[name]).isdigit():
            parser.error(f"invalid {ENV_PREFIX}{name} {cfg[name]!r}: must be a number")
    if cfg["SECURITY"] not in SECURITY_MODES:
        parser.error(f"invalid {ENV_PREFIX}SECURITY {cfg['SECURITY']!r}: "
                     f"must be one of {', '.join(SECURITY_MODES)}")
    if cfg["CA_CERT"] and not os.path.isfile(cfg["CA_CERT"]):
        parser.error(f"{ENV_PREFIX}CA_CERT {cfg['CA_CERT']!r}: no such file")
    if cfg["SECURITY"] == "none":
        for host in (cfg["IMAP_HOST"], cfg["SMTP_HOST"]):
            if not is_loopback(host):
                parser.error(f"{ENV_PREFIX}SECURITY=none with host {host!r}: "
                             "refusing to send credentials in the clear to "
                             "anything but this machine")
    if need_account:
        if not cfg["USER"]:
            parser.error(f"no account: set {ENV_PREFIX}USER or pass --user "
                         "(see docs/deliver-emails.md)")
        if not cfg["PASSWORD"]:
            if sys.stdin is None or not sys.stdin.isatty():
                parser.error(f"no password: set {ENV_PREFIX}PASSWORD or pass "
                             "--password (no terminal to prompt on)")
            cfg["PASSWORD"] = getpass.getpass(
                f"mail password for {cfg['USER']} (Bridge's, not Proton's): ")
    if not cfg["FROM"]:
        cfg["FROM"] = cfg["USER"]
    if need_account and "@" not in email.utils.parseaddr(cfg["FROM"])[1]:
        parser.error(f"From address {cfg['FROM']!r} is not a full email "
                     f"address: set {ENV_PREFIX}FROM (the login on this "
                     "server is a bare username)")
    return cfg


def make_ssl_context(host, ca_cert):
    """Verified against ca_cert when given, against the system store for
    any other remote host - and not at all for a loopback host with no
    CA, which is how Bridge's self-signed certificate is accepted."""
    if ca_cert:
        return ssl.create_default_context(cafile=ca_cert)
    context = ssl.create_default_context()
    if is_loopback(host):
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def verification(cfg):
    """How the report describes certificate checking."""
    if cfg["SECURITY"] == "none":
        return "no TLS"
    if cfg["CA_CERT"]:
        return f"{cfg['SECURITY']}, verified against {cfg['CA_CERT']}"
    legs = {name: ("verify off (loopback)" if is_loopback(cfg[name + "_HOST"])
                   else "verified") for name in ("IMAP", "SMTP")}
    if legs["IMAP"] == legs["SMTP"]:
        return f"{cfg['SECURITY']}, {legs['IMAP']}"
    return f"{cfg['SECURITY']}, imap {legs['IMAP']}, smtp {legs['SMTP']}"


# ------------------------------------------------------------------- mail

def describe(exc):
    """An exception's message as text, decoding the bytes imaplib and
    smtplib tend to put in .args."""
    parts = []
    for arg in getattr(exc, "args", ()) or ():
        if isinstance(arg, bytes):
            arg = arg.decode("utf-8", "replace")
        parts.append(str(arg))
    text = " ".join(p for p in parts if p) or exc.__class__.__name__
    return text.strip()


def build_message(block, sender):
    policy = email.policy.SMTP.clone(cte_type="7bit")
    message = email.message.EmailMessage(policy=policy)
    message["From"] = sender
    message["To"] = block.to
    message["Subject"] = block.subject
    message["Date"] = email.utils.formatdate(localtime=True)
    _, sender_addr = email.utils.parseaddr(sender)
    domain = (sender_addr.rsplit("@", 1)[1] if "@" in sender_addr
              else socket.gethostname() or "localhost")
    message["Message-ID"] = email.utils.make_msgid(domain=domain)
    message["X-BPQ-Msg-Id"] = block.msg_id
    message.set_content(block.body + "\n")
    return message


def quote_mailbox(name):
    """An IMAP mailbox name as a command argument. Python 3.8-3.13 pass
    the name through verbatim, so anything beyond plain characters
    ("[Gmail]/Drafts", names with spaces) has to be quoted here; 3.14
    quotes itself but leaves an already-quoted name alone."""
    if re.fullmatch(r"[A-Za-z0-9._/+-]+", name):
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def open_imap(cfg):
    host, port = cfg["IMAP_HOST"], int(cfg["IMAP_PORT"])
    try:
        if cfg["SECURITY"] == "ssl":
            imap = imaplib.IMAP4_SSL(
                host, port, ssl_context=make_ssl_context(host, cfg["CA_CERT"]))
        else:
            imap = imaplib.IMAP4(host, port)
            if cfg["SECURITY"] == "starttls":
                imap.starttls(make_ssl_context(host, cfg["CA_CERT"]))
        imap.login(cfg["USER"], cfg["PASSWORD"])
    except (OSError, imaplib.IMAP4.error) as exc:
        raise DeliveryError(f"imap {host}:{port}: {describe(exc)}") from exc
    return imap


def open_smtp(cfg):
    host, port = cfg["SMTP_HOST"], int(cfg["SMTP_PORT"])
    # smtplib's default EHLO name comes from socket.getfqdn(), a reverse
    # DNS lookup that can stall for seconds; the bare hostname is fine.
    ehlo_name = socket.gethostname() or "localhost"
    try:
        if cfg["SECURITY"] == "ssl":
            smtp = smtplib.SMTP_SSL(
                host, port, local_hostname=ehlo_name, timeout=TIMEOUT,
                context=make_ssl_context(host, cfg["CA_CERT"]))
        else:
            smtp = smtplib.SMTP(host, port, local_hostname=ehlo_name,
                                timeout=TIMEOUT)
            smtp.ehlo()
            if cfg["SECURITY"] == "starttls":
                smtp.starttls(context=make_ssl_context(host, cfg["CA_CERT"]))
                smtp.ehlo()
        smtp.login(cfg["USER"], cfg["PASSWORD"])
    except (OSError, smtplib.SMTPException) as exc:
        raise DeliveryError(f"smtp {host}:{port}: {describe(exc)}") from exc
    return smtp


def find_drafts_folder(imap, override):
    """The Drafts folder: the override if given, else the folder LIST
    flags with \\Drafts (Bridge: "Drafts", Gmail: "[Gmail]/Drafts"), else
    plain "Drafts". Whichever it is, it must SELECT."""
    try:
        typ, rows = imap.list()
    except (OSError, imaplib.IMAP4.error) as exc:
        raise DeliveryError(f"imap LIST failed: {describe(exc)}") from exc
    names, flagged = [], None
    for row in rows or []:
        if not isinstance(row, bytes):
            continue
        match = LIST_RE.match(row.strip())
        if not match:
            continue
        name = match.group("name").decode("utf-8", "replace").strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        names.append(name)
        if flagged is None and b"\\drafts" in match.group("flags").lower():
            flagged = name
    folder = override or flagged or "Drafts"
    try:
        typ, data = imap.select(quote_mailbox(folder), readonly=True)
    except UnicodeError:
        raise DeliveryError(
            f"Drafts folder {folder!r}: names with non-ASCII characters are "
            "not supported - use an ASCII-named folder") from None
    except (OSError, imaplib.IMAP4.error) as exc:
        typ, data = "NO", [describe(exc).encode()]
    if typ != "OK":
        raise DeliveryError(
            f"cannot open Drafts folder {folder!r}: "
            f"{describe(Exception(*(data or [])))}; folders on the server: "
            + (", ".join(names) or "(none listed)")
            + f" - set {ENV_PREFIX}DRAFTS or --drafts-folder")
    return folder


def append_draft(imap, folder, message):
    try:
        typ, data = imap.append(quote_mailbox(folder), DRAFT_FLAGS, time.time(),
                                message.as_bytes())
    except (OSError, UnicodeError, imaplib.IMAP4.error) as exc:
        raise DeliveryError(describe(exc)) from exc
    if typ != "OK":
        raise DeliveryError(f"APPEND to {folder} refused: "
                            f"{describe(Exception(*(data or [])))}")


def send(smtp, message):
    try:
        smtp.send_message(message)
    except smtplib.SMTPRecipientsRefused as exc:
        detail = "; ".join(
            f"{addr}: {code} {describe(Exception(text))}"
            for addr, (code, text) in exc.recipients.items())
        raise DeliveryError(detail or "recipients refused") from exc
    except smtplib.SMTPResponseException as exc:
        raise DeliveryError(
            f"{exc.smtp_code} {describe(Exception(exc.smtp_error))}") from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise DeliveryError(describe(exc)) from exc


def close_quietly(imap, smtp):
    for closer in ((imap.logout if imap else None), (smtp.quit if smtp else None)):
        if closer:
            try:
                closer()
            except Exception:  # noqa: BLE001 - shutting down, nothing to report
                pass


# ------------------------------------------------------------ run, report

def plan_actions(blocks, ledger, send_mode, force, only):
    """(block, action, note) per block: action is draft, send or skip."""
    plan = []
    for block in blocks:
        if only is not None and block.msg_id not in only:
            continue
        done = ledger.get(block.msg_id)
        if done and not force:
            action, stamp, _ = done
            plan.append((block, "skip", f"{action} {stamp[:10]}"))
        elif send_mode and len(block.addresses) == 1:
            plan.append((block, "send", ""))
        elif send_mode:
            plan.append((block, "draft",
                         f"{len(block.addresses)} addresses - not sent"))
        else:
            plan.append((block, "draft", ""))
    return plan


def deliver(plan, cfg, ledger_path, dry_run):
    """Carry out the plan. Rows of (msg_id, to, action, status). Both
    connections are opened and logged in before the first message is
    touched; one message failing never stops the rest."""
    rows = []
    imap = smtp = folder = None
    try:
        if not dry_run and any(a != "skip" for _, a, _ in plan):
            check_ledger_writable(ledger_path)
        if not dry_run and any(a == "draft" for _, a, _ in plan):
            imap = open_imap(cfg)
            folder = find_drafts_folder(imap, cfg["DRAFTS"])
        if not dry_run and any(a == "send" for _, a, _ in plan):
            smtp = open_smtp(cfg)
        for block, action, note in plan:
            suffix = f" ({note})" if note else ""
            if action == "skip":
                rows.append((block.msg_id, block.to, "-", f"SKIPPED{suffix}"))
                continue
            if dry_run:
                rows.append((block.msg_id, block.to, action,
                             f"WOULD {action.upper()}{suffix}"))
                continue
            message = build_message(block, cfg["FROM"])
            try:
                if action == "draft":
                    append_draft(imap, folder, message)
                    done, status = "drafted", "DRAFTED"
                else:
                    send(smtp, message)
                    done, status = "sent", "SENT"
            except DeliveryError as exc:
                rows.append((block.msg_id, block.to, action, f"FAILED: {exc}"))
                continue
            try:
                record(ledger_path, block.msg_id, done, block.to)
            except OSError as exc:
                # The message is out; say so loudly rather than lose it.
                status += f" - NOT RECORDED ({exc.strerror}); add it to the ledger by hand"
            rows.append((block.msg_id, block.to, action, status + suffix))
    finally:
        close_quietly(imap, smtp)
    return rows


def build_report(rows, cfg, mode, source):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    width = max([len(r[1]) for r in rows] + [len("TO")])
    out = [
        f"=== deliver_emails {stamp} ===",
        f"source:  {source}",
        f"mode:    {mode}",
        f"server:  imap {cfg['IMAP_HOST']}:{cfg['IMAP_PORT']}  "
        f"smtp {cfg['SMTP_HOST']}:{cfg['SMTP_PORT']}  {verification(cfg)}",
        f"account: {cfg['USER'] or '(not needed)'}",
    ]
    out += ["", f"{'MSG':>6}  {'TO':<{width}}  ACTION  STATUS"]
    for msg_id, to, action, status in rows:
        out.append(f"{msg_id:>6}  {to:<{width}}  {action:<6}  {status}")

    counts = {}
    for _, _, _, status in rows:
        key = status.split(":")[0].split(" (")[0]
        counts[key] = counts.get(key, 0) + 1
    delivered = sum(1 for r in rows if r[3].startswith(("DRAFTED", "SENT")))
    out += ["", f"{delivered} of {len(rows)} messages delivered  "
            + "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))]

    failed = [r for r in rows if r[3].startswith("FAILED")]
    if failed:
        out += ["", f"FAILED ({len(failed)}) - fix and re-run; delivered "
                "messages are skipped automatically"]
        for msg_id, to, _, status in failed:
            out.append(f"    msg {msg_id}  {to}  {status[len('FAILED: '):]}")
    unrecorded = [r for r in rows if "NOT RECORDED" in r[3]]
    if unrecorded:
        out += ["", f"NOT RECORDED ({len(unrecorded)}) - delivered, but the "
                "ledger could not be written; a re-run would deliver these "
                "again unless you add them to the ledger"]
        for msg_id, to, _, status in unrecorded:
            out.append(f"    msg {msg_id}  {to}")
    redirected = [r for r in rows if "not sent" in r[3]]
    if redirected:
        out += ["", f"DRAFTED instead of sent ({len(redirected)}) - the To "
                "line carries more than one address; pick one in the mail "
                "client, or edit emails.txt and re-run with --force"]
        for msg_id, to, _, _ in redirected:
            out.append(f"    msg {msg_id}  {to}")
    return out


def test_connection(cfg):
    """Log in to both servers and find the Drafts folder. Touches no
    messages. Returns the lines to print."""
    lines = [f"imap {cfg['IMAP_HOST']}:{cfg['IMAP_PORT']} ({verification(cfg)})"]
    imap = smtp = None
    try:
        imap = open_imap(cfg)
        lines[-1] += ": login OK"
        folder = find_drafts_folder(imap, cfg["DRAFTS"])
        lines.append(f"drafts folder: {folder}")
        smtp = open_smtp(cfg)
        lines.append(f"smtp {cfg['SMTP_HOST']}:{cfg['SMTP_PORT']}: login OK")
    finally:
        close_quietly(imap, smtp)
    return lines


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", nargs="?", default=".",
                        help="export directory holding emails.txt (default: cwd)")
    parser.add_argument("--emails-file", default=None,
                        help="read this file instead of DIR/emails.txt")
    parser.add_argument("--send", action="store_true",
                        help="send messages with exactly one To address; "
                             "messages with more become drafts (default: "
                             "draft everything)")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and report what would happen - no "
                             "connection, no credentials, nothing written")
    parser.add_argument("--force", action="store_true",
                        help="redo messages the ledger says were already "
                             "drafted or sent")
    parser.add_argument("--only", action="append", metavar="ID[,ID...]",
                        default=None,
                        help="deliver only these message ids (repeat the "
                             "flag or separate ids with commas)")
    parser.add_argument("--test", action="store_true",
                        help="log in to IMAP and SMTP, report the Drafts "
                             "folder, and exit without touching any message")
    parser.add_argument("--ledger", default=None,
                        help="where delivered messages are recorded "
                             "(default: delivered.txt in DIR)")
    parser.add_argument("--log-file", default="deliver_emails.log",
                        help="append the report to this file "
                             "(default: %(default)s; --log-file '' to disable)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="write only to the log file, not to stdout")

    conn = parser.add_argument_group(
        "connection", f"each overrides the {ENV_PREFIX}* variable of the same name")
    conn.add_argument("--user")
    conn.add_argument("--password", help="prefer the env var or the prompt")
    conn.add_argument("--from", dest="from_addr", metavar="ADDR")
    conn.add_argument("--imap-host")
    conn.add_argument("--imap-port")
    conn.add_argument("--smtp-host")
    conn.add_argument("--smtp-port")
    conn.add_argument("--security", choices=SECURITY_MODES)
    conn.add_argument("--ca-cert", metavar="PEM")
    conn.add_argument("--drafts-folder", metavar="NAME")
    args = parser.parse_args()

    socket.setdefaulttimeout(TIMEOUT)
    cfg = config_from_env(parser, args,
                          need_account=args.test or not args.dry_run)

    if args.test:
        try:
            lines = test_connection(cfg)
        except DeliveryError as exc:
            print(f"connection test failed: {exc}", file=sys.stderr)
            return 1
        print("\n".join(lines))
        return 0

    emails_path = args.emails_file or os.path.join(args.directory, "emails.txt")
    # The ledger lives next to whichever emails.txt is being delivered, so
    # the --emails-file and DIR forms of the same run share it.
    ledger_path = args.ledger or os.path.join(
        os.path.dirname(os.path.abspath(emails_path)), "delivered.txt")
    blocks = load_blocks(emails_path)
    only = None
    if args.only:
        only = {i.strip() for group in args.only for i in group.split(",") if i.strip()}
        unknown = sorted(only - {b.msg_id for b in blocks})
        if unknown:
            sys.exit(f"--only: no such message(s) in {emails_path}: "
                     + ", ".join(unknown))
    try:
        ledger = read_ledger(ledger_path)
    except OSError as exc:
        sys.exit(f"cannot read the ledger {ledger_path}: {exc.strerror}")
    plan = plan_actions(blocks, ledger, args.send, args.force, only)

    mode = "send" if args.send else "drafts"
    if args.dry_run:
        mode += " (dry run)"
    try:
        rows = deliver(plan, cfg, ledger_path, args.dry_run)
    except DeliveryError as exc:
        print(f"nothing delivered: {exc}", file=sys.stderr)
        return 1

    report = build_report(rows, cfg, mode, os.path.abspath(emails_path))
    if not args.quiet:
        print("\n".join(report))
    if args.log_file and not args.dry_run:
        with open(args.log_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(report) + "\n\n")
        if not args.quiet:
            print(f"\nreport appended to {os.path.abspath(args.log_file)}")
    return 1 if any(r[3].startswith("FAILED") or "NOT RECORDED" in r[3]
                    for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
