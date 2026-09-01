[← back to README](../README.md)

# `clean-housekeeping` — clear housekeeping reports

Finds every `SYSTEM Housekeeping Results` message in `LPN` and kills each
one with `K <id>`. Nothing else is touched, and every kill is verified
against the BBS reply.

```bash
# Preview first - prints the IDs it would kill, sends no K commands
python bpq_admin.py clean-housekeeping mynode.example.com --user N0CALL --dry-run

# Actually kill them
python bpq_admin.py clean-housekeeping mynode.example.com --user N0CALL
```

| Argument | Default | Description |
|---|---|---|
| `--dry-run` | off | Print the message IDs that would be killed, then exit without killing anything. Run this first. |

Only lines matching the exact shape
`<id> <date> PN <size> SYSOP SYSTEM Housekeeping Results` are killed — an
ordinary user message, even one mentioning housekeeping in its subject,
cannot match. Any kill the BBS does not confirm is reported and makes the
exit code 1.

Every kill and its confirmation is recorded in the audit log — see
[Logging](logging.md).
