# RIGOR Interview Workbench

RIGOR is a browser-based technical interview practice and resume review workbench with an optional FastAPI/PostgreSQL service for job-specific preparation. Resume files are parsed in the browser; the existing ATS-style heuristics, interview drills, progress ledger, and preferences remain available locally. Resume text reaches the configured backend only when the user explicitly requests resume/job matching, and is processed transiently.

## Architecture and current workflow

```mermaid
flowchart LR
  Browser[Vanilla JS + Vite] -->|REST; explicit resume match only| API[FastAPI]
  Browser -->|local workbench + resume parsing| Local[Browser storage]
  API -->|SQLAlchemy async| DB[(PostgreSQL + Alembic)]
  API -->|optional, bounded requests| AI[OpenAI API]
```

- **Frontend:** vanilla JavaScript ES modules, static HTML, and CSS served by Vite. Resume PDF/DOCX parsing loads browser libraries from public CDNs. Practice records and the current resume buffer remain in browser local storage.
- **Backend:** Python 3.12+, FastAPI, Pydantic request validation, SQLAlchemy async sessions, PostgreSQL, and Alembic. `src/api.js` is the dedicated frontend API client; the current interface degrades gracefully while the API is offline.
- **Database:** companies, jobs and version history, canonical skills/aliases and role mappings, reusable questions and role/skill mappings, skill-linked learning modules, resumes and evidence, preparation plans, persisted plan items, sessions, and responses. `0002_content_engine` and `0003_personalised_practice` are additive; applied migrations are not edited.
- **Workflow:** import a pasted job post or browse the catalogue, inspect extracted fields and skill evidence, then build a persisted plan with ranked questions, learning modules, explicit match reasons, and content gaps. Imports create a default plan; selected jobs can also receive additional plans.
- **Analysis:** deterministic taxonomy matching with whole-phrase boundaries, explainable content ranking, conservative duplicate matching, and historical versions. No LLM or paid provider is required. Source URLs are stored and normalized for duplicate detection; the server does not fetch them.
- **Stage 3 AI:** optional structured OpenAI integration for evidence-checked job analysis, gap-focused question drafts, and rubric feedback. Provider calls happen only after an explicit UI action or answer-level consent. The default provider is `none`; it does not silently switch models or providers. Existing deterministic analysis and practice work without a key.
- **Resume matching:** PDF, DOCX, TXT, and Markdown extraction remains in the browser. Matching sends the text to the configured RIGOR backend for transient deterministic analysis; it is not written to the database or sent to an AI provider. Evidence distinguishes demonstrated action-oriented lines from keyword-only mentions.
- **Practice lifecycle:** practice sessions, text responses, evaluations, progress, and the unanswered queue persist in PostgreSQL. Assessment modes hide references before submission. Local feedback is a keyword heuristic; optional AI feedback is approximate and requires a checkbox for each answer. Generated questions remain pending review until explicitly approved.
- **Curated catalogue:** 46 reviewed practice questions map to 10 role families; 12 reusable learning modules cover high-value shared skills. The content is authored for RIGOR and is not represented as employer-sourced interview questions. Current mapped question counts are backend 23, data analyst 10, data engineer 13, distributed systems 12, frontend 11, ML engineer 7, platform/DevOps 13, QA automation 12, security 7, and systems 9. A question can map to multiple families. This is below the 300–500 target; expand the seed with similarly validated entries.
- **Project scope:** RIGOR is a portfolio project and public demonstration, not a production SaaS. Login, signup, roles, and multi-tenant accounts are intentionally excluded. Remaining launch work is demo-state isolation, bounded public writes, safe catalogue administration, reproducible deployment, and end-to-end UI validation. See the prioritized list below and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Run locally

### Frontend

```sh
npm install
npm run dev
```

Build/preview with `npm run build` and `npm run preview`. The frontend works without the backend; the job import panel displays the service connection state.

### PostgreSQL

Docker Compose starts PostgreSQL 16 and stores data in a named volume:

```sh
docker compose up -d db
```

The compose credentials are for local development only. Do not expose this database publicly.

### Backend

Use Python 3.12 or newer. For optional OpenAI features, install the provider extra:

```sh
cd backend
uv sync --extra dev --extra ai
cp ../.env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

`uv sync` creates the virtual environment and selects Python 3.12 or newer. Alternatively, create a Python 3.12+ virtual environment and run `pip install -e '.[dev]'`, then invoke `alembic` and `uvicorn` inside it. The API docs are at `http://127.0.0.1:8000/docs`; `/api/v1/health` checks process health and `/api/v1/ready` checks database and migration readiness without calling OpenAI.

