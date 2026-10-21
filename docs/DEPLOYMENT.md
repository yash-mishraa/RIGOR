# RIGOR portfolio demo deployment

RIGOR is a portfolio demonstration, not a production SaaS. The intended public demo uses fictional/sample content and does not ask visitors to create accounts or upload real resumes. Login, roles, and multi-tenant ownership are intentionally out of scope.

## Deployment shape

- **Frontend:** deploy the Vite static build from the repository root to Vercel (`npm ci`, `npm run build`, output `dist`, already configured in `vercel.json`). Set `VITE_API_BASE_URL` to the deployed API URL ending in `/api/v1`.
- **Backend:** use a separate persistent FastAPI web service built from `backend/Dockerfile` with `backend/` as the Docker context. Run the image command with the host-provided port, for example `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- **Database:** use managed PostgreSQL with TLS and private networking from the backend where available. Set `DATABASE_URL` in the backend secret manager using SQLAlchemy async form (`postgresql+asyncpg://...`). Run `uv run alembic upgrade head` as the release migration command before serving traffic.

Vercel's Python Functions runtime supports FastAPI, but is currently documented as beta. RIGOR's async database lifecycle, connection pooling, migrations, and request limits have only been validated in the container/long-running service shape; this repository does not include a Vercel Python function adapter or verify serverless database connection behavior. Keep the frontend on Vercel and backend/database separate for the first reproducible demo deployment. Re-evaluate the [Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python) only after a deployment spike confirms those constraints.

A straightforward separate-host option is a Render web service plus Render Postgres; follow their current [FastAPI deployment](https://render.com/docs/deploy-fastapi) and [Postgres setup](https://render.com/docs/postgresql) documentation. This repository does not provision or verify a hosted environment yet.

## Environment configuration

Start from `.env.example` and configure backend values in the backend host's secret manager:

- `DATABASE_URL`: managed PostgreSQL URL.
- `CORS_ORIGINS`: exact Vercel production origin(s); do not use `*`.
- `AI_PROVIDER=none` by default. To enable the paid feature, set `AI_PROVIDER=openai`, `AI_MODEL`, and `OPENAI_API_KEY` on the backend only.
- `AI_TIMEOUT_SECONDS`, `AI_MAX_GENERATION_BATCH`, `AI_MAX_OUTPUT_TOKENS`, and `AI_REQUESTS_PER_MINUTE`: conservative request bounds. The AI limiter is in-process and does not provide distributed abuse protection.
- `QUESTION_REVIEW_TOKEN`: optional backend-only operator capability. Without it, generated-question review is disabled. Never place it in frontend variables.
- `MAX_REQUEST_BYTES`: request-body cap; default is 200 KB.

Never use a `VITE_*` variable for database credentials, the OpenAI key, or the review token. Vite publishes those values in browser JavaScript.

## Release checks

1. Seed reviewed content and fictional demo listings in the database. Use `uv run python -m app.seed --include-demo-jobs` only for explicitly fictional sample jobs; they are marked `DEMO`.
2. Apply migrations with `uv run alembic upgrade head` and confirm `GET /api/v1/health` and `GET /api/v1/ready`.
3. Set Vercel's `VITE_API_BASE_URL`, deploy the frontend, and verify CORS and catalogue reads from the deployed origin.
4. Walk through job analysis, plan creation, resume matching with fictional text, practice response submission, and results. Test AI only when intentionally configured; the live smoke test costs a provider request.
5. Confirm no real resumes or sensitive answers were used, no secrets are in frontend bundles/logs/Git, and the public write boundaries below are in place before opening the demo broadly.

## Current public-demo boundary

The API has no identity system by design. Job imports, preparation plans, practice sessions, and candidate answers are currently stored in a shared database. Resume matching itself is transient, but answer text is persisted. Current UI/local storage and backend data do not yet provide per-browser demo isolation or a reset action. The question review route is protected by the optional operator token, and generated drafts are hidden from the reviewed catalogue unless approved. CORS is not access control.

**Do not open the current write-enabled API to unrestricted public traffic yet.** Before launch, complete these portfolio-demo safeguards (no accounts required):

1. Seed reviewed sample jobs/questions/modules and a fictional resume-match walkthrough.
2. Add an opaque per-browser demo session identifier and scope persisted plans, sessions, and answers to it; provide a reset that removes only that session's progress.
3. Apply endpoint-specific non-AI request limits and maximum active/demo data quotas; make the public demo use seeded jobs and prevent arbitrary users from changing reviewed catalogue content.
4. Confirm AI limits at the hosting edge or with another shared quota mechanism; the current in-process limiter is only a local safeguard.
5. Add a clear demo privacy notice, short retention/reset policy, and UI states for unavailable AI/backend errors.
6. Verify the hosted frontend, API, and database end to end using synthetic data and document the actual tested release setup.

This is a small public-demo boundary, not a production identity or multi-user SaaS program. Do not collect real resume text or claim sensitive-workload readiness.

## Rollback and recovery

- Enable the database provider's managed backups and test a restore on a separate database before launch.
- Prefer additive, forward-compatible migrations. Roll back the app image first when possible; do not automatically downgrade or delete content tables.
- Keep frontend and backend release identifiers so each can be rolled back independently.
