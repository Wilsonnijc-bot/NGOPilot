# RosterCopiilot — Ubuntu Deployment Runbook (Supervised Demo)

This deploys RosterCopiilot as an **externally accessible, access-gated,
supervised demo** — not an unsupervised production system. It does not imply
NGO acceptance or staff-facing production readiness.

Target: Ubuntu 24.04 LTS (verify with `cat /etc/os-release`). Architecture:

```
Browser ── HTTPS ──> Nginx ──┬── /            static frontend (index.html + vendor/)
                             └── /api/*       Uvicorn @ 127.0.0.1:8000
                                                 ├── SQLite  /var/lib/rostercopiilot/roster.db
                                                 └── exports /var/lib/rostercopiilot/exports/
```

## Persistent data locations

| Path | Purpose | Owner / mode |
|------|---------|--------------|
| `/opt/rostercopiilot/releases/<git-sha>/` | Immutable release code + venv | root, 0755 |
| `/opt/rostercopiilot/current` | Symlink to the active release | root |
| `/var/lib/rostercopiilot/roster.db` | SQLite database (survives releases) | rostercopiilot, 0640 |
| `/var/lib/rostercopiilot/exports/` | Generated workbooks | rostercopiilot, 0750 |
| `/etc/rostercopiilot/rostercopiilot.env` | Env config + optional secrets | root:rostercopiilot, 0640 |
| `/etc/nginx/rostercopiilot.htpasswd` | Basic-auth credentials | root, 0640 |
| `/var/backups/rostercopiilot/` | Backups (confidential) | root, 0700 |

Persistent data lives **outside** the release directory, so upgrades and
rollbacks never touch it.

## Prerequisites (install only what is missing)

```bash
sudo apt-get update
sudo apt-get install -y python3-venv nginx sqlite3 apache2-utils rsync
# TLS (if a domain is available):
sudo apt-get install -y certbot python3-certbot-nginx
```

## First deployment

```bash
# 1. Get a committed checkout onto the VPS (clone or rsync a specific SHA).
git clone <repo> /tmp/rostercopiilot && cd /tmp/rostercopiilot
git checkout <git-sha>

# 2. Install (idempotent): creates the user, dirs, release, venv, unit + site.
sudo deploy/ubuntu/install.sh

# 3. Verify the backend locally (loopback only).
curl -fsS http://127.0.0.1:8000/api/health

# 4. Configure the env file (persistent paths are pre-filled; review CORS/token).
sudo nano /etc/rostercopiilot/rostercopiilot.env
sudo systemctl restart rostercopiilot

# 5. Create the access gate (credentials NOT in git).
sudo htpasswd -c /etc/nginx/rostercopiilot.htpasswd demo

# 6. Point both Nginx templates at the domain. Enable the HTTP-only bootstrap
#    site first; it exposes only the ACME challenge and returns 503 elsewhere.
sudo sed -i 's/REPLACE_WITH_DOMAIN/roster.example.org/g' /etc/nginx/sites-available/rostercopiilot
sudo sed -i 's/REPLACE_WITH_DOMAIN/roster.example.org/g' /etc/nginx/sites-available/rostercopiilot-bootstrap
sudo ln -sfn /etc/nginx/sites-available/rostercopiilot-bootstrap /etc/nginx/sites-enabled/rostercopiilot
sudo nginx -t && sudo systemctl reload nginx

# 7. Obtain the certificate without exposing the unauthenticated demo over
#    plaintext HTTP, then atomically switch to the final HTTPS site.
sudo certbot certonly --webroot -w /var/www/html -d roster.example.org
sudo ln -sfn /etc/nginx/sites-available/rostercopiilot /etc/nginx/sites-enabled/rostercopiilot
sudo nginx -t && sudo systemctl reload nginx

# 8. Firewall: allow SSH + HTTPS only; never expose 8000.
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

> **Access-gate options.** HTTP Basic over HTTPS (above) is the minimum gate.
> A Tailscale/VPN address or an Nginx `allow`/`deny` IP allowlist are acceptable
> alternatives. Do **not** expose the demo anonymously while it can accept or
> display personal data. Provision all credentials outside git.

## Updating to a new release

```bash
cd /path/to/checkout && git fetch && git checkout <new-git-sha>
sudo deploy/ubuntu/install.sh          # builds a new release dir, flips 'current'
curl -fsS http://127.0.0.1:8000/api/health
```

Old releases remain under `/opt/rostercopiilot/releases/` for rollback.

## Rollback procedure

```bash
# List releases and pick the previous good SHA.
ls -1 /opt/rostercopiilot/releases/
sudo ln -sfn /opt/rostercopiilot/releases/<previous-sha> /opt/rostercopiilot/current
sudo systemctl restart rostercopiilot
curl -fsS http://127.0.0.1:8000/api/health
```

Because persistent data is external, rollback is a symlink flip + restart. If a
release changed the database shape (this build does not), also restore a
pre-upgrade DB backup (see below).

## Backup & restore

```bash
# Backup (schedule daily). WAL-safe consistent snapshot + integrity check.
sudo deploy/ubuntu/backup.sh
#   -> /var/backups/rostercopiilot/roster-<ts>.db.gz  (+ exports-<ts>.tar.gz)

