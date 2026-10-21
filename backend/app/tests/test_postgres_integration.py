import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app, session_dependency
from app.models import JobPost

POSTGRES_URL = os.getenv("RIGOR_TEST_DATABASE_URL")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    not POSTGRES_URL, reason="Set RIGOR_TEST_DATABASE_URL to an explicitly chosen test database"
)
async def test_postgres_job_version_plan_and_cascade_cleanup():
    engine = create_async_engine(POSTGRES_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    job_id = None

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[session_dependency] = override_session
    title = f"RIGOR PostgreSQL Integration {uuid4().hex[:8]} Backend Engineer"
    source_url = f"https://postgres-integration.invalid/{uuid4()}"
    original = (
        "Required skills: Python, Postgres, FastAPI, and AWS.\n"
        "Location: Remote\nEmployment Type: Full-time\n\n"
        "Responsibilities:\n- Build reliable APIs and improve production performance.\n"
    ) * 2
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            health = await client.get("/api/v1/health")
            readiness = await client.get("/api/v1/ready")
            assert health.status_code == 200 and health.json()["status"] == "ok"
            assert readiness.status_code == 200 and readiness.json()["database"] == "ready"
            imported = await client.post(
                "/api/v1/jobs/import",
                json={
                    "role_title": title,
                    "description": original,
                    "source_url": source_url,
                },
            )
            assert imported.status_code == 201, imported.text
            job = imported.json()
            job_id = job["id"]
            assert {"Python", "PostgreSQL", "FastAPI", "AWS"}.issubset(job["required_skills"])
            assert job["location"] == "Remote" and job["employment_type"] == "full-time"
            assert job["preparation_plan"]["questions"]
            assert job["preparation_plan"]["learning_modules"]

            changed = await client.post(
                "/api/v1/jobs/import",
                json={
                    "role_title": title,
                    "description": original + "The team also owns service testing.\n",
                    "source_url": source_url,
                },
            )
            assert changed.status_code == 200 and changed.json()["content_version"] == 2
            coverage = await client.get(f"/api/v1/jobs/{job_id}/content-coverage")
            assert coverage.status_code == 200
            plan = await client.get(
                f"/api/v1/preparation-plans/{changed.json()['preparation_plan']['id']}"
            )
            assert plan.status_code == 200
            started = await client.post(
                "/api/v1/practice-sessions",
                json={
                    "plan_id": changed.json()["preparation_plan"]["id"],
                    "mode": "technical_mock",
                },
            )
            assert started.status_code == 201, started.text
            practice_id = started.json()["id"]
            submitted = await client.post(
                f"/api/v1/practice-sessions/{practice_id}/responses",
                json={"answer": "Validate at the boundary and keep the transaction short."},
            )
            assert submitted.status_code == 200, submitted.text
            resumed = await client.get(f"/api/v1/practice-sessions/{practice_id}")
            assert resumed.status_code == 200 and resumed.json()["position"] == 1
            results = await client.get(f"/api/v1/practice-sessions/{practice_id}/results")
            assert results.status_code == 200 and len(results.json()["responses"]) == 1
    finally:
        app.dependency_overrides.clear()
        if job_id:
            async with sessions() as session:
                await session.execute(delete(JobPost).where(JobPost.id == job_id))
                await session.commit()
        await engine.dispose()
