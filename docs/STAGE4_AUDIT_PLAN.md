# Stage 4 audit and implementation plan

## Baseline (2026-10-21)

- HEAD was `74a171f` on `main`, aligned with `origin/main`; the working tree was clean.
- README describes a Vite/vanilla JS frontend, FastAPI/SQLAlchemy backend, and PostgreSQL/Alembic persistence.
- Baseline: 20 backend tests passed, one PostgreSQL test skipped; Ruff passed; Vite build passed.
- Database migration was at `0003_personalised_practice`.
- The ignored `backend/.env` exists but has no OpenAI provider, model, or key entries; no corresponding process variables were present. The key value was never read or printed.

## Findings

- OpenAI setup was checked only on use; provider failures were sanitized, but authentication failures were not identified clearly and the SDK retried once.
- AI calls already used Pydantic structured outputs and bounded timeouts. Job analysis checked canonical skills and verbatim evidence. Generated questions had basic duplicate checks and review status, but unknown skills could be silently dropped and answer-evaluation evidence was not grounded against the submitted answer.
- Prompt inputs had no explicit untrusted-data boundary. Resume matching is transient; answer text and imported job descriptions are persisted.
- The health route combined process and database status and did not check migration readiness. There was no general request-size guard.
- ORM queries are parameterized. Source URLs are validated as HTTP(S) metadata and never fetched, so current ingestion does not make server-side network requests. No file upload endpoint exists.
- AI routes had no rate limit, and operational logs did not provide structured request IDs or privacy-safe token metadata.
- Job imports, plans, practice sessions, answers, and question approval lack authentication or ownership checks. Public multi-user deployment remains blocked.

## Implementation order

1. Keep default checks offline; verify effective provider state without reading secrets.
2. Add a one-call opt-in OpenAI smoke test and versioned synthetic evaluation corpus with offline and separately gated model modes.
3. Harden prompts, provider failures, schema/content checks, review state, request-size handling, rate limits, and privacy-conscious telemetry.
4. Separate process health from database/migration readiness and document controlled deployment, rollback, data ownership, and public-launch blockers.
5. Run backend tests, Ruff, PostgreSQL integration where available, deterministic evaluation, Alembic current, and frontend production build. Make no live provider calls.
