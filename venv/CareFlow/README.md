# CareFlow 護流

> AI-powered administrative assistant for frontline elderly care workers.
> "你護老，我護你" — *We support those who care.*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-20232A?logo=react&logoColor=61DAFB)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

CareFlow is an open-source AI workstation designed for non-profit elderly care teams. It turns handwritten volunteer forms, home-visit voice memos, government welfare PDFs, and blank PDF templates into structured, reviewable, and auditable documents — with a strict **"AI drafts, humans confirm"** workflow.

All AI-extracted results remain in a `pending_review` state until a social worker explicitly confirms them. Personal data such as voice transcripts can be encrypted at rest and burned after review.

---

## Features

| Pipeline | Input | Output | Description |
|---|---|---|---|
| **α** Volunteer Form → Excel | Photos of handwritten forms | NGO-formatted `.xlsx` | Extracts fields from paper volunteer forms and writes them into existing Excel templates while preserving formatting, merged cells, and formulas. |
| **β** Home Visit Voice → Report | Cantonese audio + template | Structured JSON / `.docx` | Transcribes home-visit recordings and generates structured visit notes for review. |
| **γ** Welfare Form → Filled PDF | Elder profile + blank PDF | Completed PDF | Semi-automatically fills government welfare application forms. |
| **θ** Blank PDF → Reusable Template | Any blank PDF form | Field coordinates + bbox template | Learns the layout of arbitrary PDF forms so they can be reused in pipeline γ. |

Every pipeline shares the same side-by-side review interface:

- Confidence heatmap per field (red < 0.7, yellow 0.7–0.9, green ≥ 0.9)
- Click any field to see the source region or audio segment
- All corrections are stored for future prompt improvement
- One-click confirmation before writing to the final document

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│   React     │────▶│   FastAPI   │────▶│  SQLite / Tasks │
│  Frontend   │◀────│   Backend   │◀────│   (Celery)      │
└─────────────┘     └──────┬──────┘     └─────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   DeepSeek-V4        Azure GPT-5.1       DashScope fun-asr
   (text / reasoning) (vision / bbox)     (Cantonese ASR)
```

### Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLModel, Celery |
| Database | SQLite (single-node deployment) |
| Frontend | Vite, React 18, TypeScript, TailwindCSS |
| Text LLM | DeepSeek-V4-Pro / Flash (OpenAI-compatible) |
| Vision | Azure AI Foundry · GPT-5.1 |
| Speech | DashScope · fun-asr (Cantonese) |
| Excel | `openpyxl` |
| PDF | PyMuPDF |
| Encryption | Fernet (at-rest + burn-after-reading) |
| Deployment | Docker Compose |

The three LLM clients in [`backend/app/llm/client.py`](backend/app/llm/client.py) are independent: if one API key is missing, only that channel falls back to mock mode.

---

## Quick Start

### Docker (recommended)

```bash
# 1. Clone the repository
git clone https://github.com/OscarXuHz/CareFlow.git
cd CareFlow

# 2. Copy and edit environment variables
cp backend/.env.example backend/.env
# Fill in at least one provider key (all three are optional; missing ones use mock mode)

# 3. Start the stack
docker compose up -d

# 4. Open the app
open http://localhost:8080
```

For production deployments using pre-built images:

```bash
docker compose -f docker-compose.deploy.yml up -d
```

### Local Development

**Backend**

```bash
cd backend
uv venv && source .venv/bin/activate
uv pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

Then visit `http://localhost:5173`.

---

## Configuration

Copy `backend/.env.example` to `backend/.env` and configure the providers you want to use:

```env
# Text reasoning — DeepSeek
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com

# Vision extraction — Azure AI Foundry
AZURE_OPENAI_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-5.1
AZURE_OPENAI_API_VERSION=2024-05-01-preview
AZURE_OPENAI_MODEL=gpt-5.1

# Cantonese speech recognition — DashScope
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

> The Azure endpoint accepts the full Foundry project URL; the client wrapper automatically resolves it to the resource root and appends `/models`.

---

## Repository Layout

```
CareFlow/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Pydantic settings
│   │   ├── db.py                # SQLModel + SQLite
│   │   ├── llm/                 # LLM clients (DeepSeek / Azure / DashScope)
│   │   ├── services/            # Pipeline implementations
│   │   └── api/                 # REST endpoints
│   ├── alembic/                 # Database migrations
│   └── tests/                   # Test suite
├── frontend/
│   └── src/
│       ├── pages/               # Pipeline UI pages
│       ├── components/          # Shared UI components
│       └── lib/                 # API client and utilities
├── docs/                        # Architecture and meeting guides
├── docker-compose.yml
├── docker-compose.deploy.yml
└── backend/.env.example
```

---

## Contributing

We welcome contributions from developers, designers, social workers, and translators.

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Make your changes and add tests where possible
4. Run the test suite: `cd backend && pytest`
5. Commit with a clear message and open a pull request

Please keep the **"AI drafts, humans confirm"** principle in mind when modifying any pipeline: AI output must never be written directly to a final document without explicit human approval.

For detailed architecture and design decisions, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Privacy & Safety

- All AI extractions start in `pending_review` and require explicit confirmation.
- Voice transcripts are encrypted at rest with Fernet and can be burned after review.
- No personal data is sent to any provider unless the corresponding API key is configured.
- Basic Auth credentials for public demos are kept in `frontend/.htpasswd.local`, which is never committed.

---

## License

CareFlow is released under the [MIT License](./LICENSE).

---

## Acknowledgements

CareFlow was built for frontline elderly care workers in Hong Kong. Special thanks to the NGOs and social workers who shared their workflows and helped shape the review-first design.

For the original internal documentation (in Traditional Chinese), see [`README.internal.md`](./README.internal.md).
