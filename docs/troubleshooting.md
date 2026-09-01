[← back to README](../README.md)

# Troubleshooting

**It hangs, then reports "never saw a login prompt".** Run with
`--verbose` to see exactly what the node sent. The script recognizes login
prompts containing `user:`, `callsign:`, or `login:` and password prompts
containing `password:` (case-insensitive) — BPQ's defaults. If your
`bpq32.cfg` uses custom `LOGINPROMPT`/`PASSWORDPROMPT` values, adjust the
`LOGIN_PROMPTS`/`PASSWORD_PROMPTS` tuples near the top of `bpq_admin.py`.

**Listings seem cut short.** If your BBS user has paging enabled, long
listings may pause mid-output. Disable paging for the account the script
logs in as.

**`python` isn't found.** Use `python3` (macOS/Linux) or `py` (Windows),
and see [Getting started](getting-started.md).

**Every QRZ lookup comes back empty.** Almost always the subscription: the
XML Logbook Data service returns full records only to subscribers. The
script warns on stderr when QRZ reports the account as a non-subscriber.
Check also that the callsigns in the `CALL` column are the ones you expect
— a message whose address block omits the callsign shows `no callsign` and
is never looked up.

**A recovered address looks wrong.** Compare it against the message text
with `--no-qrz`. Addresses are transcribed by hand through several relays,
so the traffic itself can carry a typo — a `DIFFERS` row is exactly that
case, and QRZ is usually, though not always, the better source.

Still stuck? [Logging](logging.md) explains what each script records and
where; `--verbose` on any `bpq_admin.py` action dumps the full session
transcript to stderr.