AI stays disabled with the checked-in `.env.example`. To enable OpenAI, set `AI_PROVIDER=openai`, choose `AI_MODEL`, and set `OPENAI_API_KEY` in the private backend environment; the key is only read by backend settings. No key is required for startup, tests, resume matching, catalogue browsing, or local practice. The adapter uses structured outputs, a 30-second timeout, zero SDK retries, at most five generated questions per request, a configurable 3,000-token output ceiling, and a local per-process limit of 10 AI requests per minute. Usage logs include token counts when the provider reports them. Optional input/output per-million-token rates can produce an explicitly estimated cost; the rates are operator supplied and must be checked against current pricing. Readiness reports configuration only and does not test provider connectivity.

`QUESTION_REVIEW_TOKEN` is an optional backend-only operator capability for approving or rejecting generated questions. With no token configured, review is disabled. Never expose it in browser variables or commit its value.

Seed reviewed questions, learning modules, canonical aliases, and role-skill mappings without adding fictional jobs:

```sh
uv run python -m app.seed
```

The seed is repeatable and version-aware. To explicitly add fictional catalogue examples, all marked `DEMO` in the UI and `is_demo=true` in the database:

```sh
uv run python -m app.seed --include-demo-jobs
```

This local database has 10 such demonstration listings. They are not live vacancies.

## API slice

- `GET /api/v1/health` (application process)
- `GET /api/v1/ready` (database connection, migration head, and non-secret AI configuration status)
- `GET /api/v1/jobs?q=python&role_family=backend&skill=Postgres&status=active&sort=relevance&limit=20&offset=0` (also filters seniority, location, and employment type)
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/import` with `role_title`, `description` (80–30,000 chars), and optional company/location/seniority/employment type/source URL. URL/title/company duplicates are reused; changed content creates a new job version.
- `GET /api/v1/jobs/{job_id}/skills`
- `GET /api/v1/jobs/{job_id}/content-coverage`
- `POST /api/v1/jobs/{job_id}/analyse` with `{"use_ai": true}` explicitly requests provider-assisted analysis; results are cached by job description version, provider, and model. Transient provider failures return deterministic analysis; provider authentication/model configuration errors return a clear 503.
- `POST /api/v1/resumes/analyse` with `resume_text` returns transient structured evidence and does not persist the resume.
- `POST /api/v1/resume-job-matches` with `job_id` and `resume_text` returns evidence-backed strengths, gaps, project connections, and study priorities; it does not call an external AI provider.
- `POST /api/v1/jobs/{job_id}/generate-questions` with optional `max_questions` (1–5) generates only for uncovered skills. Drafts are duplicate-checked, cached, tagged `ai_generated`, and stay `generated_pending_review` and are excluded from the shared reviewed catalogue until an operator approves them through `POST /api/v1/questions/{question_id}/review` with `{"decision":"approve"}` and the backend-only `X-Review-Token` capability. With no `QUESTION_REVIEW_TOKEN` configured, review is disabled.
- `POST /api/v1/preparation-plans` with `job_id` and optional `question_limit` (1–50); `GET /api/v1/preparation-plans/{plan_id}`
- `POST /api/v1/practice-sessions` with a `plan_id` and mode (`guided_practice`, `technical_mock`, `resume_deep_dive`, or `behavioral`); `GET /api/v1/practice-sessions/{session_id}` resumes the current question; `POST /api/v1/practice-sessions/{session_id}/responses` saves/evaluates an answer; `POST .../{session_id}/next` retrieves the current state; `GET .../{session_id}/results` returns feedback and a weak-skill revision queue.
- `GET /api/v1/questions?q=retry&role_family=backend&skill=Python&category=api_design&difficulty=intermediate&limit=30&offset=0`; `GET /api/v1/questions/{question_id}`
- `GET /api/v1/learning-modules?skill=SQL&limit=30&offset=0`; `GET /api/v1/learning-modules/{module_id}`

Question ranking uses configurable weights in `backend/app/services.py`: up to 50 points for required-skill coverage (distributed across required skills), 18 for preferred-skill coverage, 22 for role-family relevance, 10 for matching competencies, and 5 for seniority/difficulty alignment. The planner adds small diversity and uncovered-required-skill bonuses when sequencing questions. Scores explain catalogue relevance; they are not validated predictions of interview performance. Coverage reports missing skills and role categories instead of substituting unrelated questions.

Frontend API base defaults to `http://127.0.0.1:8000/api/v1`; configure `VITE_API_BASE_URL` at Vite build/dev time if needed. Backend configuration lives in `.env` (see `.env.example`): `DATABASE_URL` and comma-separated `CORS_ORIGINS`.

