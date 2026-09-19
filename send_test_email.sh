#!/usr/bin/env bash
# send_test_email.sh ADDRESS [--send | --dry-run]
#
# Check deliver_emails.py against your real Bridge with one message to
# an address you own. Builds a one-block emails.txt in a temp folder,
# runs the connection test, then delivers it - as a draft by default,
# sent for real with --send. Source bpq.env first.
set -euo pipefail
cd "$(dirname "$0")"

usage="usage: $0 you@example.com [--send | --dry-run]"
to="${1:?$usage}"
mode="${2:-}"
case "$mode" in
    ""|--send|--dry-run) ;;
    *) echo "$usage" >&2; exit 2 ;;
esac

if [ "$mode" != "--dry-run" ]; then
    if [ -z "${BPQ_DELIVER_USER:-}" ]; then
        echo "BPQ_DELIVER_USER is not set - run 'source bpq.env' first" >&2
        exit 2
    fi
    # Two deliver_emails.py runs follow; prompt once rather than twice.
    if [ -z "${BPQ_DELIVER_PASSWORD:-}" ] && [ -t 0 ]; then
        read -rsp "mail password for $BPQ_DELIVER_USER (Bridge's, not Proton's): " BPQ_DELIVER_PASSWORD
        echo
        export BPQ_DELIVER_PASSWORD
    fi
fi

dir="$(mktemp -d /tmp/deliver-test-XXXXXX)"
trap 'echo; echo "scratch folder: $dir  (holds the test address - rm -r it when done)"' EXIT

cat > "$dir/emails.txt" <<BLOCK
########## msg 1 ##########

To: $to
Subject: deliver_emails.py test

Body: 
This is a test message from deliver_emails.py through Proton Mail Bridge.
If you are reading it, drafting/sending from the script works.

73, Shaun W2QS Region 2 Hub Sysop

====
NR 1 R W2QS 6 DEANSBORO NY $(date +'%b %-d' | tr '[:lower:]' '[:upper:]')
TEST MESSAGE W2QS
BT
THIS IS A TEST X PLEASE IGNORE
BT
SHAUN W2QS
AR
BLOCK

if [ "$mode" != "--dry-run" ]; then
    echo "== connection test"
    python3 deliver_emails.py --test
    echo
fi
echo "== delivering to $to (${mode:-draft})"
python3 deliver_emails.py "$dir" $mode --log-file ''
