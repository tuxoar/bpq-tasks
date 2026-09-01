[← back to README](../README.md)

# Listing messages: `list` and `list-held`

Two read-only actions for a quick look at what's on the BBS. Both take
only the [common arguments](configuration.md) — no options of their own.

## `list`

Runs `LPN` and prints your private new messages:

```bash
python bpq_admin.py list mynode.example.com --user N0CALL
```

```
Connected to mynode.example.com:8010
Logged in, entering BBS...
BBS login successful (prompt 'de N0CALL>')
running LPN ...
3309   31-Aug PN      22 W2QS   @W2QS   W2QS   test
```

## `list-held`

Runs `LH` and prints every held message — traffic the BBS is holding back
from forwarding:

```bash
python bpq_admin.py list-held mynode.example.com --user N0CALL
```

Both actions only list; nothing is read, killed, or marked. To act on what
you see, reach for the task-specific actions:
[`clean-housekeeping`](clean-housekeeping.md) for housekeeping reports,
the [stale-traffic workflow](stale-traffic.md) for old traffic.
