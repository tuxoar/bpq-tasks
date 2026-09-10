[← back to README](../README.md)

# Delivery confirmations: `list-hxc`

A radiogram whose preamble carries an **HXC** handling instruction asks
the delivering station to report the date and time of delivery back to
the originating station. When you deliver exported traffic (email or
letter), those originators are still owed a service message.

`list-hxc` scans the `msg_<id>.txt` files in an export directory for
preambles whose HX group contains `C` — plain `HXC`, combined codes like
`HXCG` or `HXCF30`, and separately written groups like `HXC HXG` are all
recognized — and writes the radiogram numbers, grouped by originating
station, to a text file. It never connects to the node: only the export
directory is read, and each originator's name, address, and email are
looked up on the QRZ.com XML API (the same credentials and client as
[`extract_emails.py`](extract-emails.md); `--no-qrz` skips the lookups).

```bash
python bpq_admin.py list-hxc --dir stale-20260910-094311
```

```
AC1AE: 194 197 202 203 204
W2PAX: 3961 3962 3963 3975
WX2DX: 363
10 HXC radiogram(s) from 3 station(s) written to stale-20260910-094311/hxc_list.txt
3 confirmation draft(s) written to stale-20260910-094311/hxc_replies
placeholders left to fill in by hand: WX2DX
```

| Argument | Default | Description |
|---|---|---|
| `--dir DIR` | required | Export directory containing the `msg_<id>.txt` files to scan. |
| `--out FILE` | `hxc_list.txt` inside `--dir` | Where to write the list. |
| `--qrz-user` | `QRZ_USER` env var | QRZ.com username for the addressee lookups. |
| `--qrz-password` | `QRZ_PASSWORD` env var | QRZ.com password; prompted for if a user is given without one. |
| `--no-qrz` | off | Skip QRZ and leave the name/address/email placeholders. |

The output file has two sections: the radiogram numbers grouped by
originating station (the reply goes to that station and quotes that
number), and a detail section mapping each BBS message file to the full
preamble line it matched:

```
radiogram numbers by originating station:
  W2PAX: 3961 3962 3963 3975

detail (BBS message, preamble):
  msg_3298  3962 R HXC W2PAX ARL 24 NAPLES FL AUG 29
```

The numbers are grouped by the **station of origin from the preamble**,
not the BBS `From:` header — traffic is often relayed, and the HXC
confirmation is owed to the originator, not the relay.

## Confirmation drafts

Alongside the list, one confirmation radiogram draft per originating
station is written to `hxc_replies/reply_<callsign>.txt` inside the
export directory:

```
TO: 08053@NTSNJ
SUBJECT: MARLTON W2PAX
NR 25027 R W2QS 14 DEANSBORO NY SEP 10
DAVE SMITH W2PAX
1 MAIN ST MARLTON NJ 08053
DAVE@EXAMPLE.COM
BT
YOUR MSG 3961 3962 3963 3975
DELIVERED VIA EMAIL ON SEP 10 1230 EDT
BT
SHAUN W2QS DTN 2RN SYSOP
```

The draft is uppercased end to end, radiogram style. The two filing
lines at the top come from the same QRZ record: `TO:` is the routable
`zip@NTS<state>` header (zip+4 suffixes and postal-code spaces are
stripped so [`check-routing`](check-routing.md) would accept it), and
`SUBJECT:` is the addressee's city and callsign.

Filled in automatically: a random 5-digit message number (unique within
the run), today's date, the delivery time in EST/EDT (whichever is in
effect), the station's radiogram numbers, the check — the real group
count of the text between the `BT`s — and the addressee's name, one-line
address, and email from their QRZ record. A name or address QRZ does not
carry stays a `<FULL NAME>` / `<ONE LINE ADDRESS>` placeholder, and the
summary line names the stations still needing hand-editing; a missing or
unpublished email simply drops the email line — no placeholder. A failed
lookup warns and falls back rather than aborting the run. The
origin station, place, and signature come from the `REPLY_ORIGIN`,
`REPLY_PLACE`, and `REPLY_SIGNATURE` constants at the top of
`bpq_admin.py`.

Sending these back onto the node automatically is planned as a
follow-on feature.

## Fitting into the stale-traffic workflow

Run it after [`export-stale`](stale-traffic.md#export-stale) and before
[`kill-exported`](stale-traffic.md#kill-exported), alongside
[`extract_emails.py`](extract-emails.md) — once the messages are killed
on the BBS, the export folder is the only record of who asked for a
confirmation.
