# CareFlow Architecture Overview

Version: 0.4.8  
Generated from the current codebase on 2026-06-29.

## Executive Summary

CareFlow is a single-node, AI-assisted workflow application for community care operations. It combines a React/Vite frontend, a FastAPI backend, SQLite persistence, local file storage, and several external AI channels to turn paper forms, audio recordings, and PDF templates into reviewed operational outputs.

The product currently supports four main workflow families:

1. Volunteer paper forms to reviewed records and Excel exports.
2. Home-visit or internal-meeting audio plus a DOCX template to reviewed DOCX reports.
3. Welfare-form autofill from elder profile data into PDF templates.
4. Custom PDF form template discovery and publishing for later autofill use.

The deployment model is intentionally compact for demos: Docker Compose runs the backend and frontend on one host, keeps the backend private to the Docker network, exposes only the Nginx frontend on localhost, and can publish that frontend through Cloudflare Tunnel. Nginx adds Basic Auth, rate limiting, and security headers for public demo protection.

## Runtime Topology

```text
Browser
  |
  | HTTPS public demo URL, or http://127.0.0.1:8080 locally
  v
Cloudflare Tunnel, optional public entrypoint
  |
  v
Nginx frontend container
  |-- Serves React SPA static assets
  |-- Enforces demo Basic Auth
  |-- Applies API rate limits and security headers
  |
  | /api/*
  v
FastAPI backend container
  |-- SQLModel over SQLite
  |-- Local data directory for uploads, exports, templates, transcripts
  |-- AI provider clients for text, vision, and ASR
  |
  +--> DeepSeek-compatible text model
  +--> Azure OpenAI / Azure AI Foundry vision model
  +--> DashScope / Bailian ASR
```

In production-style Docker Compose, the backend does not publish a host port. Nginx talks to it over the internal Compose network at `http://backend:8000`. The frontend binds to `127.0.0.1:8080`, so public access must go through the local machine or a tunnel instead of exposing the backend directly.

## Repository Layout

```text
backend/
  app/
    api/                  FastAPI route modules
    llm/                  AI provider clients and wrappers
    services/             Workflow services and document/PDF processing
    main.py               FastAPI application entrypoint
    config.py             Pydantic settings and provider configuration
    db.py                 SQLite engine/session setup and lightweight migrations
    models.py             SQLModel persistence models
    version.py            Application version
  data/                   Runtime data, samples, templates, and generated files
  Dockerfile              Backend image build

frontend/
  src/                    React application
  nginx.conf              Static hosting, reverse proxy, auth, headers, rate limits
  Dockerfile              Frontend image build

docker-compose.yml        Local/demo Compose stack
docker-compose.deploy.yml Remote-image deployment variant
```

The current codebase is the source of truth. Some historical README text may mention heavier infrastructure, but the active implementation uses FastAPI in-process background tasks, SQLite, and lightweight schema adjustments rather than Celery workers or Alembic migrations.

## Backend Architecture

The backend starts from `backend/app/main.py`. It creates the FastAPI app, configures CORS from settings, initializes the database on startup, exposes `/api/health`, serves allow-listed runtime files through `/api/files/{path:path}`, and registers the route modules for all workflows.

Important backend modules:

- `config.py`: central settings for runtime paths, CORS, AI provider endpoints, model names, API keys, and mock-mode fallbacks.
- `db.py`: resolves the SQLite database into the configured data directory, creates SQLModel tables, and applies small SQLite-safe migrations when needed.
- `models.py`: defines persistent records for volunteer batches, extracted volunteer records, field corrections, elders, visit sessions, Theta templates, and Theta fields.
- `api/*.py`: HTTP surface area for each workflow.
- `services/*.py`: workflow orchestration, AI extraction, document rendering, PDF filling, template publishing, and export logic.
- `llm/client.py`: factory layer for text, vision, and ASR provider clients.

The backend uses FastAPI `BackgroundTasks` for long-running extraction and rendering work. This keeps the app simple for a single-node demo, but these jobs are not durable across process restarts.

## Frontend Architecture

The frontend is a React 18, TypeScript, Vite, and Tailwind application. `frontend/src/App.tsx` defines the main pages and routes:

- `/`: main workflow landing page.
- `/volunteer/upload`: upload volunteer paper-form images.
- `/volunteer/review/:batchId`: review extracted volunteer records.
- `/history` and `/history/:batchId`: inspect previous batches and exports.
- `/templates`: manage export templates.
- `/settings`: operational settings page.
- `/home-visit`: create visit-note or meeting-note sessions.
- `/home-visit/sessions/:sessionId`: review and render a generated note.
- `/welfare-form`: preview and fill welfare PDF forms.
- `/theta/upload`: upload a custom PDF form.
- `/theta/audit/:templateId`: review detected PDF fields and publish a template.

