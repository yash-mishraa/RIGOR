# RIGOR controlled deployment guide

This guide prepares a private or controlled deployment. It does not provision infrastructure or deploy. **Do not enable public multi-user traffic until the ownership and authorization work below is complete.**

## Current deployment boundary

The Vite frontend can be hosted as a static Vercel site. FastAPI and PostgreSQL run separately. The backend has no sign-in, tenant model, ownership enforcement, retention policy, or protected reviewer identity. Imported job descriptions, plans, sessions, and candidate answers are shared in the configured database. UUIDs are identifiers, not access control. Keep the API private behind an access-controlled network or gateway, and use synthetic data until the blockers are addressed.

Resume matching endpoints process submitted text transiently and do not store it. A legacy `Resume` table exists but current product routes do not write to it. Candidate answers and imported job descriptions are stored, and there is no user-facing deletion or retention implementation yet.

## Frontend (Vercel)

1. Import the repository with its root as the Vercel project root.
2. Use `npm ci` for installation, `npm run build` for the build, and `dist` as the output directory (also recorded in `vercel.json`).
3. Set `VITE_API_BASE_URL` to the HTTPS API base, including `/api/v1`, separately for production and preview environments.
4. Never put `OPENAI_API_KEY`, database credentials, or backend secrets in a `VITE_*` variable. Vite embeds those values into downloadable JavaScript.
5. Point preview deployments at a non-production API and database. Browser resume parsing libraries currently load from public CDNs; self-host them if your environment requires tighter supply-chain control.

## Backend and PostgreSQL

1. Provision PostgreSQL with TLS, automated backups, restricted network access, and a dedicated least-privilege application role. Keep production credentials separate from local Compose defaults.
2. Build the backend container with `backend/` as the Docker build context. The image uses committed `uv.lock` and installs the optional OpenAI extra. Do not copy `.env` into an image.
3. Configure `DATABASE_URL` with the host's PostgreSQL connection string in SQLAlchemy async form (`postgresql+asyncpg://...`). Follow the provider's supported SSL options and use a connection pool that respects its connection limit.
4. Set `CORS_ORIGINS` to an exact comma-separated list of deployed frontend origins. Do not use `*`. CORS is not authentication.
5. Keep `AI_PROVIDER=none` until AI is intentionally enabled. To enable it, set `AI_PROVIDER=openai`, `AI_MODEL`, and `OPENAI_API_KEY` only in the backend secret manager. Set timeouts, output-token limits, and `AI_REQUESTS_PER_MINUTE` conservatively. Optional `AI_INPUT_COST_PER_MILLION_USD` and `AI_OUTPUT_COST_PER_MILLION_USD` are operator-supplied estimates; RIGOR labels the derived amount as an estimate. Verify current provider pricing before setting them.
6. Release step: run `uv run alembic upgrade head` from the backend image/release command with the same database URL, then start `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT` (or the platform equivalent). Do not use `--reload` in production. The current container default listens on 8000; configure the host to route to it.
7. Set liveness to `GET /api/v1/health` (process only) and readiness to `GET /api/v1/ready` (database and current migration required). Readiness reports AI configuration only; it never calls OpenAI or claims provider reachability.
8. Verify the deployed frontend URL, health/readiness, browser CORS preflight, and a non-sensitive catalogue read before directing controlled users to it. Do not use a live AI call as a health check.

## Rollback and recovery

- Take a managed database backup before a schema release and test restore procedures on a separate database.
- Prefer forward-compatible additive migrations. Roll back the application image first if a release fails. Do not automatically downgrade a migration or delete tables containing user content.
- Restore a database backup only through the host's documented recovery process and with an explicit recovery point decision. Preserve the failed release identifier and migration revision for diagnosis.
- Keep frontend and backend release identifiers so Vercel and the API image can be rolled back independently.

## Ownership and route access plan before public launch

Identity must come from a verified authentication layer, not a caller-supplied user ID. Resolve the principal on every request; persist its stable subject on private rows; scope every read/write by that subject; and return 404 for objects outside the caller's ownership. Reviewer actions need an administrator/reviewer role and audit record. Add deletion/export and retention jobs before collecting real resumes or answers.

| Data / routes | Intended classification | Required authorization after auth ships |
| --- | --- | --- |
| `GET /health`, `GET /ready` | Operational status | Public to platform probes; apply edge limits if exposed |
| Curated `GET /questions`, `GET /questions/{id}`, `GET /learning-modules`, `GET /learning-modules/{id}` | Global reviewed catalog | Read-only; hide pending/rejected question states |
| `GET /jobs`, `GET /jobs/{id}`, `/skills`, `/content-coverage` | Mixed catalog and user imports | Global only for curated/demo rows; private scope for user imports |
| `POST /jobs/import`, `POST /jobs/{id}/analyse`, `/generate-questions` | User job content and derived AI data | Authenticated owner; private job ownership; AI abuse quota |
| `POST /resume-job-matches`, `POST /resumes/analyse` | Transient resume content | Authenticated caller; explicit consent for external processing; never persist request text |
| `POST /preparation-plans`, `GET /preparation-plans/{id}` | User preparation data | Plan owner and owned job; generated items must be reviewed |
| `POST /practice-sessions`, `GET/POST /practice-sessions/{id}/*` | Private practice and candidate answers | Session owner through plan/job chain; restrict answer/evaluation reads to owner |
| `POST /questions/{id}/review` | Global catalog mutation | Reviewer/admin role only; record reviewer, decision, and timestamp |

Implementation tasks: add a principal abstraction and identity provider; add owner foreign keys and backfill existing rows in a controlled migration; create per-user access helpers and tests for every route above; make import deduplication tenant-scoped; protect generation/review operations; implement user deletion cascades/retention and export; then add distributed edge/API quotas and audit logs. Foreign keys alone do not enforce authorization.

## Current controls and remaining blockers

- Current controls: exact-origin CORS; bounded request body and field sizes; no server-side URL fetching; ORM-bound SQL; no file upload endpoint; transient resume matching; 30-second AI timeout; zero SDK retries; a per-process AI request limiter; Pydantic structured outputs; pending review for generated questions; privacy-allowlisted JSON logs.
- Still required for public launch: authentication; ownership for imported jobs/plans/sessions/responses; reviewer authorization; retention/deletion and export; distributed abuse controls; production secrets and TLS; database backup/restore validation; security review of hosting proxy configuration. The in-process limiter is not shared across worker processes and is not a replacement for an edge/API gateway quota.
