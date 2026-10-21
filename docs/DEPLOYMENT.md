# RIGOR portfolio demo deployment

RIGOR is a portfolio demonstration, not a production SaaS. Use fictional/sample content only. It has no accounts or recovery flow; a browser's signed demo cookie is the credential for that browser's progress. Do not invite visitors to submit sensitive resumes or answers.

## Deployment shape

- **Frontend:** Vercel static Vite build from the repository root (`npm ci`, `npm run build`, output `dist`; `vercel.json` is checked in). Set `VITE_API_BASE_URL` to the backend URL ending in `/api/v1`.
- **Backend:** a persistent FastAPI web service built from `backend/Dockerfile`, with `backend/` as the Docker build context. Start with `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- **Database:** managed PostgreSQL with TLS and private networking where available. Configure SQLAlchemy async `DATABASE_URL` (`postgresql+asyncpg://...`) in the backend secret manager. Apply `uv run alembic upgrade head` before serving the new release.

Render web service plus managed PostgreSQL is one supported deployment shape; follow the provider's current [web service](https://render.com/docs/web-services), [PostgreSQL](https://render.com/docs/postgresql), and [health check](https://render.com/docs/health-checks) documentation. Vercel's [Python Functions runtime](https://vercel.com/docs/functions/runtimes/python) is documented separately and has not been validated with this app's async database lifecycle or connection pool. Keep the backend persistent unless a serverless deployment is independently adapted and verified.

No hosted service, database, DNS, or domain has been provisioned for this repository. Production environment values and release checks below are a runbook; they are not evidence of a live deployment.

## Production configuration

Set backend secrets and configuration in the backend host (never in Vite `VITE_*` variables):

- `APP_ENV=production`.
- `DATABASE_URL`: managed PostgreSQL URL with TLS settings required by the provider.
- `CORS_ORIGINS`: comma-separated exact HTTPS frontend origins; do not use `*`.
- `DEMO_SESSION_SECRET`: unique random secret of at least 32 characters. Do not reuse the local example secret.
- `DEMO_COOKIE_NAME=__Host-rigor_demo`, `DEMO_COOKIE_SECURE=true`, `DEMO_COOKIE_SAMESITE=none`. Production settings validation rejects insecure or non-`__Host-` cookies.
- `DATABASE_POOL_SIZE`, `DATABASE_POOL_MAX_OVERFLOW`, and `DATABASE_POOL_TIMEOUT_SECONDS`: fit total pool capacity to the database connection limit and all service instances.
- `DEMO_*` limits: tune request and per-session data ceilings for the expected demo size. Request quotas use atomic PostgreSQL counters and are shared across backend instances.
- `AI_PROVIDER=none` by default. If deliberately enabling paid calls, configure `AI_PROVIDER=openai`, `AI_MODEL`, and `OPENAI_API_KEY` on the backend only. `AI_REQUESTS_PER_MINUTE` and output bounds are enforced server side. Do not put the API key in a browser build.
- `QUESTION_REVIEW_TOKEN`: optional backend-only operator capability. Leave unset to disable review. Never expose it to the frontend.
- `MAX_REQUEST_BYTES`: request-body cap, 200 KB by default.

For production, use HTTPS throughout. The session cookie is `HttpOnly`, `Secure`, and host-only. If the Vercel frontend and backend are on different sites (for example `*.vercel.app` and `*.onrender.com`), browsers may block third-party cookies even with `SameSite=None`. A reliable public demo should use same-site custom domains for the frontend and API, or a same-origin proxy. Custom-domain DNS changes require the project owner's action and are not part of this repository setup.

## Release procedure

1. Create the managed PostgreSQL database and backend service in the provider dashboard. Set secrets and verify connectivity.
2. Run migrations with `uv run alembic upgrade head`, then seed the shared reviewed catalogue and fictional listings with `uv run python -m app.seed`. The seed is idempotent; demo listings are included by default and labeled fictional.
3. Confirm `GET /api/v1/health` and `GET /api/v1/ready`. Readiness checks database/migration state and reports only non-secret AI configuration; it does not make a provider call. Use provider health checks for `/api/v1/health`.
4. Configure the exact HTTPS frontend origin, cookie settings, and frontend `VITE_API_BASE_URL`; build and deploy the Vite site.
5. From a clean browser profile, verify session creation, shared job browsing, fictional resume matching, plan creation, practice answer submission/results, reload/resume, and reset. Open a second profile and verify it cannot read or delete the first profile's progress. Inspect the browser network panel to confirm cookies and CSRF marker work.
6. Use fictional inputs only. Verify that reset leaves shared jobs, questions, and learning modules intact. Confirm the built frontend contains no backend secrets.
7. Test OpenAI only if the provider is configured and the operator explicitly opts in. The live smoke test makes one paid request; the regular test suite does not call the provider.

Do not announce the deployment as verified until the hosted release passes those checks. This repository does not provision hosting or DNS.

## Data boundaries and operations

Public routes cannot create or edit shared catalogue questions. Generated questions are private to the originating demo session and remain pending review. The review route requires `QUESTION_REVIEW_TOKEN`. Public job imports, plans, practice sessions, answers, resume operations, AI operations, and demo-session creation are bounded by quotas; PostgreSQL counters coordinate backend instances. A database outage prevents quota-backed writes rather than falling back to per-process counters.

Session data expires with the signed session's server-side expiry; reset deletes only the current browser session's imported jobs and progress. Expired sessions are cleaned during new session initialization. Review data retention and backups at the host must match the portfolio-demo policy; avoid storing real personal information. Configure managed backups and test a restore before inviting visitors. Database logs and application logs must not include secrets or raw resume/answer text.

The API validates browser origins and requires its CSRF marker for browser mutations. CORS and CSRF checks are browser safeguards, not authentication; the anonymous cookie is a bearer credential. Use edge protection/provider abuse controls as appropriate, monitor database capacity and 429 responses, and rotate the session secret only with awareness that rotation invalidates existing browser sessions.

## Rollback and recovery

- Keep provider backups enabled and test restore to a separate database.
- Prefer additive, forward-compatible migrations. Roll back the application image first when possible; do not automatically downgrade or delete content tables.
- Keep frontend and backend release identifiers so each can be rolled back independently.
