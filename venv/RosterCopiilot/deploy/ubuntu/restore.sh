#!/usr/bin/env bash
#
# RosterCopiilot restore / restore-rehearsal.
#
# By default this restores a backup into a SEPARATE verification directory and
# runs an integrity check WITHOUT touching the live database — this is the
# rehearsal path you run regularly to prove backups are recoverable.
#
# Usage:
#   deploy/ubuntu/restore.sh <roster-YYYYMMDDT...db.gz> [--verify-dir DIR]
#   deploy/ubuntu/restore.sh <roster-...db.gz> --apply-live   # DANGEROUS
#
# --apply-live stops the service, backs up the current DB, swaps in the restored
# copy, fixes ownership, and restarts. Only use during an authorized recovery.
set -euo pipefail

STATE="${ROSTER_STATE_DIR:-/var/lib/rostercopiilot}"
DB_PATH="${ROSTER_DB_PATH:-${STATE}/roster.db}"
APP_USER="rostercopiilot"
APP_GROUP="rostercopiilot"

log() { printf '[restore] %s\n' "$*"; }
die() { printf '[restore:error] %s\n' "$*" >&2; exit 1; }

BACKUP=""
APPLY_LIVE=0
VERIFY_DIR="$(mktemp -d /tmp/rostercopiilot-restore.XXXXXX)"
while [ $# -gt 0 ]; do
    case "$1" in
        --apply-live) APPLY_LIVE=1; shift ;;
        --verify-dir) VERIFY_DIR="$2"; shift 2 ;;
        *) BACKUP="$1"; shift ;;
    esac
done

[ -n "${BACKUP}" ] || die "usage: restore.sh <backup.db.gz> [--apply-live] [--verify-dir DIR]"
[ -f "${BACKUP}" ] || die "backup not found: ${BACKUP}"
command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 is required"

install -d -m 0700 "${VERIFY_DIR}"
RESTORED="${VERIFY_DIR}/roster.restored.db"
log "Decompressing ${BACKUP} -> ${RESTORED}"
gunzip -c "${BACKUP}" > "${RESTORED}"

log "Integrity check"
CHECK="$(sqlite3 "${RESTORED}" 'PRAGMA integrity_check;')"
[ "${CHECK}" = "ok" ] || die "integrity check FAILED: ${CHECK}"
ROWS="$(sqlite3 "${RESTORED}" "SELECT count(*) FROM weeklyrundocument;" 2>/dev/null || echo '?')"
log "Integrity OK. weekly runs in snapshot: ${ROWS}"

if [ "${APPLY_LIVE}" -eq 0 ]; then
    log "Rehearsal complete. Restored copy left at: ${RESTORED}"
    log "No live data was modified. Re-run with --apply-live for real recovery."
    exit 0
fi

# --- Live recovery ---------------------------------------------------------
[ "$(id -u)" -eq 0 ] || die "--apply-live must run as root"
log "Stopping service"
systemctl stop rostercopiilot.service || true
if [ -f "${DB_PATH}" ]; then
    SAFETY="${DB_PATH}.pre-restore.$(date -u +%Y%m%dT%H%M%SZ)"
    log "Preserving current DB -> ${SAFETY}"
    cp -a "${DB_PATH}" "${SAFETY}"
fi
# Remove stale WAL/SHM so the restored file is authoritative.
rm -f "${DB_PATH}-wal" "${DB_PATH}-shm"
install -o "${APP_USER}" -g "${APP_GROUP}" -m 0640 "${RESTORED}" "${DB_PATH}"
log "Starting service"
systemctl start rostercopiilot.service
sleep 2
curl -fsS http://127.0.0.1:8000/api/health >/dev/null && log "Health OK after restore." || die "health check failed after restore"
log "Live restore complete."
