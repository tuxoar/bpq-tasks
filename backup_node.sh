#!/usr/bin/env bash
# One-shot backup of every file docs/rebuild.md §1 calls out, pulled from
# the node over SSH into a single timestamped tarball under ./backups/.
#
# Usage:
#   ./backup_node.sh [user@host]        # default: 100.69.92.43
#
# The archive contains real credentials (bpq32.cfg passwords, bpq.env,
# VARA license) — backups/ is gitignored and the tarball is chmod 600.
# Copy the result somewhere off this machine too; a backup that lives
# next to the repo on the same disk as nothing is still one disk away
# from useless in the disaster this exists for.
#
# The netplan file is root-only on the node. The script tries
# passwordless sudo first, then falls back to prompting for the sudo
# password when run interactively; if neither works you get a warning,
# not a failure (its contents are also recorded in docs/rebuild.md §5).

set -Eeuo pipefail

HOST="${1:-${BPQ_BACKUP_HOST:-100.69.92.43}}"
STAMP="$(date +%Y%m%d-%H%M%S)"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${SCRIPT_DIR}/backups"
STAGING="${BACKUP_DIR}/.staging-${STAMP}"
ARCHIVE="${BACKUP_DIR}/bpq-node-backup-${STAMP}.tar.gz"

# Home-relative paths to collect (globs expand on the node; missing
# entries are skipped with a warning at the end, not an error).
HOME_PATHS='
linbpq/bpq32.cfg
linbpq/bpq32.cfg-ALL
linbpq/bpq32.cfg.ICOM
linbpq/bpq32.cfg.ftdx10
linbpq/bpq32.cfg.tentec
linbpq/linmail.cfg
linbpq/WP.cfg
linbpq/direwolf.conf
linbpq/DIRMES.SYS
linbpq/BPQNODES.dat
linbpq/Mail
linbpq/direwolf-bpq-start.sh
linbpq/start_bpq.sh
ic7100-packet-start.sh
scripts/bpq_logs.sh
bpq-tasks/bpq.env
.ssh/authorized_keys
.wine/drive_c/VARA
.wine/drive_c/VARA FM
.wine/user.reg
.wine/system.reg
vara-installers
'

# Required entries: their absence means the backup is NOT a full
# disaster-recovery set, so say so loudly.
REQUIRED='
linbpq/bpq32.cfg
linbpq/linmail.cfg
linbpq/direwolf.conf
linbpq/Mail
bpq-tasks/bpq.env
.wine/drive_c/VARA
'

warn() { printf 'WARNING: %s\n' "$*" >&2; }
info() { printf '%s\n' "$*"; }

cleanup() { rm -rf "${STAGING}"; }
trap cleanup EXIT

info "Backing up BPQ node ${HOST} -> ${ARCHIVE}"

if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "${HOST}" true 2>/dev/null; then
    echo "ERROR: cannot reach ${HOST} over SSH (key auth)" >&2
    exit 1
fi

mkdir -p "${BACKUP_DIR}"
mkdir -p "${STAGING}/home" "${STAGING}/etc" "${STAGING}/meta"

# --- home files: existence-filter on the node, stream one tar back ----
info "[1/4] Home-directory files (configs, Mail/, VARA, installers)..."
ssh "${HOST}" '
    cd "$HOME"
    while IFS= read -r p; do
        [ -n "$p" ] && [ -e "$p" ] && printf "%s\n" "$p"
    done | tar czf - --ignore-failed-read -T -
' <<<"${HOME_PATHS}" | tar xzf - -C "${STAGING}/home"

# --- /etc files readable without root ---------------------------------
info "[2/4] /etc files (udev rules, axports)..."
ssh "${HOST}" \
    'tar czf - --ignore-failed-read -C / etc/udev/rules.d/99-usb-serial.rules etc/ax25/axports 2>/dev/null' \
    | tar xzf - -C "${STAGING}"

# --- netplan (root-only) ----------------------------------------------
info "[3/4] Netplan (needs sudo on the node)..."
mkdir -p "${STAGING}/etc/netplan"
if ssh "${HOST}" 'sudo -n cat /etc/netplan/01-ax25.yaml' \
        >"${STAGING}/etc/netplan/01-ax25.yaml" 2>/dev/null && \
        [ -s "${STAGING}/etc/netplan/01-ax25.yaml" ]; then
    :
elif [ -t 0 ] && ssh -t "${HOST}" 'sudo cat /etc/netplan/01-ax25.yaml' \
        >"${STAGING}/etc/netplan/01-ax25.yaml" && \
        [ -s "${STAGING}/etc/netplan/01-ax25.yaml" ]; then
    # ssh -t can leave a stray CR at line ends; strip them
    sed -i 's/\r$//' "${STAGING}/etc/netplan/01-ax25.yaml"
else
    rm -f "${STAGING}/etc/netplan/01-ax25.yaml"
    warn "could not read /etc/netplan/01-ax25.yaml (no sudo); its contents are in docs/rebuild.md §5"
fi

# --- command-output snapshots -----------------------------------------
info "[4/4] Crontab and package list..."
ssh "${HOST}" 'crontab -l' >"${STAGING}/meta/crontab.txt" 2>/dev/null \
    || warn "could not read crontab"
ssh "${HOST}" 'apt-mark showmanual' >"${STAGING}/meta/manual-packages.txt" 2>/dev/null \
    || warn "could not list manually installed packages"
{
    echo "host: ${HOST}"
    echo "taken: $(date --iso-8601=seconds)"
    echo "by: $(whoami)@$(hostname)"
    echo "restore guide: docs/rebuild.md in the bpq-tasks repo"
} >"${STAGING}/meta/backup-info.txt"

# --- verify the must-have files made it in ----------------------------
missing=0
while IFS= read -r p; do
    [ -z "$p" ] && continue
    if [ ! -e "${STAGING}/home/${p}" ]; then
        warn "REQUIRED file missing from backup: ~/${p}"
        missing=1
    fi
done <<<"${REQUIRED}"

# --- bundle ------------------------------------------------------------
tar czf "${ARCHIVE}" -C "${STAGING}" .
chmod 600 "${ARCHIVE}"

info ""
info "Done: ${ARCHIVE} ($(du -h "${ARCHIVE}" | cut -f1))"
info "Contains secrets — keep it chmod 600 and NEVER commit it."
info "Now copy it off this machine (cloud drive, another host, USB)."
if [ "${missing}" -ne 0 ]; then
    warn "backup is INCOMPLETE — see REQUIRED warnings above"
    exit 1
fi
