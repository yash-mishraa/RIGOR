# RIGOR Interview Workbench

RIGOR is a browser-based technical interview practice and resume review workbench with a new optional FastAPI/PostgreSQL service for job-specific preparation. The established resume parser, ATS-style heuristics, interview drills, evaluation, progress ledger, and preferences remain in the Vite frontend. Resume import stays local to the browser; this initial backend does not receive resume text.

## Architecture and current workflow

- **Frontend:** vanilla JavaScript ES modules, static HTML, and CSS served by Vite. Resume PDF/DOCX parsing loads browser libraries from public CDNs. Practice records and the current resume buffer remain in browser local storage.
- **Backend:** Python 3.12+, FastAPI, Pydantic request validation, SQLAlchemy async sessions, PostgreSQL, and Alembic. `src/api.js` is the dedicated frontend API client; the current interface degrades gracefully while the API is offline.
- **Database:** companies, jobs and version history, canonical skills/aliases and role mappings, reusable questions and role/skill mappings, skill-linked learning modules, resumes and evidence, preparation plans, persisted plan items, sessions, and responses. `0002_content_engine` adds the content-engine schema without editing the already-applied `0001_initial` migration.
- **Workflow:** import a pasted job post or browse the catalogue, inspect extracted fields and skill evidence, then build a persisted plan with ranked questions, learning modules, explicit match reasons, and content gaps. Imports create a default plan; selected jobs can also receive additional plans.
- **Analysis:** deterministic taxonomy matching with whole-phrase boundaries, explainable content ranking, conservative duplicate matching, and historical versions. No LLM or paid provider is required. Source URLs are stored and normalized for duplicate detection; the server does not fetch them.
- **Curated catalogue:** 46 reviewed practice questions map to 10 role families; 12 reusable learning modules cover high-value shared skills. The content is authored for RIGOR and is not represented as employer-sourced interview questions. Current mapped question counts are backend 23, data analyst 10, data engineer 13, distributed systems 12, frontend 11, ML engineer 7, platform/DevOps 13, QA automation 12, security 7, and systems 9. A question can map to multiple families. This is below the 300–500 target; expand the seed with similarly validated entries.
- **Next steps:** improve content breadth, add richer resume evidence and retention/deletion, persist practice responses/evaluations, then add an optional provider-based LLM behind validation/review. Add authentication and per-user ownership before public deployment.

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

Use Python 3.12 or newer:

```sh
cd backend
uv sync --extra dev
cp ../.env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

`uv sync` creates the virtual environment and selects Python 3.12 or newer. Alternatively, create a Python 3.12+ virtual environment and run `pip install -e '.[dev]'`, then invoke `alembic` and `uvicorn` inside it. The API docs are at `http://127.0.0.1:8000/docs`; readiness is exposed at `/api/v1/health` (`status` describes app availability and `database` reports database connectivity).

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

- `GET /api/v1/health`
- `GET /api/v1/jobs?q=python&role_family=backend&skill=Postgres&status=active&sort=relevance&limit=20&offset=0` (also filters seniority, location, and employment type)
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/import` with `role_title`, `description` (80–30,000 chars), and optional company/location/seniority/employment type/source URL. URL/title/company duplicates are reused; changed content creates a new job version.
- `GET /api/v1/jobs/{job_id}/skills`
- `GET /api/v1/jobs/{job_id}/content-coverage`
- `POST /api/v1/jobs/{job_id}/analyse`
- `POST /api/v1/preparation-plans` with `job_id` and optional `question_limit` (1–50); `GET /api/v1/preparation-plans/{plan_id}`
- `GET /api/v1/questions?q=retry&role_family=backend&skill=Python&category=api_design&difficulty=intermediate&limit=30&offset=0`; `GET /api/v1/questions/{question_id}`
- `GET /api/v1/learning-modules?skill=SQL&limit=30&offset=0`; `GET /api/v1/learning-modules/{module_id}`

Question ranking uses configurable weights in `backend/app/services.py`: up to 50 points for required-skill coverage (distributed across required skills), 18 for preferred-skill coverage, 22 for role-family relevance, 10 for matching competencies, and 5 for seniority/difficulty alignment. The planner adds small diversity and uncovered-required-skill bonuses when sequencing questions. Scores explain catalogue relevance; they are not validated predictions of interview performance. Coverage reports missing skills and role categories instead of substituting unrelated questions.

Frontend API base defaults to `http://127.0.0.1:8000/api/v1`; configure `VITE_API_BASE_URL` at Vite build/dev time if needed. Backend configuration lives in `.env` (see `.env.example`): `DATABASE_URL` and comma-separated `CORS_ORIGINS`.

## Privacy, security, and deployment limits

There is no authentication, tenant ownership, or authorization yet. Imported job descriptions are shared in the local database. Do not deploy this API publicly until authentication, per-user ownership checks, rate limits for expensive operations, privacy/retention controls, and production secrets are implemented. No resume content is sent to the backend or an LLM. Job source URLs are stored as metadata and are not fetched server-side. File uploads and external job ingestion are not implemented. CORS is restricted to configured origins.

## Verification

Run backend unit/API tests and formatting checks from `backend/`, plus the frontend production build from the repository root:

```sh
uv run pytest app/tests -q
uv run ruff check app alembic
npm run build
```

For the PostgreSQL integration test, point the test explicitly at a local test database whose contents may receive a temporary uniquely named job that the test deletes afterward:

```sh
RIGOR_TEST_DATABASE_URL='postgresql+asyncpg://rigor:rigor@localhost:5432/rigor' uv run pytest app/tests -q
```