## Privacy, security, and deployment limits

RIGOR intentionally has no accounts, login, roles, or tenant model. A shared demonstration database therefore must contain fictional/sample data only until per-browser demo-state isolation and public write limits are complete. Imported job descriptions, plans, sessions, and candidate answers currently share the configured database. Generated questions stay pending and hidden from the reviewed catalogue; operator review requires the backend-only `QUESTION_REVIEW_TOKEN`. Do not expose the current write-enabled API as an unrestricted public demo until demo isolation, non-AI API abuse controls, and catalogue write boundaries are implemented. Resume text is sent to the configured RIGOR backend only when the user requests matching; it is not saved or sent to an LLM. If AI answer feedback is checked, the submitted answer is sent to the configured provider. Job source URLs are metadata and are not fetched server-side. File uploads and external job ingestion are not implemented. CORS is restricted to configured origins and does not provide access control.

The Vite frontend is configured for Vercel. The simplest currently documented backend path is a separate FastAPI host plus managed PostgreSQL, with `VITE_API_BASE_URL` set to the service. Vercel’s Python Functions runtime can run FastAPI, but this app also needs persistent external PostgreSQL and must be adapted and verified for serverless execution; this repository does not yet ship that adapter. Deployment is not yet verified end to end. The intended public release is a limited portfolio demo with fictional data, not a public multi-user SaaS or a place to submit sensitive resumes.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for frontend/backend/database deployment guidance, migration, health check, and rollback. The image uses the committed `backend/uv.lock`; build it with `backend/` as the Docker context. Request bodies are capped at 200 KB by default. The per-process AI limiter is not a distributed public abuse control.

## Verification

Run backend unit/API tests and formatting checks from `backend/`, plus the frontend production build from the repository root:

```sh
uv run pytest app/tests -q
uv run ruff check app alembic
npm run build
```

Run the deterministic synthetic quality evaluation from `backend/`:

```sh
uv run python -m app.evaluations.run_quality --mode deterministic
```

Its fixture dataset and runner are under `backend/evaluations/` and `backend/app/evaluations/`. The OpenAI integration smoke test makes exactly one request and is skipped by default. Opt in explicitly only when prepared to incur a provider charge:

```sh
RIGOR_RUN_OPENAI_INTEGRATION=1 uv run pytest app/tests/test_openai_live.py -q -s
```

Model-dependent dataset evaluation is separate and makes three requests for each of five synthetic role cases. It is never part of default tests:

```sh
RIGOR_RUN_AI_EVALUATIONS=1 uv run python -m app.evaluations.run_quality --mode openai --output evaluation-result.json
```

That run records UTC timestamp, model, prompt-template and dataset versions, token configuration, request count, and aggregate/per-case metrics; it does not store secrets or source text. A result is evidence on this synthetic fixture only, not a production-quality guarantee.

For the PostgreSQL integration test, point the test explicitly at a local test database whose contents may receive a temporary uniquely named job that the test deletes afterward:

```sh
RIGOR_TEST_DATABASE_URL='postgresql+asyncpg://rigor:rigor@localhost:5432/rigor' uv run pytest app/tests -q
```


## What works and what remains

- **Implemented:** reviewed question and learning catalogues, deterministic job analysis and ranking, preparation plans, resume evidence matching (transient), persistent practice sessions, deterministic answer feedback, optional structured OpenAI job analysis/question generation/answer feedback, generated-question draft state, health/readiness routes, and offline quality fixtures.
- **Deterministic fallback:** job extraction, resume matching, question planning, and answer feedback remain available without OpenAI. AI-specific analysis, generation, and feedback report when unavailable instead of silently switching providers.
- **Not complete for a public demo:** per-browser isolation/reset of persisted demo progress; non-AI write abuse limits and safe boundaries for public job imports; seeded reviewed demo jobs/modules and a sample resume-match walkthrough in the UI; complete UI loading/error/navigation audit; live configured-provider validation; repeatable hosted deployment verification; screenshots/GIF.
- **Required before launch:** finish those demo tasks, run the documented checks from a clean checkout, verify a real OpenAI smoke call with a private key, deploy frontend/backend/PostgreSQL, and verify the complete candidate flow with fictional data. Authentication and SaaS multi-tenancy are not launch requirements.
- **Optional later:** broaden reviewed content while preserving quality; add semantic matching only if it improves evidence-backed matching and remains explicitly consented.