All frontend API calls are centralized through `frontend/src/lib/api.ts` and use `/api/*` paths. During development, Vite proxies `/api` to `http://127.0.0.1:8000`. In the Docker demo, Nginx serves the static frontend and reverse-proxies `/api/*` to the backend container.

## Data Model

CareFlow uses SQLModel over SQLite. The main persistent entities are:

- `VolunteerBatch`: a group of uploaded volunteer form photos and its processing status.
- `VolunteerRecord`: one uploaded form image, its AI extraction results, final reviewed fields, provider metadata, timing, errors, and confidence data.
- `FieldCorrection`: reviewer corrections used for audit and prompt-feedback loops.
- `Elder`: a simple elder profile record.
- `VisitSession`: one audio-to-DOCX session, including file paths, extraction phases, template contract, generated content, encrypted transcript path, and final DOCX path.
- `ThetaTemplate`: an uploaded custom PDF form template.
- `ThetaField`: one detected or reviewed fillable field in a Theta template, including label, key, type, page number, bounding box, and confidence.

The database is stored under the configured data directory. In Docker, this is mounted as `./backend/data:/app/data`, so runtime state survives container restarts.

## Workflow Pipelines

### 1. Volunteer Form Extraction

API module: `backend/app/api/volunteer.py`  
Service modules: `volunteer_form.py`, `excel_export.py`, and related LLM helpers.

The volunteer workflow turns paper-form photos into reviewed structured records and Excel exports:

1. A user creates a batch and uploads one or more form images.
2. Files are stored under `data/uploads/batch_{id}`.
3. A background task sets the batch to extraction mode and processes each image.
4. The vision channel extracts fields, confidence, bounding boxes, model/provider metadata, latency, and raw/error details.
5. The batch moves to pending review.
6. Optional text-model review can annotate or rewrite low-confidence values while preserving originals.
7. Human review writes final fields and records corrections.
8. The backend exports reviewed data to Excel files under `data/exports`.

The extraction service opens fresh database sessions inside background work. Image extraction is parallelized with a small thread pool to improve demo throughput without turning the app into a distributed worker system.

### 2. Home Visit and Meeting Notes

API module: `backend/app/api/home_visit.py`  
Service modules: `home_visit.py`, `visit_note_agent.py`, `transcriber.py`, `transcript_vault.py`, and DOCX rendering helpers.

This workflow converts an audio recording and a DOCX template into a structured, reviewed DOCX report:

1. The user creates a session with a title, optional note, mode, audio file, and DOC/DOCX template.
2. Files are stored under `data/visit_sessions/session_{id}`.
3. The backend runs extraction in phases: upload, extraction, review, rendering, confirmation, failure, or burn.
4. Audio transcription and template preparation can run concurrently.
5. DOC/DOCX templates are normalized and structurally analyzed.
6. The text model generates slot content according to the selected mode: home visit or internal meeting.
7. The transcript is encrypted with Fernet and stored under `data/transcripts`; the encryption key is stored as `data/.transcript_key`.
8. Only a transcript snippet is exposed for review.
9. After review, the backend renders the final DOCX into `data/exports/visit_notes`.
10. A burn operation can overwrite and delete the encrypted transcript file.

The real ASR path uses DashScope's native async transcription flow because the selected `fun-asr` model is not handled through the OpenAI-compatible audio endpoint. If ASR credentials are missing or mock mode is enabled, the system falls back to sample/demo behavior.

### 3. Welfare Form Autofill

API module: `backend/app/api/placeholder.py`, exposed as `/api/welfare-form`  
Service modules: `welfare_form_templates.py`, `welfare_form_extractor.py`, `welfare_form_mapping.py`, and `welfare_form_filler.py`.

This workflow maps elder profile data into PDF welfare forms:

1. The backend loads template manifests from `backend/data/form_templates/*.json`.
2. Built-in source PDFs live under `backend/data/templates`.
3. The user can start with a mock elder profile, raw text, or an uploaded image.
4. Profile extraction can use the AI layer when needed.
5. `preview-mapping` maps elder fields into template fields with defaults and optional text-model assistance for missing values.
6. `fill` renders the PDF output through PyMuPDF and writes it under `data/welfare_outputs`.
7. The generated file is returned through an `/api/files/...` download URL.

The form system supports both AcroForm-style field filling and coordinate/anchor-based insertion for PDFs without native fillable widgets.

### 4. Theta Custom PDF Template Builder

API module: `backend/app/api/theta.py`  
Service modules: `theta_extractor.py` and `theta_publish.py`.

