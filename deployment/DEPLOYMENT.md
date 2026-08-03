# NGOPilot Cloud Deployment

This deployment keeps the public surface small:

```text
Render Static Site (React/Vite)
        | HTTPS + WSS
        v
Railway API/ACP service (one replica)
        |-- Railway PostgreSQL: accounts, chat history, jobs, object metadata
        |-- Railway Volume at /data: tenant ACP and native SQLite state
        `-- Private S3/R2 bucket: uploads and generated artifacts
```

PostgreSQL is the product index and ownership boundary. The attached volume is
durable runtime state, not a cache: CareFlow and Roster follow-up operations need
their native SQLite rows and adjacent files. Object storage holds immutable user
uploads and generated artifacts; PostgreSQL stores their metadata and checksums.

## Preconditions

Use the existing user-level deployment CLI credentials. Verify identity before
changing cloud resources:

```sh
railway whoami
render whoami
aws sts get-caller-identity
```

Do not create or deploy AWS root access keys. The Railway service needs a new
least-privilege IAM identity restricted to the one NGOPilot bucket, or equivalent
R2 credentials restricted to that bucket. Keep all credentials in provider secret
stores, never in Git, build arguments, Render variables, URLs, or logs.

## Environment Contract

Start from [`deployment/.env.example`](.env.example). Angle-bracket values are
placeholders and must not be deployed literally.

### Railway API variables

| Variable | Required | Value / rule |
|---|---:|---|
| `DATABASE_URL` | Yes | Railway PostgreSQL private URL; secret |
| `DATA_ROOT` | Yes | Exactly `/data`, matching the mounted volume |
| `PUBLIC_API_URL` | Yes | Public Railway origin, HTTPS, no trailing slash |
| `ALLOWED_ORIGINS` | Yes | Comma-separated exact Render origins; never `*` |
| `GOOSE_PROVIDER` | Yes | `openrouter` |
| `GOOSE_MODEL` | Yes | `openai/gpt-5.6-luna` |
| `OPENROUTER_API_KEY` | Yes | Railway secret; never a `VITE_*` variable |
| `DATABASE_POOL_MIN_SIZE` | No | PostgreSQL pool floor; `1` is the default |
| `DATABASE_POOL_MAX_SIZE` | No | PostgreSQL pool ceiling; `10` is the default and must be at least the floor |
| `AUTH_TOKEN_TTL_HOURS` | Yes | Positive integer; `168` is the default |
| `WS_TICKET_TTL_SECONDS` | Yes | `5` to `300`; `60` is the default |
| `REGISTRATION_ENABLED` | Yes | `true` for initial signup, then set policy explicitly |
| `MAX_UPLOAD_BYTES` | Yes | Positive integer; `26214400` is 25 MiB |
| `UPLOAD_RESOLVE_TIMEOUT_SECONDS` | No | Seconds to wait for a staged upload; `30` is the default |
| `S3_BUCKET` | Yes | Private bucket name |
| `S3_REGION` | Yes | Bucket region |
| `S3_ENDPOINT_URL` | R2 only | R2 S3 endpoint; leave empty for AWS S3 |
| `AWS_ACCESS_KEY_ID` | Yes | Least-privilege bucket credential; secret |
| `AWS_SECRET_ACCESS_KEY` | Yes | Least-privilege bucket credential; secret |
| `NGOPILOT_BIN` | Yes | Installed ACP executable; default `ngopilot` |
| `NGOPILOT_MCP_BIN` | Yes | Installed MCP executable; default `ngopilot-mcp` |
| `NGOPILOT_MCP_SHARED_STATE_DIR` | Yes | Exactly `/opt/ngopilot/shared`; immutable and prebuilt into the image |
| `NGOPILOT_PROCESS_IDLE_SECONDS` | Yes | Positive integer; `900` is the default |
| `NGOPILOT_PROCESS_STARTUP_SECONDS` | Yes | Positive integer; `90` is the default |
| `PORT` | Automatic | Injected by Railway; the service must bind `0.0.0.0:$PORT` |

`DATA_ROOT` contains tenant directories derived only from authenticated UUIDs:

```text
/data/
  tenants/<user_uuid>/
    goose/       # ACP session/config state
    workflow/    # MCP jobs, CareFlow, Roster, exports
    uploads/     # server-side staged inputs
    tmp/
