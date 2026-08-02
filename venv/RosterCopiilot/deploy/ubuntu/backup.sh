#!/usr/bin/env bash
#
# RosterCopiilot backup: consistent hot copy of the SQLite database plus the
# exports directory, with retention pruning. WAL-safe (uses sqlite3 .backup).
#
# Usage (root or the service user):
#   deploy/ubuntu/backup.sh [BACKUP_DIR]
# Default BACKUP_DIR: /var/backups/rostercopiilot
#
# Schedule daily via cron/systemd timer. Backups may contain workbook-derived
# data: store them with restrictive permissions and confidentiality controls.
set -euo pipefail

STATE="${ROSTER_STATE_DIR:-/var/lib/rostercopiilot}"
DB_PATH="${ROSTER_DB_PATH:-${STATE}/roster.db}"
EXPORT_DIR="${ROSTER_EXPORT_DIR:-${STATE}/exports}"
BACKUP_DIR="${1:-/var/backups/rostercopiilot}"
RETENTION_DAYS="${ROSTER_BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

log() { printf '[backup] %s\n' "$*"; }
die() { printf '[backup:error] %s\n' "$*" >&2; exit 1; }

command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 is required (apt-get install sqlite3)"
[ -f "${DB_PATH}" ] || die "database not found: ${DB_PATH}"

install -d -m 0700 "${BACKUP_DIR}"

DB_OUT="${BACKUP_DIR}/roster-${STAMP}.db"
log "Backing up database -> ${DB_OUT}"
# .backup takes a consistent snapshot even while the service is writing.
sqlite3 "${DB_PATH}" ".backup '${DB_OUT}'"
# Integrity-check the snapshot before trusting it.
CHECK="$(sqlite3 "${DB_OUT}" 'PRAGMA integrity_check;')"
[ "${CHECK}" = "ok" ] || die "integrity check failed on snapshot: ${CHECK}"
gzip -f "${DB_OUT}"
chmod 0600 "${DB_OUT}.gz"
log "Database snapshot verified and compressed: ${DB_OUT}.gz"

if [ -d "${EXPORT_DIR}" ]; then
    EXPORTS_OUT="${BACKUP_DIR}/exports-${STAMP}.tar.gz"
    log "Archiving exports -> ${EXPORTS_OUT}"
    tar -czf "${EXPORTS_OUT}" -C "$(dirname "${EXPORT_DIR}")" "$(basename "${EXPORT_DIR}")"
    chmod 0600 "${EXPORTS_OUT}"
fi

log "Pruning backups older than ${RETENTION_DAYS} days"
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'roster-*.db.gz' -mtime "+${RETENTION_DAYS}" -delete
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'exports-*.tar.gz' -mtime "+${RETENTION_DAYS}" -delete

log "Backup complete."
