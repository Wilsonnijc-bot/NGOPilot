#!/usr/bin/env bash
#
# RosterCopiilot Ubuntu install / update script (idempotent).
#
# Deploys a specific committed checkout into a versioned release directory,
# builds an isolated virtualenv, installs the systemd unit and Nginx site, and
# (re)starts the service. Safe to re-run: it never touches persistent data in
# /var/lib/rostercopiilot and never overwrites an existing env or htpasswd file.
#
# Usage (run as root on the VPS, from inside a checked-out copy of the repo):
#   sudo deploy/ubuntu/install.sh
#
# Prerequisites: python3 (>=3.11) with venv, nginx. Run apply-tls/basic-auth
# steps from README.md before public exposure.
set -euo pipefail

APP_USER="rostercopiilot"
APP_GROUP="rostercopiilot"
BASE="/opt/rostercopiilot"
RELEASES="${BASE}/releases"
CURRENT="${BASE}/current"
STATE="/var/lib/rostercopiilot"
ETC="/etc/rostercopiilot"
ENV_FILE="${ETC}/rostercopiilot.env"

log() { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[install:error]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "must run as root (use sudo)"

# Resolve the repository root (two levels up from this script).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

command -v git >/dev/null 2>&1 || die "git is required"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "nogit")"
[ "${GIT_SHA}" = "nogit" ] && die "not a git checkout; deploy a committed SHA"
RELEASE_DIR="${RELEASES}/${GIT_SHA}"

log "Deploying commit ${GIT_SHA}"

# --- Service account -------------------------------------------------------
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    log "Creating system user ${APP_USER}"
    useradd --system --home-dir "${STATE}" --shell /usr/sbin/nologin "${APP_USER}"
fi

# --- Directories -----------------------------------------------------------
install -d -m 0755 "${BASE}" "${RELEASES}"
install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${STATE}"
install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${STATE}/exports"
install -d -m 0750 "${ETC}"

# --- Release checkout ------------------------------------------------------
# Copy only the tracked application code; never copy local data/exports or the
# working virtualenv.
log "Syncing release into ${RELEASE_DIR}"
install -d -m 0755 "${RELEASE_DIR}"
rsync -a --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'data' \
    --exclude 'output' \
    --exclude 'tmp' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "${REPO_ROOT}/" "${RELEASE_DIR}/"

# --- Virtualenv ------------------------------------------------------------
if [ ! -x "${RELEASE_DIR}/.venv/bin/python" ]; then
    log "Creating virtualenv"
    python3 -m venv "${RELEASE_DIR}/.venv"
fi
log "Installing dependencies"
"${RELEASE_DIR}/.venv/bin/python" -m pip install --upgrade pip >/dev/null
"${RELEASE_DIR}/.venv/bin/python" -m pip install -e "${RELEASE_DIR}[dev]"

# --- Environment file (never overwrite an existing one) --------------------
if [ ! -f "${ENV_FILE}" ]; then
    log "Installing example env to ${ENV_FILE} (EDIT before exposure)"
    install -m 0640 -g "${APP_GROUP}" "${SCRIPT_DIR}/env.example" "${ENV_FILE}"
else
    log "Keeping existing ${ENV_FILE}"
fi

# --- Activate this release atomically --------------------------------------
ln -sfn "${RELEASE_DIR}" "${CURRENT}"
chown -h root:root "${CURRENT}"

# --- systemd unit ----------------------------------------------------------
log "Installing systemd unit"
install -m 0644 "${SCRIPT_DIR}/rostercopiilot.service" /etc/systemd/system/rostercopiilot.service
systemctl daemon-reload
systemctl enable rostercopiilot.service >/dev/null 2>&1 || true
systemctl restart rostercopiilot.service

# --- Nginx sites (install but do not enable without a domain) --------------
if command -v nginx >/dev/null 2>&1; then
    log "Installing Nginx bootstrap and final TLS sites"
    install -m 0644 "${SCRIPT_DIR}/nginx-bootstrap.conf" /etc/nginx/sites-available/rostercopiilot-bootstrap
    install -m 0644 "${SCRIPT_DIR}/nginx.conf" /etc/nginx/sites-available/rostercopiilot
    log "Obtain TLS through the bootstrap site before enabling the final site. See README.md."
else
    log "Nginx not installed; skipping site install"
fi

log "Done. Deployed ${GIT_SHA}."
log "Verify: curl -fsS http://127.0.0.1:8000/api/health"
log "Next: set access gate (htpasswd), TLS (certbot), then reload nginx. See README.md."