```

Database `storage_objects.local_path` values are relative to `DATA_ROOT`. Reject
absolute paths and any rebased path that escapes `/data`.

Shared MCP worker environments live at `/opt/ngopilot/shared/runtimes` inside the
container image. They are immutable release assets, not tenant data and not volume
content. Tenant workflow directories may contain symlinks to those image paths;
backups restore the tenant trees and recreate the runtime links from the matching
image revision.

### Render build variables

| Variable | Value |
|---|---|
| `VITE_API_URL` | Same HTTPS origin as `PUBLIC_API_URL` |
| `VITE_GOOSE_DEFAULT_PROVIDER` | `openrouter` |
| `VITE_GOOSE_DEFAULT_MODEL` | `openai/gpt-5.6-luna` |

No model, database, AWS, ACP, or object-store secret belongs in Render. Vite
variables are public at build time.

## PostgreSQL

Provision one Railway PostgreSQL service and expose its private `DATABASE_URL` to
the API service using a Railway variable reference. Do not expose PostgreSQL to
the browser.

The initial migration is
[`deployment/backend/ngopilot_gateway/migrations/001_initial.sql`](backend/ngopilot_gateway/migrations/001_initial.sql).
It creates a migration ledger and tenant-owned users, auth sessions, one-use WebSocket
tickets, chat sessions, messages, jobs, and object metadata. JSON columns have size
limits so Roster responses cannot silently recreate the previous multi-megabyte
message/operation duplication.

The gateway runs pending migrations before starting Uvicorn. To run them explicitly
inside Railway private networking:

```sh
python -m ngopilot_gateway.migrate
```

The migration runner inspects `schema_migrations` and skips version `1` after it is
recorded. Do not blindly rerun a numbered SQL file and do not use ORM `create_all()`
as a migration mechanism. Apply later changes through new numbered, transactional
files.

Verify the installed version without printing the connection URL:

```sql
SELECT version, name, applied_at FROM schema_migrations ORDER BY version;
```

The API must derive `user_id` from the stored SHA-256 bearer-token digest. It must
never trust `user_id`, `agent_session_id`, `native_refs`, `local_path`, or
`object_key` supplied by a browser or model tool payload. Every session, message,
job, and object query must include the authenticated owner; composite foreign keys
provide a second ownership check.

Schema ownership is intentionally small:

- `users` and `auth_sessions` own identity and revocable opaque bearer tokens;
- `ws_tickets` stores only one-use SHA-256 ticket digests for WSS upgrades;
- `chat_sessions` maps one user to an internal ACP session;
- `messages` retains bounded structured ACP content, not flattened text;
- `jobs` keeps a bounded public result plus the native reference needed to resume;
- `storage_objects` records private S3/R2 objects and root-relative volume paths.

Native CareFlow and Roster tables remain authoritative for their domain rules.
Copying their large documents into PostgreSQL messages or job history is expressly
out of scope.

## Private Object Storage

Use one private S3 or R2 bucket with public access blocked. Enable encryption at
rest (`SSE-S3`, `SSE-KMS`, or the R2 equivalent) and TLS-only access. Grant the
Railway identity only the object actions and prefixes the API uses.

Use opaque keys without names, emails, or document text:

```text
tenants/<user_uuid>/uploads/<object_uuid>/<safe_filename>
tenants/<user_uuid>/artifacts/<sha256>/<safe_filename>
native-backups/<utc_timestamp>/<manifest_or_archive>
```

The current browser sends uploads through the authenticated API, so the bucket
does not need public CORS. If direct presigned uploads are added later, allow only
the exact Render origin and the required methods/headers. Keep signed URLs
short-lived and generate them on demand; never persist signed URLs.

Record byte size and lowercase SHA-256 after the API has verified the stored
object. Do not use an S3 `ETag` as a content hash because multipart ETags are not
SHA-256. A `storage_objects` row may enter `ready` only after the object key,
checksum, size, and verification time are present.

Object deletion is two-phase because PostgreSQL cannot delete S3 objects in the
same transaction: mark the row deleting, remove the object and any versions, then
mark/delete the row. Configure lifecycle cleanup for abandoned multipart uploads
and stale pending uploads. If bucket versioning is enabled, transcript burn and
account purge must delete every retained version or must not claim irreversible
erasure.

## Railway API Service

[`deployment/railway.json`](railway.json) fixes the Dockerfile, migration command,
start command, readiness check, restart policy, and replica count. In Railway's
service settings, set the config-file path to `/deployment/railway.json`; a volume
and database variable reference still require explicit project configuration.

1. Create a Railway service from the repository root with Dockerfile path
   `deployment/backend/Dockerfile`. Its container command is
   `python -m ngopilot_gateway`.
2. Attach one Railway Volume at `/data` before first start.
3. Add the API variables above through Railway variable references/secrets.
4. Set the pre-deploy command to `python -m ngopilot_gateway.migrate`; startup also
   checks pending migrations.
5. Set Railway's traffic health check to `/readyz`. `/healthz` is the liveness
   endpoint; readiness must succeed before traffic is accepted.
6. Generate a Railway public domain, then set `PUBLIC_API_URL` to that exact HTTPS
   origin.

Keep the backend at exactly **one replica**. The volume can attach to only one
service instance, native SQLite permits one coordinated writer per tenant, and ACP
process ownership is local to that instance. Horizontal scaling requires moving
native state and process coordination to network services; it is not a replica
count change.

Deployments must be rolling-disabled or otherwise ensure that two revisions do not
write the same volume concurrently. The API should serialize mutations per
`(user_id, native_worker)` while allowing independent users to proceed.

WebSocket access uses a short-lived, one-use ticket from authenticated
`POST /api/ws-tickets`, then connects to `wss://<api-host>/acp?ticket=...`. Store
only its 32-byte SHA-256 digest in `ws_tickets`, consume it atomically, and reject
expired, used, or wrong-user tickets. Redact the query value from access logs.
Never expose the ACP shared secret to the browser.

