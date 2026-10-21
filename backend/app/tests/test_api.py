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
async def test_resume_matching_is_transient_and_evidence_aware(client):
    imported = await client.post(
        "/api/v1/jobs/import",
        json={
            "role_title": "Backend Engineer",
            "description": "Required skills: Python and PostgreSQL. Build reliable REST APIs with tests. "
            * 3,
        },
    )
    job_id = imported.json()["id"]
    response = await client.post(
        "/api/v1/resume-job-matches",
        json={
            "job_id": job_id,
            "resume_text": "Experience\n- Built and maintained a Python REST API with tests, serving internal product traffic.\nProjects:\n- Developed a data service using Python and PostgreSQL to support reporting.",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "Python" in payload["match"]["supported_required_skills"]
    assert "PostgreSQL" in payload["match"]["supported_required_skills"]
    assert payload["match"]["relevant_projects"]
    assert payload["storage"] == "not_persisted"
    assert "resume_text" not in payload
    analysis = await client.post(
        "/api/v1/resumes/analyse",
        json={"resume_text": "Built a Python service with automated tests for a product team."},
    )
    assert analysis.status_code == 200 and analysis.json()["storage"] == "not_persisted"


@pytest.mark.asyncio
async def test_practice_session_persists_answers_hides_references_and_resumes(client):
    imported = await client.post(
        "/api/v1/jobs/import",
        json={
            "role_title": "Backend Engineer",
            "description": "Required skills: Python and PostgreSQL. Build reliable REST APIs with tests. "
            * 3,
        },
    )
    plan = imported.json()["preparation_plan"]
    started = await client.post(
        "/api/v1/practice-sessions", json={"plan_id": plan["id"], "mode": "technical_mock"}
    )
    assert started.status_code == 201, started.text
    state = started.json()
    assert state["current_question"]
    assert "reference_answer" not in state["current_question"]
    resumed = await client.get(f"/api/v1/practice-sessions/{state['id']}")
    assert resumed.status_code == 200 and resumed.json()["position"] == 0
    response = await client.post(
        f"/api/v1/practice-sessions/{state['id']}/responses",
        json={
            "answer": "Validate input and keep transaction boundaries short, with useful tests.",
            "submission_key": "attempt-key-0001",
            "allow_ai_evaluation": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["reference_answer"]
    assert response.json()["evaluation_method"] == "deterministic_keyword_heuristic"
    assert response.json()["evaluation"]["provider_notice"]
    assert response.json()["session"]["position"] == 1
    resumed_after_answer = await client.get(f"/api/v1/practice-sessions/{state['id']}")
    assert resumed_after_answer.json()["last_feedback"]["reference_answer"]
    replay = await client.post(
        f"/api/v1/practice-sessions/{state['id']}/responses",
        json={"answer": "same request", "submission_key": "attempt-key-0001"},
    )
    assert replay.status_code == 200 and replay.json()["status"] == "duplicate_submission"
    results = await client.get(f"/api/v1/practice-sessions/{state['id']}/results")
    assert results.status_code == 200 and len(results.json()["responses"]) == 1


@pytest.mark.asyncio
async def test_ai_job_analysis_requires_explicit_provider_configuration(client):
    imported = await client.post(
        "/api/v1/jobs/import",
        json={
            "role_title": "Backend Engineer",
            "description": "Required Python skills with PostgreSQL and API testing. " * 4,
        },
    )
    response = await client.post(
        f"/api/v1/jobs/{imported.json()['id']}/analyse", json={"use_ai": True}
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_ai_job_analysis_provider_failure_returns_deterministic_fallback(client, monkeypatch):
    from app import main as api
    from app.ai import AIProviderError

    imported = await client.post(
        "/api/v1/jobs/import",
        json={
            "role_title": "Backend Engineer",
            "description": "Required skills: Python and PostgreSQL. Build and test reliable APIs. "
            * 3,
        },
    )

    class BrokenProvider:
        provider_name = "mock"
        model_name = "fixture"

        async def analyze_job(self, description, canonical_skills):
            raise AIProviderError("provider unavailable")

    monkeypatch.setattr(api, "get_ai_provider", lambda: BrokenProvider())
    response = await client.post(
        f"/api/v1/jobs/{imported.json()['id']}/analyse", json={"use_ai": True}
    )
    assert response.status_code == 200
    assert response.json()["ai_status"] == "failed_deterministic_fallback"
    assert "Python" in {row["name"] for row in response.json()["analysis"]["required_skills"]}


@pytest.mark.asyncio
async def test_mock_provider_analysis_cache_and_targeted_generation(client, monkeypatch):
    from app import main as api
    from app.ai import (
        EvidenceStatement,
        GeneratedQuestion,
        JobAnalysisOutput,
        QuestionGenerationOutput,
        SkillEvidence,
    )

    imported = await client.post(
        "/api/v1/jobs/import",
        json={
            "role_title": "Backend Engineer",
            "description": "Required skills: PostgreSQL and Kubernetes. Build API services with reliable debugging and testing. "
            * 3,
        },
    )
    job_id = imported.json()["id"]

    class FakeProvider:
        provider_name = "mock"
        model_name = "fixture-v1"
        analysis_calls = 0
        generation_calls = 0

        async def analyze_job(self, description, canonical_skills):
            self.analysis_calls += 1
            return JobAnalysisOutput(
                responsibilities=[
                    EvidenceStatement(statement="Build API services", evidence="Build API services")
                ],
                competencies=[EvidenceStatement(statement="debugging", evidence="debugging")],
                required_skills=[
                    SkillEvidence(name="PostgreSQL", evidence="Required skills: PostgreSQL")
                ],
            )

        async def generate_questions(self, job_context, skill_names, limit):
            self.generation_calls += 1
            question = GeneratedQuestion(
                question_text="How would you safely migrate a PostgreSQL schema while keeping a high-traffic API available?",
                question_type="scenario",
                difficulty="intermediate",
                primary_skill="PostgreSQL",
                skills=["PostgreSQL"],
                expected_points=[
                    "Use backward-compatible schema changes",
                    "Deploy in safe expand and contract steps",
                ],
                reference_answer="A safe migration starts with additive backward-compatible changes and deploys code that supports both schema versions before cleanup.",
                rubric="Look for compatibility, rollout safety, monitoring, and rollback planning.",
            )
            return QuestionGenerationOutput(questions=[question, question.model_copy()])

    fake = FakeProvider()
    monkeypatch.setattr(api, "get_ai_provider", lambda: fake)
    first = await client.post(f"/api/v1/jobs/{job_id}/analyse", json={"use_ai": True})
    second = await client.post(f"/api/v1/jobs/{job_id}/analyse", json={"use_ai": True})
    assert first.status_code == 200 and first.json()["ai_status"] == "analyzed"
    assert second.status_code == 200 and second.json()["ai_status"] == "cached"
    assert fake.analysis_calls == 1
    generated = await client.post(
        f"/api/v1/jobs/{job_id}/generate-questions", json={"max_questions": 1}
    )
    reused = await client.post(
        f"/api/v1/jobs/{job_id}/generate-questions", json={"max_questions": 1}
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["status"] == "generated_pending_review"
    assert len(generated.json()["questions"]) == 1
    assert generated.json()["questions"][0]["validation_status"] == "generated_pending_review"
    assert reused.json()["status"] == "reused_generated_content"
    assert fake.generation_calls == 1
    generated_id = generated.json()["questions"][0]["id"]
    assert (await client.get(f"/api/v1/questions/{generated_id}")).status_code == 404
    reviewed = await client.post(
        f"/api/v1/questions/{generated_id}/review", json={"decision": "approve"}
    )
    assert reviewed.status_code == 200 and reviewed.json()["validation_status"] == "reviewed"
    question_detail = await client.get(f"/api/v1/questions/{generated_id}")
    assert question_detail.json()["provenance"] == "ai_generated"


@pytest.mark.asyncio
async def test_import_rejects_short_descriptions_and_bad_filters(client):
    response = await client.post(
        "/api/v1/jobs/import", json={"role_title": "Engineer", "description": "Too short"}
    )
    assert response.status_code == 422
    bad_filter = await client.get("/api/v1/jobs", params={"status": "anything"})
    assert bad_filter.status_code == 422


@pytest.mark.asyncio
async def test_health_readiness_and_request_size_guard(client):
    health = await client.get("/api/v1/health")
    assert health.status_code == 200 and health.json() == {"status": "ok"}
    assert health.headers.get("x-request-id")
    ready = await client.get("/api/v1/ready")
    assert ready.status_code == 503
    assert ready.json()["database"] == "ready"
    assert ready.json()["migrations"] == "pending"
    assert ready.json()["ai_configuration"] in {"disabled", "configured", "misconfigured"}
    preflight = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.headers.get("access-control-allow-origin") == "http://localhost:5173"
    oversized = await client.post(
        "/api/v1/resumes/analyse",
        content=b" " * 200_001,
        headers={"content-type": "application/json"},
    )
    assert oversized.status_code == 413


@pytest.mark.asyncio
async def test_resume_content_is_not_logged_or_persisted(client, caplog):
    sentinel = "PRIVATE_RESUME_SENTINEL_72b8"
    response = await client.post(
        "/api/v1/resumes/analyse",
        json={"resume_text": f"Built Python services and tested APIs. {sentinel}"},
    )
    assert response.status_code == 200
    assert sentinel not in caplog.text
    assert response.json()["storage"] == "not_persisted"
    assert (await client.get("/api/v1/health")).status_code == 200

    malformed_sentinel = "SENSITIVE"
    malformed = await client.post(
        "/api/v1/resumes/analyse", json={"resume_text": malformed_sentinel}
    )
    assert malformed.status_code == 422
    assert malformed_sentinel not in malformed.text