# Restore REHEARSAL (safe, does not touch live data) — run this regularly:
sudo deploy/ubuntu/restore.sh /var/backups/rostercopiilot/roster-<ts>.db.gz

# Real recovery (authorized incidents only): stops service, preserves current
# DB, swaps in the restored copy, restarts, health-checks.
sudo deploy/ubuntu/restore.sh /var/backups/rostercopiilot/roster-<ts>.db.gz --apply-live
```

Suggested cron (root):
`0 3 * * * /opt/rostercopiilot/current/deploy/ubuntu/backup.sh >> /var/log/rostercopiilot-backup.log 2>&1`

## Operational checklist (before public exposure)

- [ ] `/etc/os-release` confirms the expected Ubuntu version.
- [ ] `curl http://127.0.0.1:8000/api/health` returns `ok`.
- [ ] Uvicorn is bound to `127.0.0.1` only (`ss -lntp | grep 8000`).
- [ ] Port 8000 is **not** reachable from outside (firewall + loopback bind).
- [ ] Basic-auth (or VPN/IP allowlist) gate is active and tested.
- [ ] TLS valid; HTTP redirects to HTTPS; no mixed content.
- [ ] `ROSTER_ENV=production` (API docs disabled — `/docs` returns 404).
- [ ] `ROSTER_CORS_ORIGINS` empty (same-origin) — no wildcard.
- [ ] Backup runs and a restore rehearsal succeeds.
- [ ] No real NGO personal data seeded unless explicitly authorized.
- [ ] Journal contains no credentials or workbook personal data.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| 502 from Nginx | `systemctl status rostercopiilot`; `journalctl -u rostercopiilot -n 100` |
| Service won't start | Env file paths readable? `sudo -u rostercopiilot test -w /var/lib/rostercopiilot` |
| Uploads rejected (413) | `ROSTER_MAX_UPLOAD_MB` vs Nginx `client_max_body_size` (12m) |
| Icons missing | `vendor/lucide.min.js` present in the release `frontend/`? (page still works without icons) |
| API calls 401 | Basic-auth prompt (expected) or `ROSTER_API_TOKEN` set — the browser demo should leave the token unset |
| "database is locked" | Confirm one worker; WAL + 30s busy_timeout are enabled in-app |
| Stale review 409 | Expected concurrency protection; the UI auto-reloads the latest version |

Inspect:

```bash
systemctl status rostercopiilot
journalctl -u rostercopiilot -n 200 --no-pager
nginx -t
ss -lntp
```

## Known limitations (supervised demo)

- Browser access control is enforced at the reverse proxy, not in the app
  (a browser SPA cannot hold a shared secret). The optional `ROSTER_API_TOKEN`
  adds app-level gating for scripted/direct API access only.
- CSP allows `'unsafe-inline'` for the first-party inline UI bundle; all dynamic
  content is HTML-escaped in the frontend.
- Single Uvicorn worker; multi-worker correctness is not certified here.
- Not production hardened: no RBAC, no audit-log shipping, no HA.