Theta lets an operator convert an arbitrary PDF form into a reusable CareFlow welfare-form template:

1. A PDF is uploaded to `data/theta_pdfs`.
2. The backend creates a `ThetaTemplate`.
3. Each PDF page is rendered to an image.
4. The vision model detects blank fields and returns labels, keys, types, bounding boxes, and confidence scores.
5. Page-level failures are tolerated so one bad page does not discard the entire template.
6. The audit UI displays page images and detected boxes.
7. The reviewer edits fields and bounding boxes, then confirms the template.
8. Publishing converts relative image bounding boxes into PDF point coordinates and writes `data/form_templates/theta_{id}.json`.
9. The published template becomes available to the welfare-form autofill workflow.

## AI Provider Layer

CareFlow separates AI work into three channels:

- Text: DeepSeek official OpenAI-compatible API, defaulting to `deepseek-v4-flash`.
- Vision: Azure OpenAI or Azure AI Foundry, defaulting to a `gpt-5-mini` deployment.
- ASR: Bailian/DashScope, defaulting to `fun-asr`.

Each channel has its own settings and mock fallback checks. This allows a demo to run partially offline or with only some providers configured. The vision client includes compatibility handling for Azure OpenAI and Azure AI Foundry endpoints, including endpoint normalization, timeout configuration, and parameter adjustments for provider-specific constraints.

## File Handling and Privacy Boundaries

Runtime files are stored below the configured data directory:

- `uploads`: uploaded volunteer form photos.
- `exports`: generated Excel and DOCX outputs.
- `welfare_outputs`: generated welfare PDFs.
- `theta_pdfs`: uploaded custom PDF templates.
- `samples`: mock/demo samples.
- `welfare_templates`: template-related assets.
- `transcripts`: encrypted visit-note transcripts.

The `/api/files/{path:path}` endpoint only serves allow-listed subdirectories. It rejects path traversal, hidden path segments, the SQLite database file, and the transcript encryption key. This is important because the demo uses local file storage rather than a separate object store with independent access policies.

Visit-note transcripts are encrypted at rest before being stored. The application exposes only a short snippet during review and supports a burn operation to overwrite and unlink the encrypted transcript file.

## Deployment and Public Demo Security

The main demo deployment path is Docker Compose:

- `backend`: builds `careflow-backend:0.4.8`, runs FastAPI, mounts `./backend/data:/app/data`, and stays private inside the Compose network.
- `frontend`: builds `careflow-frontend:0.4.8`, serves the React bundle with Nginx, proxies `/api/*` to the backend, and binds only to `127.0.0.1:8080`.
- `cloudflared`: optional Cloudflare Tunnel sidecar or detached container that publishes the local frontend to a public HTTPS URL.

Nginx provides the first public-facing protection layer:

- Basic Auth for the demo site.
- API request rate limiting.
- Security headers such as frame denial, content-type sniffing prevention, referrer policy, and restricted browser permissions.
- Dotfile denial.
- A no-auth `/healthz` endpoint for container health checks.
- Large request support and long timeouts for upload and AI-backed workflows.

This is a reasonable public-demo guardrail, not a full production authentication model. For durable public access, the next security step should be Cloudflare Access or application-level user authentication, plus stricter role-based permissions and audit logging.

## Operational Boundaries

The current architecture is optimized for a fast, inspectable demo rather than multi-tenant production scale.

Key boundaries:

- Background jobs are in-process FastAPI tasks, so long-running work can be lost if the process restarts.
- SQLite and local files make the system easy to run, but they are not a multi-node storage design.
- Schema changes use SQLModel table creation and lightweight SQLite migrations, not Alembic.
- Basic Auth protects the whole demo but does not provide per-user identity, roles, or workflow-level authorization.
- AI provider calls can be long-running and network-dependent; mock fallbacks are available but should not be confused with real extraction quality.
- Some module names are historical. For example, `placeholder.py` currently contains the active welfare-form API.

## Fast Orientation for New Engineers

Start with these files:

1. `backend/app/main.py` to understand the backend entrypoint and registered route modules.
2. `backend/app/models.py` to understand persisted workflow state.
3. `backend/app/config.py` to understand runtime paths, provider settings, and mock modes.
4. `frontend/src/App.tsx` to understand the user-facing routes.
5. `frontend/src/lib/api.ts` to see how the frontend talks to the backend.
6. `frontend/nginx.conf` to understand the demo reverse proxy and public-facing protections.
7. `docker-compose.yml` to understand how the app runs locally and through a tunnel.

The fastest way to reason about CareFlow is to treat it as one React SPA and one FastAPI service sharing a local SQLite database and data directory, with AI provider calls plugged in at the service layer.