The remaining public API paths are `POST /api/auth/register`,
`POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, and
`POST /api/uploads`. All except registration/login require the bearer token issued
by the auth gateway.

## Render Static Site

[`deployment/render.yaml`](render.yaml) is the Render Blueprint for the static
site. Select that Blueprint path when connecting the repository. If the dashboard
does not offer a custom Blueprint path, create the static site manually with the
same settings below.

Create a Render **Static Site** with:

| Setting | Value |
|---|---|
| Root directory | `deployment/frontend` |
| Build command | `corepack enable && pnpm install --frozen-lockfile && pnpm build` |
| Publish directory | `dist` |
| Node version | `24.10.0` or newer |

Add the three public `VITE_*` variables above. Configure a rewrite from `/*` to
`/index.html` with status `200` so client-side routes survive refreshes. After the
first Render deploy, set `ALLOWED_ORIGINS` on Railway to the exact Render HTTPS
origin and redeploy the API. CORS must allow `Authorization` and content headers
only for configured origins.

## Deployment Order

1. Verify the three CLI identities, then create or select one private encrypted
   S3/R2 bucket and its least-privilege service credential.
2. In Railway, create PostgreSQL and the API service, select
   `/deployment/railway.json`, attach a volume at `/data`, and set all Railway API
   variables except the final Render origin.
3. Generate the Railway domain and set `PUBLIC_API_URL` to its HTTPS origin.
4. In Render, create the static site from `/deployment/render.yaml`, set
   `VITE_API_URL` to the Railway origin, and deploy once to obtain the Render URL.
5. Set Railway `ALLOWED_ORIGINS` to that exact Render HTTPS origin. Run the
   pre-deploy migration and deploy the single API replica.
6. Confirm `/readyz`, redeploy Render if its API URL changed, then run the release
   checks below.

Do not point DNS at the deployment until both `/readyz` and the browser workflow
pass. When adding custom domains, update `PUBLIC_API_URL`, `VITE_API_URL`, and
`ALLOWED_ORIGINS` together before switching traffic.

## Backup and Restore

Railway PostgreSQL, the Railway Volume, and S3/R2 are one recovery set. A database
backup alone cannot resume CareFlow or Roster jobs.

### Backup

1. Stop accepting new mutations and wait for active native workers to finish.
2. Create a timestamped PostgreSQL custom-format dump with `pg_dump`.
3. Use SQLite's online `.backup` API for every database below `/data/tenants`.
   Do not copy a live main `.db` file without its WAL.
4. Copy each tenant's adjacent native files, including CareFlow transcript vault
   files/key, Roster exports, and job manifests. Do not copy the immutable shared
   runtimes from `/opt`; retain the referenced container image instead.
5. Write a manifest containing hashes, image revision, migration versions,
   `DATA_ROOT`, and object-store bucket/region.
6. Upload the encrypted dump, SQLite snapshots, native trees, and manifest to the
   private backup prefix, then resume traffic.

Use a separate backup retention policy from user artifact retention. Test restore
regularly; an untested archive is not a backup.

The initial retention policy should be explicit and automated:

| Data | Default retention |
|---|---|
| Active chats, jobs, uploads, artifacts | Until the user deletes them |
| Soft-deleted user data | 30-day recovery window, then hard purge |
| Used/expired WebSocket tickets | Purge within 24 hours |
| Revoked/expired auth sessions | Purge after 30 days |
| Failed/pending uploads and local staging | Purge after 24 hours |
| Backups | 7 daily, 4 weekly, 3 monthly recovery points |

Document that purged content can remain in encrypted backups until the backup
retention window expires. Transcript burn is the exception: it must remove the
native transcript, PostgreSQL-derived copies, staged audio according to policy,
and every object-store version before the product calls the operation irreversible.

### Restore

1. Stop the API and attach an empty volume at the same `/data` mount.
2. Restore PostgreSQL and the volume from the same backup timestamp.
3. Restore object versions referenced by `storage_objects`.
4. Run `PRAGMA integrity_check` on every SQLite database and
   `PRAGMA foreign_key_check` where foreign keys are enabled.
5. Verify object size/SHA-256, native references, templates, and paths against the
   backup manifest.
6. Start one API replica, run reconciliation, then reopen traffic.

CareFlow stores most paths relative to its data root, but legacy MCP/Roster data
can contain absolute paths. Preserve the `/data` mount and rebase/validate any
imported legacy paths before declaring restore successful.

## Release Verification

Before calling a deployment usable, verify all of the following from a new browser
profile:

- registration policy, login, logout, expiry, and cross-user access denial;
- session creation, reload, archive/delete, and message persistence after restart;
- authenticated WSS reconnect using a fresh one-use ticket;
- one complete CareFlow workflow and one complete Roster workflow;
- upload size/type rejection and private artifact download authorization;
- S3/R2 objects are not anonymously readable;
- a backend restart preserves PostgreSQL, `/data`, and artifact access;
- migration version, PostgreSQL backup, volume backup, and restore test are current.

Never report a successful deployment while these checks or a restore test are
failing.

Run the non-secret infrastructure probes first:

```sh
API_URL=https://<railway-api-domain>
WEB_URL=https://<render-static-site-domain>

curl -fsS "$API_URL/healthz"
curl -fsS "$API_URL/readyz"
curl -fsSI "$WEB_URL/"
aws s3api get-public-access-block --bucket '<private-bucket-name>'
aws s3api get-bucket-encryption --bucket '<private-bucket-name>'
```

Then create two disposable test accounts in a private shell, without printing
their bearer tokens. For each account, verify `GET /api/auth/me`, create a one-use
ticket with `POST /api/ws-tickets`, and connect through the browser. Confirm that
reusing the ticket fails and that neither account can load the other's session,
job, upload, or artifact identifiers.

Upload a representative image, audio file, DOCX, and workbook below
`MAX_UPLOAD_BYTES`. Confirm each object is private, its database SHA-256 matches
downloaded bytes, and the corresponding local path remains below that user's
tenant root. Complete one CareFlow and one Roster workflow, restart the Railway
service, reload both chats, and retrieve their generated artifacts again.
