import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.main import app, session_dependency
from app.models import (
    LearningModule,
    LearningModuleSkill,
    Question,
    QuestionRoleFamily,
    QuestionSkill,
    Skill,
)


@pytest.fixture
async def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        python = Skill(name="Python", category="programming")
        session.add(python)
        await session.flush()
        question = Question(
            stable_key="test-python-api",
            question_text="How would you structure validation and persistence in a Python API endpoint?",
            question_type="technical",
            difficulty="intermediate",
            role_family="backend",
            category="api_design",
            primary_skill_id=python.id,
            expected_points="Validate input\nKeep transactions short",
            reference_answer="Validate at the boundary, enforce domain invariants in a service, and keep writes within a short transaction.",
            common_mistakes=["Catch and hide every exception"],
            rubric="Look for clear boundaries, correctness, and testable behavior.",
            validation_status="reviewed",
        )
        question.skills = [QuestionSkill(skill=python)]
        question.role_families = [QuestionRoleFamily(role_family="backend")]
        module = LearningModule(
            stable_key="test-python-module",
            title="Python service testing",
            purpose="Practice service boundaries and failure handling.",
            content="Use small functions and explicit transaction boundaries. " * 3,
            learning_objectives=["Test failure paths", "Keep service logic explicit"],
            core_concepts=["Transactions", "Validation"],
            examples="A service unit test uses a fake repository to assert rollback behavior.",
            common_mistakes=["Long transactions", "Broad exception handling"],
            practical_exercises=["Test a failed write"],
            revision_checklist=["Check rollback", "Check validation"],
            prerequisites=[],
            estimated_minutes=20,
            validation_status="reviewed",
        )
        module.skills = [LearningModuleSkill(skill=python)]
        session.add_all([question, module])
        await session.commit()

    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[session_dependency] = override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_import_creates_versioned_job_and_persisted_personalized_plan(client):
    description = "Required skills include Python, FastAPI, PostgreSQL and Redis. " * 3
    first = await client.post(
        "/api/v1/jobs/import",
        json={
            "role_title": "Backend Engineer",
            "description": description,
            "company_name": "Example Co",
            "source_url": "https://jobs.example.test/backend?utm_source=test",
        },
    )
    assert first.status_code == 201, first.text
    job = first.json()
    assert job["role_family"] == "backend"
    assert {"Python", "PostgreSQL", "FastAPI", "Redis"}.issubset(job["required_skills"])
    assert job["content_version"] == 1
    assert job["preparation_plan"]["questions"]
    assert job["preparation_plan"]["learning_modules"]
    assert job["preparation_plan"]["questions"][0]["match_reasons"]

    detail = await client.get(f"/api/v1/jobs/{job['id']}")
    assert detail.status_code == 200 and detail.json()["description"] == description
    coverage = await client.get(f"/api/v1/jobs/{job['id']}/content-coverage")
    assert coverage.status_code == 200
    assert "Python" in coverage.json()["coverage"]["required_skills_with_questions"]
    skills = await client.get(f"/api/v1/jobs/{job['id']}/skills")
    assert skills.status_code == 200 and all(item["evidence"] for item in skills.json()["items"])

    plan = await client.post(
        "/api/v1/preparation-plans", json={"job_id": job["id"], "question_limit": 1}
    )
    assert plan.status_code == 201 and len(plan.json()["questions"]) == 1
    plan_get = await client.get(f"/api/v1/preparation-plans/{plan.json()['id']}")
    assert plan_get.status_code == 200 and plan_get.json()["id"] == plan.json()["id"]

    repeated = await client.post(
        "/api/v1/jobs/import",
        json={
            "role_title": "Backend Engineer",
            "description": description,
            "company_name": "Example Co",
            "source_url": "https://www.jobs.example.test/backend/?utm_campaign=another",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == job["id"] and repeated.json()["version_created"] is False

    changed = await client.post(
        "/api/v1/jobs/import",
        json={
            "role_title": "Backend Engineer",
            "description": description + "\nNew required skill: Docker.",
            "company_name": "Example Co",
            "source_url": "https://jobs.example.test/backend",
        },
    )
    assert changed.status_code == 200 and changed.json()["version_created"] is True
    assert changed.json()["content_version"] == 2


@pytest.mark.asyncio
async def test_catalogue_filters_and_question_module_endpoints(client):
    imported = await client.post(
        "/api/v1/jobs/import",
        json={
            "role_title": "Backend Engineer",
            "description": "Required skills: Python and PostgreSQL. " * 4,
            "company_name": "Example Co",
        },
    )
    assert imported.status_code == 201
    jobs = await client.get(
        "/api/v1/jobs", params={"role_family": "backend", "skill": "Python", "limit": 1}
    )
    assert jobs.status_code == 200 and jobs.json()["total"] == 1
    assert jobs.json()["next_offset"] is None
    questions = await client.get(
        "/api/v1/questions", params={"role_family": "backend", "skill": "Python"}
    )
    assert questions.status_code == 200 and questions.json()["items"]
    qid = questions.json()["items"][0]["id"]
    assert (await client.get(f"/api/v1/questions/{qid}")).status_code == 200
    modules = await client.get("/api/v1/learning-modules", params={"skill": "Python"})
    assert modules.status_code == 200 and modules.json()["items"][0]["learning_objectives"]
    mid = modules.json()["items"][0]["id"]
    assert (await client.get(f"/api/v1/learning-modules/{mid}")).status_code == 200


@pytest.mark.asyncio
async def test_import_rejects_short_descriptions_and_bad_filters(client):
    response = await client.post(
        "/api/v1/jobs/import", json={"role_title": "Engineer", "description": "Too short"}
    )
    assert response.status_code == 422
    bad_filter = await client.get("/api/v1/jobs", params={"status": "anything"})
    assert bad_filter.status_code == 422
