import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import and_, case, delete, exists, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai import AIConfigurationError, AIProviderError, get_ai_provider
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.observability import configure_privacy_logging, request_id_context
from app.models import (
    CandidateResponse,
    Company,
    ContentGenerationRun,
    JobPost,
    JobPostVersion,
    JobSkill,
    LearningModule,
    LearningModuleSkill,
    PlanItem,
    PracticeSession,
    PreparationPlan,
    Question,
    QuestionRoleFamily,
    QuestionSkill,
    Skill,
    SkillAlias,
)
from app.personalization import (
    extract_resume_evidence,
    fallback_evaluate,
    is_duplicate_question,
    match_resume_to_job,
    reorder_adaptive_queue,
)
from app.schemas import (
    AnalyseRequest,
    GenerateQuestionsRequest,
    JobImport,
    JobPage,
    PlanCreate,
    PracticeResponseCreate,
    PracticeSessionCreate,
    QuestionReviewRequest,
    ResumeAnalysisRequest,
    ResumeJobMatchRequest,
)
from app.services import (
    RankingWeights,
    analyze_job,
    build_content_coverage,
    description_hash,
    detect_job_duplicate,
    job_fingerprint,
    normalize_source_url,
    rank_question,
    select_balanced_questions,
)
from app.taxonomy import SKILL_TAXONOMY

logger = logging.getLogger("rigor.http")
configure_privacy_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="RIGOR Interview Workbench API", version="3.0.0", lifespan=lifespan)


class RequestGuardMiddleware:
    def __init__(self, app, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        request_context_token = request_id_context.set(request_id)
        started = time.monotonic()
        chunks = []
        size = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                request_id_context.reset(request_context_token)
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_body_bytes:
                body = json.dumps({"detail": "Request body is too large"}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                            (b"x-request-id", request_id.encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                request_id_context.reset(request_context_token)
                return
            chunks.append(chunk)
            more_body = message.get("more_body", False)
        body = b"".join(chunks)
        replayed = False

        async def replay_receive():
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        status_code = 500

        async def traced_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message["headers"].append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, replay_receive, traced_send)
        except Exception as exc:
            logger.error(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": scope.get("method"),
                    "error_type": type(exc).__name__,
                },
            )
            request_id_context.reset(request_context_token)
            raise
        route = scope.get("route")
        logger.info(
            "request_complete",
            extra={
                "request_id": request_id,
                "endpoint": getattr(route, "path", "unmatched"),
                "method": scope.get("method"),
                "status_code": status_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
        )
        request_id_context.reset(request_context_token)


app.add_middleware(RequestGuardMiddleware, max_body_bytes=settings.max_request_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Validation details can contain submitted values; return schema diagnostics only.
    details = [
        {key: error[key] for key in ("loc", "msg", "type") if key in error}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})


_ai_request_windows: dict[str, deque[float]] = defaultdict(deque)


def enforce_ai_rate_limit(request: Request) -> None:
    if settings.ai_provider != "openai":
        return
    client_key = request.client.host if request.client else "unknown"
    now = monotonic()
    window = _ai_request_windows[client_key]
    while window and window[0] <= now - 60:
        window.popleft()
    if len(window) >= settings.ai_requests_per_minute:
        raise HTTPException(429, "AI request limit reached; try again later.")
    window.append(now)
    if len(_ai_request_windows) > 10_000:
        stale = [
            key
            for key, events in _ai_request_windows.items()
            if not events or events[-1] <= now - 60
        ]
        for key in stale:
            _ai_request_windows.pop(key, None)


async def session_dependency():
    async with SessionLocal() as session:
        yield session


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/ready")
async def readiness(session: AsyncSession = Depends(session_dependency)):
    database, migrations = "ready", "unknown"
    try:
        await session.execute(select(1))
    except SQLAlchemyError:
        database = "unavailable"
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": database,
                "migrations": migrations,
                "ai_provider": settings.ai_provider
                if settings.ai_provider in {"none", "openai"}
                else "misconfigured",
                "ai_configuration": settings.ai_configuration_status,
            },
        )
    try:
        # Query alembic_version with textual SQL so readiness works independently of ORM metadata.
        from sqlalchemy import text

        current_revision = (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
        alembic_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        script = ScriptDirectory.from_config(alembic_config)
        migrations = "current" if current_revision == script.get_current_head() else "pending"
    except SQLAlchemyError:
        migrations = "pending"
    except Exception:  # noqa: BLE001 - config failures should not leak readiness details.
        migrations = "unknown"
    status = "ready" if database == "ready" and migrations == "current" else "not_ready"
    return JSONResponse(
        status_code=200 if status == "ready" else 503,
        content={
            "status": status,
            "database": database,
            "migrations": migrations,
            "ai_provider": settings.ai_provider
            if settings.ai_provider in {"none", "openai"}
            else "misconfigured",
            "ai_configuration": settings.ai_configuration_status,
        },
    )


@app.get("/api/v1/jobs", response_model=JobPage)
async def list_jobs(
    q: str | None = Query(None, max_length=160),
    role_family: str | None = Query(None, max_length=80),
    seniority: str | None = Query(None, max_length=80),
    location: str | None = Query(None, max_length=200),
    employment_type: str | None = Query(None, max_length=80),
    skill: str | None = Query(None, max_length=120),
    status: str = Query("active", pattern="^(active|expired|stale|all)$"),
    sort: str = Query("recent", pattern="^(recent|relevance)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1000000),
    session: AsyncSession = Depends(session_dependency),
):
    query = select(JobPost)
    if status != "all":
        query = query.where(JobPost.status == status)
    if role_family:
        query = query.where(JobPost.role_family == role_family)
    if seniority:
        query = query.where(func.lower(JobPost.seniority) == seniority.lower())
    if location:
        query = query.where(JobPost.location.ilike(f"%{location}%"))
    if employment_type:
        query = query.where(func.lower(JobPost.employment_type) == employment_type.lower())
    if q:
        term = f"%{q.strip()}%"
        query = query.where(
            or_(
                JobPost.role_title.ilike(term),
                JobPost.company_name.ilike(term),
                JobPost.description.ilike(term),
            )
        )
    if skill:
        skill_match = exists(
            select(JobSkill.id)
            .join(Skill, Skill.id == JobSkill.skill_id)
            .outerjoin(SkillAlias, SkillAlias.skill_id == Skill.id)
            .where(JobSkill.job_id == JobPost.id)
            .where(
                or_(
                    func.lower(Skill.name) == skill.lower(),
                    func.lower(SkillAlias.alias) == skill.lower(),
                )
            )
        )
        query = query.where(skill_match)
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = await session.scalar(count_query) or 0
    if sort == "relevance" and q:
        normalized = q.strip().lower()
        relevance = case(
            (func.lower(JobPost.role_title) == normalized, 3),
            (JobPost.role_title.ilike(f"%{q.strip()}%"), 2),
            (JobPost.company_name.ilike(f"%{q.strip()}%"), 1),
            else_=0,
        )
        query = query.order_by(
            relevance.desc(),
            JobPost.last_verified_at.desc().nullslast(),
            JobPost.imported_at.desc(),
            JobPost.id,
        )
    else:
        query = query.order_by(
            JobPost.last_verified_at.desc().nullslast(), JobPost.imported_at.desc(), JobPost.id
        )
    jobs = (await session.scalars(query.offset(offset).limit(limit))).all()
    payloads = await job_payloads(session, jobs)
    next_offset = offset + limit if offset + limit < total else None
    return {
        "items": payloads,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
    }


@app.post("/api/v1/jobs/import")
async def import_job(
    payload: JobImport, response: Response, session: AsyncSession = Depends(session_dependency)
):
    profile = analyze_job(payload.role_title, payload.description)
    normalized_url = normalize_source_url(str(payload.source_url) if payload.source_url else None)
    company_name = payload.company_name.strip() if payload.company_name else None
    candidates_query = (
        select(JobPost)
        .where(
            or_(
                and_(normalized_url is not None, JobPost.normalized_source_url == normalized_url),
                and_(
                    func.lower(JobPost.role_title) == payload.role_title.lower(),
                    func.lower(func.coalesce(JobPost.company_name, ""))
                    == (company_name or "").lower(),
                ),
            )
        )
        .order_by(case((JobPost.normalized_source_url == normalized_url, 1), else_=0).desc())
        .limit(50)
    )
    candidates = (await session.scalars(candidates_query)).all()
    duplicate, duplicate_reason = detect_job_duplicate(
        [
            {
                "id": job.id,
                "role_title": job.role_title,
                "company_name": job.company_name,
                "description": job.description,
                "normalized_source_url": job.normalized_source_url,
            }
            for job in candidates
        ],
        title=payload.role_title,
        company=company_name,
        description=payload.description,
        normalized_url=normalized_url,
    )
    company = None
    if company_name:
        company = await session.scalar(
            select(Company).where(func.lower(Company.name) == company_name.lower())
        )
        if company is None:
            company = Company(name=company_name)
            session.add(company)
            await session.flush()

    is_new = duplicate is None
    changed = False
    if is_new:
        job = JobPost(
            role_title=payload.role_title,
            description=payload.description,
            company=company,
            company_name=company_name,
            location=payload.location or profile["location"],
            seniority=payload.seniority or profile["seniority"],
            employment_type=payload.employment_type or profile["employment_type"],
            source_url=str(payload.source_url) if payload.source_url else None,
            normalized_source_url=normalized_url,
            role_family=profile["role_family"],
            source_type="user_import",
            status="active",
            responsibilities=profile["responsibilities"],
            qualifications=profile["qualifications"],
            competencies=profile["competencies"],
            tools_technologies=profile["tools_technologies"],
            last_verified_at=datetime.now(UTC),
        )
        session.add(job)
        await session.flush()
        changed = True
        version = 1
    else:
        job = await session.get(JobPost, duplicate["id"])
        assert job is not None
        incoming_hash = job_fingerprint(payload.role_title, company_name, payload.description)
        current_hash = job_fingerprint(job.role_title, job.company_name, job.description)
        changed = incoming_hash != current_hash
        version = job.content_version + 1 if changed else job.content_version
        if changed:
            job.role_title = payload.role_title
            job.description = payload.description
            job.company = company
            job.company_name = company_name
            job.location = payload.location or profile["location"]
            job.seniority = payload.seniority or profile["seniority"]
            job.employment_type = payload.employment_type or profile["employment_type"]
            job.role_family = profile["role_family"]
            job.responsibilities = profile["responsibilities"]
            job.qualifications = profile["qualifications"]
            job.competencies = profile["competencies"]
            job.tools_technologies = profile["tools_technologies"]
            job.content_version = version
            await session.execute(delete(JobSkill).where(JobSkill.job_id == job.id))
            await session.flush()
        job.source_url = str(payload.source_url) if payload.source_url else job.source_url
        job.normalized_source_url = normalized_url or job.normalized_source_url
        job.last_verified_at = datetime.now(UTC)
        job.status = "active"

    if is_new or changed:
        session.add(
            JobPostVersion(
                job=job,
                version=version,
                description=payload.description,
                role_title=payload.role_title,
                company_name=company_name,
                content_hash=description_hash(payload.description),
            )
        )
        await save_job_skills(session, job, profile)

    await session.flush()
    plan = await latest_plan(session, job.id) if not changed else None
    if plan is None:
        plan_payload = await make_plan(session, job, PlanCreate(job_id=job.id), commit=False)
        plan = plan_payload["_plan"]
    await session.commit()
    await session.refresh(job)
    response.status_code = 201 if is_new else 200
    return {
        **await job_payload(session, job),
        "is_duplicate": not is_new,
        "duplicate_match": duplicate_reason,
        "version_created": changed and not is_new,
        "analysis": profile,
        "preparation_plan": await plan_payload_for(session, plan, job),
    }


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: UUID, session: AsyncSession = Depends(session_dependency)):
    job = await session.get(JobPost, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return await job_payload(session, job, include_description=True)


@app.get("/api/v1/jobs/{job_id}/skills")
async def get_job_skills(job_id: UUID, session: AsyncSession = Depends(session_dependency)):
    job = await session.get(JobPost, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    rows = await job_skill_rows(session, job_id)
    return {"job_id": str(job_id), "items": [job_skill_payload(row) for row in rows]}


@app.get("/api/v1/jobs/{job_id}/content-coverage")
async def job_content_coverage(job_id: UUID, session: AsyncSession = Depends(session_dependency)):
    job = await session.get(JobPost, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    analysis = await rank_job_content(session, job)
    return {"job_id": str(job_id), "coverage": analysis["coverage"]}


@app.post("/api/v1/jobs/{job_id}/analyse")
async def analyse(
    job_id: UUID,
    request: Request,
    payload: AnalyseRequest | None = None,
    session: AsyncSession = Depends(session_dependency),
):
    job = await session.get(JobPost, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    profile = analyze_job(job.role_title, job.description)
    ai_status = "not_requested"
    if payload and payload.use_ai:
        enforce_ai_rate_limit(request)
        try:
            provider = get_ai_provider()
        except AIConfigurationError as exc:
            raise HTTPException(503, str(exc)) from exc
        fingerprint = hashlib.sha256(
            f"job-analysis-v1:{job.content_version}:{description_hash(job.description)}:{provider.provider_name}:{provider.model_name}".encode()
        ).hexdigest()
        if job.ai_analysis_fingerprint == fingerprint and job.ai_analysis:
            semantic = job.ai_analysis
            ai_status = "cached"
        else:
            try:
                output = await provider.analyze_job(
                    job.description, [item["name"] for item in SKILL_TAXONOMY]
                )
                semantic = output.model_dump()
                semantic["analysis_version"] = 1
                job.ai_analysis = semantic
                job.ai_analysis_fingerprint = fingerprint
                ai_status = "analyzed"
            except AIConfigurationError as exc:
                raise HTTPException(503, str(exc)) from exc
            except AIProviderError:
                return {
                    "job_id": str(job.id),
                    "analysis": profile,
                    "ai_status": "failed_deterministic_fallback",
                    "ai_message": "AI analysis failed. The deterministic profile is returned unchanged.",
                    "content_coverage": (await rank_job_content(session, job))["coverage"],
                }
        canonical = {
            alias.casefold(): item["name"]
            for item in SKILL_TAXONOMY
            for alias in [item["name"], *item["aliases"]]
        }
        merged = {
            item["name"].casefold(): item
            for item in profile["required_skills"]
            + profile["preferred_skills"]
            + profile["mentioned_skills"]
        }
        ai_required, ai_preferred = set(), set()
        for requirement in ("required_skills", "preferred_skills"):
            for candidate in semantic[requirement]:
                name = canonical.get(candidate["name"].casefold())
                evidence = candidate["evidence"].strip()
                if name and evidence and evidence.casefold() in job.description.casefold():
                    merged[name.casefold()] = {
                        "name": name,
                        "category": next(
                            x["category"] for x in SKILL_TAXONOMY if x["name"] == name
                        ),
                        "evidence": evidence,
                    }
                    (ai_required if requirement == "required_skills" else ai_preferred).add(name)
        required_names = {item["name"] for item in profile["required_skills"]} | ai_required
        preferred_names = (
            {item["name"] for item in profile["preferred_skills"]} | ai_preferred
        ) - required_names
        profile["required_skills"] = [merged[name.casefold()] for name in sorted(required_names)]
        profile["preferred_skills"] = [merged[name.casefold()] for name in sorted(preferred_names)]
        profile["mentioned_skills"] = [
            item
            for item in profile["mentioned_skills"]
            if item["name"] not in required_names | preferred_names
        ]
        canonical_competencies = {
            "debugging",
            "communication",
            "reliability",
            "performance",
            "security",
            "testing",
            "analytics",
        }
        supported_competencies = {
            item["statement"].casefold()
            for item in semantic["competencies"]
            if item["statement"].casefold() in canonical_competencies
            and item["evidence"].casefold() in job.description.casefold()
        }
        profile["competencies"] = sorted(
            set(profile.get("competencies", [])) | supported_competencies
        )
        supported_responsibilities = [
            item["statement"]
            for item in semantic["responsibilities"]
            if item["evidence"].casefold() in job.description.casefold()
        ]
        profile["responsibilities"] = list(
            dict.fromkeys(profile.get("responsibilities", []) + supported_responsibilities)
        )[:30]
        await session.execute(delete(JobSkill).where(JobSkill.job_id == job.id))
        await save_job_skills(session, job, profile)
        await session.commit()
    return {
        "job_id": str(job.id),
        "analysis": profile,
        "ai_status": ai_status,
        "content_coverage": (await rank_job_content(session, job))["coverage"],
    }


@app.get("/api/v1/questions")
async def list_questions(
    q: str | None = Query(None, max_length=160),
    role_family: str | None = Query(None, max_length=80),
    skill: str | None = Query(None, max_length=120),
    category: str | None = Query(None, max_length=60),
    difficulty: str | None = Query(None, pattern="^(beginner|intermediate|advanced)$"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1000000),
    session: AsyncSession = Depends(session_dependency),
):
    query = select(Question).where(Question.validation_status == "reviewed")
    if q:
        query = query.where(Question.question_text.ilike(f"%{q.strip()}%"))
    if role_family:
        query = query.where(
            or_(
                Question.role_family == role_family,
                exists(
                    select(QuestionRoleFamily.question_id).where(
                        QuestionRoleFamily.question_id == Question.id,
                        QuestionRoleFamily.role_family == role_family,
                    )
                ),
            )
        )
    if skill:
        query = query.where(
            exists(
                select(QuestionSkill.question_id)
                .join(Skill, Skill.id == QuestionSkill.skill_id)
                .outerjoin(SkillAlias, SkillAlias.skill_id == Skill.id)
                .where(QuestionSkill.question_id == Question.id)
                .where(
                    or_(
                        func.lower(Skill.name) == skill.lower(),
                        func.lower(SkillAlias.alias) == skill.lower(),
                    )
                )
            )
        )
    if category:
        query = query.where(Question.category == category)
    if difficulty:
        query = query.where(Question.difficulty == difficulty)
    total = (
        await session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    )
    query = query.options(
        selectinload(Question.skills).selectinload(QuestionSkill.skill),
        selectinload(Question.role_families),
    )
    rows = (
        await session.scalars(
            query.order_by(Question.stable_key, Question.id).offset(offset).limit(limit)
        )
    ).all()
    return {
        "items": [question_payload(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
    }


@app.get("/api/v1/questions/{question_id}")
async def get_question(question_id: UUID, session: AsyncSession = Depends(session_dependency)):
    query = (
        select(Question)
        .options(
            selectinload(Question.skills).selectinload(QuestionSkill.skill),
            selectinload(Question.role_families),
        )
        .where(Question.id == question_id, Question.validation_status == "reviewed")
    )
    question = await session.scalar(query)
    if question is None:
        raise HTTPException(404, "Question not found")
    return question_payload(question)


@app.post("/api/v1/questions/{question_id}/review")
async def review_generated_question(
    question_id: UUID,
    payload: QuestionReviewRequest,
    session: AsyncSession = Depends(session_dependency),
):
    question = await session.get(Question, question_id)
    if question is None:
        raise HTTPException(404, "Question not found")
    if (
        question.provenance != "ai_generated"
        or question.validation_status != "generated_pending_review"
    ):
        raise HTTPException(
            409, "Only generated questions pending review can be approved or rejected"
        )
    question.validation_status = "reviewed" if payload.decision == "approve" else "rejected"
    await session.commit()
    return {
        "question_id": str(question.id),
        "provenance": question.provenance,
        "validation_status": question.validation_status,
    }


@app.get("/api/v1/learning-modules")
async def list_learning_modules(
    skill: str | None = Query(None, max_length=120),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1000000),
    session: AsyncSession = Depends(session_dependency),
):
    query = select(LearningModule).where(LearningModule.validation_status == "reviewed")
    if skill:
        query = query.where(
            exists(
                select(LearningModuleSkill.module_id)
                .join(Skill, Skill.id == LearningModuleSkill.skill_id)
                .outerjoin(SkillAlias, SkillAlias.skill_id == Skill.id)
                .where(LearningModuleSkill.module_id == LearningModule.id)
                .where(
                    or_(
                        func.lower(Skill.name) == skill.lower(),
                        func.lower(SkillAlias.alias) == skill.lower(),
                    )
                )
            )
        )
    total = (
        await session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    )
    query = query.options(
        selectinload(LearningModule.skills).selectinload(LearningModuleSkill.skill)
    )
    rows = (
        await session.scalars(query.order_by(LearningModule.title).offset(offset).limit(limit))
    ).all()
    return {
        "items": [module_payload(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
    }


@app.get("/api/v1/learning-modules/{module_id}")
async def get_learning_module(module_id: UUID, session: AsyncSession = Depends(session_dependency)):
    query = (
        select(LearningModule)
        .options(selectinload(LearningModule.skills).selectinload(LearningModuleSkill.skill))
        .where(LearningModule.id == module_id)
    )
    module = await session.scalar(query)
    if module is None:
        raise HTTPException(404, "Learning module not found")
    return module_payload(module)


@app.post("/api/v1/preparation-plans", status_code=201)
async def create_preparation_plan(
    payload: PlanCreate, session: AsyncSession = Depends(session_dependency)
):
    job = await session.get(JobPost, payload.job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    result = await make_plan(session, job, payload, commit=False)
    await session.commit()
    await session.refresh(result["_plan"])
    return await plan_payload_for(session, result["_plan"], job)


@app.get("/api/v1/preparation-plans/{plan_id}")
async def get_plan(plan_id: UUID, session: AsyncSession = Depends(session_dependency)):
    plan = await session.get(PreparationPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "Preparation plan not found")
    job = await session.get(JobPost, plan.job_id)
    return await plan_payload_for(session, plan, job)


async def save_job_skills(session: AsyncSession, job: JobPost, profile: dict):
    for requirement, key in (
        ("required", "required_skills"),
        ("preferred", "preferred_skills"),
        ("mentioned", "mentioned_skills"),
    ):
        for evidence in profile[key]:
            skill = await session.scalar(select(Skill).where(Skill.name == evidence["name"]))
            if skill is None:
                skill = Skill(name=evidence["name"], category=evidence["category"])
                session.add(skill)
                await session.flush()
            session.add(
                JobSkill(
                    job=job,
                    skill=skill,
                    requirement_type=requirement,
                    evidence=evidence["evidence"],
                    extraction_method=profile["method"],
                )
            )


async def job_skill_rows(session: AsyncSession, job_id: UUID):
    return (
        await session.scalars(
            select(JobSkill)
            .join(Skill, Skill.id == JobSkill.skill_id)
            .options(selectinload(JobSkill.skill))
            .where(JobSkill.job_id == job_id)
            .order_by(JobSkill.requirement_type, Skill.name)
        )
    ).all()


def job_skill_payload(row: JobSkill):
    return {
        "skill": row.skill.name,
        "category": row.skill.category,
        "requirement_type": row.requirement_type,
        "evidence": row.evidence,
        "extraction_method": row.extraction_method or "legacy",
    }


async def job_payload(session: AsyncSession, job: JobPost, include_description: bool = False):
    rows = await job_skill_rows(session, job.id)
    return serialize_job(job, rows, include_description)


async def job_payloads(session: AsyncSession, jobs: list[JobPost]):
    if not jobs:
        return []
    job_ids = [job.id for job in jobs]
    rows = (
        await session.scalars(
            select(JobSkill)
            .join(Skill, Skill.id == JobSkill.skill_id)
            .options(selectinload(JobSkill.skill))
            .where(JobSkill.job_id.in_(job_ids))
        )
    ).all()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.job_id].append(row)
    return [serialize_job(job, grouped[job.id]) for job in jobs]


def serialize_job(job: JobPost, rows: list[JobSkill], include_description: bool = False):
    result = {
        "id": str(job.id),
        "role_title": job.role_title,
        "company_name": job.company_name,
        "role_family": job.role_family,
        "seniority": job.seniority,
        "location": job.location,
        "employment_type": job.employment_type,
        "source_type": job.source_type,
        "source_url": job.source_url,
        "status": job.status,
        "is_demo": job.is_demo,
        "content_version": job.content_version,
        "last_verified_at": job.last_verified_at.isoformat() if job.last_verified_at else None,
        "imported_at": job.imported_at.isoformat() if job.imported_at else None,
        "responsibilities": job.responsibilities or [],
        "qualifications": job.qualifications or [],
        "competencies": job.competencies or [],
        "tools_technologies": job.tools_technologies or [],
        "required_skills": [r.skill.name for r in rows if r.requirement_type == "required"],
        "preferred_skills": [r.skill.name for r in rows if r.requirement_type == "preferred"],
        "mentioned_skills": [r.skill.name for r in rows if r.requirement_type == "mentioned"],
    }
    if include_description:
        result["description"] = job.description
    return result


def question_payload(question: Question):
    skill_names = [item.skill.name for item in question.skills]
    return {
        "id": str(question.id),
        "stable_key": question.stable_key,
        "question": question.question_text,
        "question_text": question.question_text,
        "question_type": question.question_type,
        "category": question.category,
        "difficulty": question.difficulty,
        "primary_skill": next(
            (
                item.skill.name
                for item in question.skills
                if question.primary_skill_id == item.skill_id
            ),
            skill_names[0] if skill_names else None,
        ),
        "skills": skill_names,
        "role_families": [item.role_family for item in question.role_families]
        or [question.role_family],
        "expected_points": question.expected_points.splitlines(),
        "reference_answer": question.reference_answer,
        "common_mistakes": question.common_mistakes or [],
        "rubric": question.rubric,
        "provenance": question.provenance,
        "validation_status": question.validation_status,
        "version": question.version,
    }


def module_payload(module: LearningModule):
    return {
        "id": str(module.id),
        "stable_key": module.stable_key,
        "title": module.title,
        "purpose": module.purpose,
        "summary": module.purpose,
        "content": module.content,
        "learning_objectives": module.learning_objectives or [],
        "core_concepts": module.core_concepts or [],
        "examples": module.examples or "",
        "common_mistakes": module.common_mistakes or [],
        "practical_exercises": module.practical_exercises or [],
        "revision_checklist": module.revision_checklist or [],
        "prerequisites": module.prerequisites or [],
        "estimated_minutes": module.estimated_minutes,
        "skills": [item.skill.name for item in module.skills],
    }


async def rank_job_content(session: AsyncSession, job: JobPost, question_limit: int = 50):
    skill_rows = await job_skill_rows(session, job.id)
    required = {r.skill.name for r in skill_rows if r.requirement_type == "required"}
    preferred = {r.skill.name for r in skill_rows if r.requirement_type == "preferred"}
    all_skill_ids = [r.skill_id for r in skill_rows]
    question_query = select(Question).where(Question.validation_status == "reviewed")
    if all_skill_ids:
        question_query = question_query.where(
            or_(
                Question.role_family == job.role_family,
                exists(
                    select(QuestionRoleFamily.question_id).where(
                        QuestionRoleFamily.question_id == Question.id,
                        QuestionRoleFamily.role_family == job.role_family,
                    )
                ),
                exists(
                    select(QuestionSkill.question_id).where(
                        QuestionSkill.question_id == Question.id,
                        QuestionSkill.skill_id.in_(all_skill_ids),
                    )
                ),
            )
        )
    else:
        question_query = question_query.where(
            or_(
                Question.role_family == job.role_family,
                exists(
                    select(QuestionRoleFamily.question_id).where(
                        QuestionRoleFamily.question_id == Question.id,
                        QuestionRoleFamily.role_family == job.role_family,
                    )
                ),
            )
        )
    question_query = question_query.options(
        selectinload(Question.skills).selectinload(QuestionSkill.skill),
        selectinload(Question.role_families),
    )
    question_rows = (await session.scalars(question_query)).all()
    question_candidates = []
    for row in question_rows:
        item = question_payload(row)
        item = rank_question(
            item,
            role_family=job.role_family,
            required=required,
            preferred=preferred,
            competencies=set(job.competencies or []),
            seniority=job.seniority,
            weights=RankingWeights(),
        )
        question_candidates.append(item)
    ranked = sorted(
        question_candidates,
        key=lambda item: (-item["relevance_score"], item["stable_key"], item["id"]),
    )

    module_query = select(LearningModule).where(LearningModule.validation_status == "reviewed")
    if all_skill_ids:
        module_query = module_query.where(
            exists(
                select(LearningModuleSkill.module_id).where(
                    LearningModuleSkill.module_id == LearningModule.id,
                    LearningModuleSkill.skill_id.in_(all_skill_ids),
                )
            )
        )
    module_query = module_query.options(
        selectinload(LearningModule.skills).selectinload(LearningModuleSkill.skill)
    )
    modules = (await session.scalars(module_query)).all()
    module_items = [module_payload(module) for module in modules]
    module_items.sort(
        key=lambda item: (
            -len(set(item["skills"]) & required),
            -len(set(item["skills"]) & preferred),
            item["stable_key"],
        )
    )
    selected = select_balanced_questions(ranked, question_limit, required)
    coverage = build_content_coverage(required, preferred, ranked, module_items, job.role_family)
    return {
        "required": required,
        "preferred": preferred,
        "questions": selected,
        "ranked_questions": ranked,
        "learning_modules": module_items,
        "coverage": coverage,
    }


async def make_plan(session: AsyncSession, job: JobPost, request: PlanCreate, commit: bool = True):
    analysis = await rank_job_content(session, job, request.question_limit)
    plan = PreparationPlan(job_id=job.id, status="active", content_coverage=analysis["coverage"])
    session.add(plan)
    await session.flush()
    position = 1
    for module in analysis["learning_modules"]:
        session.add(
            PlanItem(
                plan_id=plan.id,
                position=position,
                item_type="module",
                module_id=UUID(module["id"]),
                match_reasons=[
                    f"Supports {name}."
                    for name in module["skills"]
                    if name in analysis["required"] or name in analysis["preferred"]
                ],
            )
        )
        position += 1
    for question in analysis["questions"]:
        session.add(
            PlanItem(
                plan_id=plan.id,
                position=position,
                item_type="question",
                question_id=UUID(question["id"]),
                relevance_score=question["relevance_score"],
                match_reasons=question["match_reasons"],
            )
        )
        position += 1
    if commit:
        await session.commit()
        await session.refresh(plan)
    return {"_plan": plan, "analysis": analysis}


async def latest_plan(session: AsyncSession, job_id: UUID):
    return await session.scalar(
        select(PreparationPlan)
        .where(PreparationPlan.job_id == job_id)
        .order_by(PreparationPlan.created_at.desc())
        .limit(1)
    )


async def plan_payload_for(session: AsyncSession, plan: PreparationPlan, job: JobPost):
    items = (
        await session.scalars(
            select(PlanItem).where(PlanItem.plan_id == plan.id).order_by(PlanItem.position)
        )
    ).all()
    if not items:
        analysis = await rank_job_content(session, job)
        question_items = analysis["questions"]
        learning_modules = analysis["learning_modules"]
        coverage = plan.content_coverage or analysis["coverage"]
    else:
        qids = [item.question_id for item in items if item.question_id]
        mids = [item.module_id for item in items if item.module_id]
        question_rows = (
            (
                await session.scalars(
                    select(Question)
                    .options(
                        selectinload(Question.skills).selectinload(QuestionSkill.skill),
                        selectinload(Question.role_families),
                    )
                    .where(Question.id.in_(qids))
                )
            ).all()
            if qids
            else []
        )
        qmap = {row.id: question_payload(row) for row in question_rows}
        item_map = {item.question_id: item for item in items if item.question_id}
        question_items = []
        for qid in qids:
            q = qmap.get(qid)
            if q:
                stored = item_map[qid]
                q.update(
                    {
                        "relevance_score": stored.relevance_score,
                        "match_reasons": stored.match_reasons or [],
                    }
                )
                question_items.append(q)
        module_rows = (
            (
                await session.scalars(
                    select(LearningModule)
                    .options(
                        selectinload(LearningModule.skills).selectinload(LearningModuleSkill.skill)
                    )
                    .where(LearningModule.id.in_(mids))
                )
            ).all()
            if mids
            else []
        )
        module_map = {row.id: module_payload(row) for row in module_rows}
        learning_modules = [module_map[mid] for mid in mids if mid in module_map]
        coverage = plan.content_coverage or {}
    legacy_modules = [
        {
            "name": "Priority concepts",
            "skills": sorted(coverage.get("required_skills_without_learning", [])),
        },
        {"name": "Practice questions", "questions": question_items},
    ]
    return {
        "id": str(plan.id),
        "job_id": str(job.id),
        "status": plan.status,
        "modules": legacy_modules,
        "learning_modules": learning_modules,
        "questions": question_items,
        "content_coverage": coverage,
    }


@app.post("/api/v1/resumes/analyse")
async def analyse_resume(payload: ResumeAnalysisRequest):
    # Resume text is processed transiently and is never stored or logged.
    return {
        "profile": extract_resume_evidence(payload.resume_text),
        "storage": "not_persisted",
        "processing": "backend_local",
    }


@app.post("/api/v1/resume-job-matches")
async def resume_job_match(
    payload: ResumeJobMatchRequest, session: AsyncSession = Depends(session_dependency)
):
    job = await session.get(JobPost, payload.job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    rows = await job_skill_rows(session, job.id)
    required = [row.skill.name for row in rows if row.requirement_type == "required"]
    preferred = [row.skill.name for row in rows if row.requirement_type == "preferred"]
    profile = extract_resume_evidence(payload.resume_text)
    return {
        "job_id": str(job.id),
        "profile": profile,
        "match": match_resume_to_job(profile, required, preferred),
        "storage": "not_persisted",
        "external_ai_used": False,
    }


@app.post("/api/v1/jobs/{job_id}/generate-questions")
async def generate_targeted_questions(
    job_id: UUID,
    request: Request,
    payload: GenerateQuestionsRequest,
    session: AsyncSession = Depends(session_dependency),
):
    job = await session.get(JobPost, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    analysis = await rank_job_content(session, job)
    coverage = analysis["coverage"]
    gaps = (
        coverage["required_skills_without_questions"]
        or coverage["preferred_skills_without_questions"]
    )
    if not gaps:
        return {
            "status": "no_content_gap",
            "questions": [],
            "message": "Existing reviewed questions already cover the identified job skills.",
        }
    enforce_ai_rate_limit(request)
    try:
        provider = get_ai_provider()
    except AIConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    limit = min(payload.max_questions, settings.ai_max_generation_batch, 5)
    fingerprint = hashlib.sha256(
        f"question-generation-v1:{job.content_version}:{provider.provider_name}:{provider.model_name}:{','.join(sorted(gaps))}:{limit}".encode()
    ).hexdigest()
    cached_run = await session.scalar(
        select(ContentGenerationRun)
        .where(
            ContentGenerationRun.input_fingerprint == fingerprint,
            ContentGenerationRun.content_type == "targeted_questions",
            ContentGenerationRun.status == "generated_pending_review",
        )
        .order_by(ContentGenerationRun.created_at.desc())
    )
    if cached_run:
        keys = [value for value in cached_run.validation_metadata.splitlines() if value]
        cached = (
            (await session.scalars(select(Question).where(Question.stable_key.in_(keys)))).all()
            if keys
            else []
        )
        return {
            "status": "reused_generated_content",
            "questions": [
                {
                    "id": str(q.id),
                    "stable_key": q.stable_key,
                    "question": q.question_text,
                    "validation_status": q.validation_status,
                    "provenance": q.provenance,
                }
                for q in cached
            ],
            "uncovered_skills": gaps,
        }
    existing_texts = list((await session.scalars(select(Question.question_text))).all())
    reusable_questions = [
        {"question": item["question"], "skills": item["skills"], "category": item["category"]}
        for item in analysis["questions"][:8]
    ]
    reusable_modules = [
        {"title": item["title"], "skills": item["skills"], "summary": item["purpose"]}
        for item in analysis["learning_modules"][:6]
    ]
    context = f"Role: {job.role_title}; role family: {job.role_family}; responsibilities: {job.responsibilities or []}; description: {job.description[:4000]}; already available practice questions: {reusable_questions}; reusable learning modules: {reusable_modules}"
    try:
        output = await provider.generate_questions(context, gaps, limit)
    except AIConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(
            502, "Question generation failed; existing preparation content remains available"
        ) from exc
    skill_rows = (await session.scalars(select(Skill))).all()
    skill_by_name = {row.name.casefold(): row for row in skill_rows}
    skill_by_alias = dict(skill_by_name)
    for alias, skill_name in (
        await session.execute(
            select(SkillAlias.alias, Skill.name).join(Skill, Skill.id == SkillAlias.skill_id)
        )
    ).all():
        skill_by_alias[alias.casefold()] = skill_by_name[skill_name.casefold()]
    created = []
    rejected_count = 0
    for candidate in output.questions[:limit]:
        if is_duplicate_question(candidate.question_text, existing_texts):
            rejected_count += 1
            continue
        if any(name.casefold() not in skill_by_alias for name in candidate.skills):
            rejected_count += 1
            continue
        names = list(
            dict.fromkeys(
                skill_by_alias[name.casefold()].name
                for name in candidate.skills
                if name.casefold() in skill_by_alias
            )
        )
        primary = skill_by_alias.get(candidate.primary_skill.casefold())
        if (
            not primary
            or primary.name not in names
            or primary.name not in gaps
            or not any(
                alias.casefold() in candidate.question_text.casefold()
                for alias, skill in skill_by_alias.items()
                if skill.id == primary.id
            )
        ):
            rejected_count += 1
            continue
        stable_key = (
            "ai-" + hashlib.sha256(candidate.question_text.casefold().encode()).hexdigest()[:40]
        )
        question = Question(
            stable_key=stable_key,
            question_text=candidate.question_text,
            question_type=candidate.question_type,
            difficulty=candidate.difficulty,
            role_family=job.role_family,
            category="ai_targeted_practice",
            primary_skill_id=primary.id,
            expected_points="\n".join(candidate.expected_points),
            reference_answer=candidate.reference_answer,
            common_mistakes=[],
            rubric=candidate.rubric,
            provenance="ai_generated",
            validation_status="generated_pending_review",
            version=1,
        )
        question.skills = [QuestionSkill(skill=skill_by_name[name.casefold()]) for name in names]
        question.role_families = [QuestionRoleFamily(role_family=job.role_family)]
        session.add(question)
        await session.flush()
        created.append(question)
        existing_texts.append(candidate.question_text)
    run_status = "generated_pending_review" if created else "rejected_validation"
    run = ContentGenerationRun(
        content_type="targeted_questions",
        provider=provider.provider_name,
        model=provider.model_name,
        input_fingerprint=fingerprint,
        status=run_status,
        validation_metadata="\n".join(q.stable_key for q in created),
    )
    session.add(run)
    await session.commit()
    logger.info(
        "question_generation_complete",
        extra={
            "ai_provider": provider.provider_name,
            "ai_model": provider.model_name,
            "generation_accepted": len(created),
            "generation_rejected": rejected_count,
        },
    )
    return {
        "status": run_status,
        "uncovered_skills": gaps,
        "questions": [
            {
                "id": str(q.id),
                "stable_key": q.stable_key,
                "question": q.question_text,
                "difficulty": q.difficulty,
                "skills": [row.skill.name for row in q.skills],
                "reference_answer": q.reference_answer,
                "rubric": q.rubric,
                "provenance": q.provenance,
                "validation_status": q.validation_status,
                "model": provider.model_name,
            }
            for q in created
        ],
    }


def _session_question(question: Question, mode: str):
    query = question_payload(question)
    if mode != "guided_practice":
        query.pop("reference_answer", None)
        query.pop("expected_points", None)
    return query


async def _session_payload(session: AsyncSession, practice: PracticeSession):
    queue = practice.question_queue or []
    current = None
    if practice.status == "in_progress" and practice.current_position < len(queue):
        qid = UUID(queue[practice.current_position])
        question = await session.scalar(
            select(Question)
            .options(
                selectinload(Question.skills).selectinload(QuestionSkill.skill),
                selectinload(Question.role_families),
            )
            .where(Question.id == qid)
        )
        if question:
            current = _session_question(question, practice.mode)
    last_feedback = None
    if practice.current_position > 0:
        response_row = await session.scalar(
            select(CandidateResponse)
            .where(CandidateResponse.session_id == practice.id)
            .order_by(CandidateResponse.created_at.desc())
            .limit(1)
        )
        if response_row:
            answered_question = await session.get(Question, response_row.question_id)
            last_feedback = {
                "evaluation": response_row.evaluation or {},
                "evaluation_method": response_row.evaluation_method,
                "reference_answer": answered_question.reference_answer
                if answered_question
                else None,
            }
    return {
        "id": str(practice.id),
        "plan_id": str(practice.plan_id),
        "mode": practice.mode,
        "status": practice.status,
        "position": practice.current_position,
        "question_count": len(queue),
        "current_question": current,
        "last_feedback": last_feedback,
        "started_at": practice.started_at.isoformat() if practice.started_at else None,
        "completed_at": practice.completed_at.isoformat() if practice.completed_at else None,
        "resume_notice": "Assessment modes hide reference answers until submission.",
    }


@app.post("/api/v1/practice-sessions", status_code=201)
async def start_practice_session(
    payload: PracticeSessionCreate, session: AsyncSession = Depends(session_dependency)
):
    plan = await session.get(PreparationPlan, payload.plan_id)
    if plan is None:
        raise HTTPException(404, "Preparation plan not found")
    items = (
        await session.scalars(
            select(PlanItem)
            .where(
                PlanItem.plan_id == plan.id,
                PlanItem.item_type == "question",
                PlanItem.question_id.is_not(None),
            )
            .order_by(PlanItem.position)
        )
    ).all()
    qids = [str(item.question_id) for item in items]
    if payload.mode == "behavioral":
        questions = (
            (
                await session.scalars(
                    select(Question).where(Question.id.in_([UUID(qid) for qid in qids]))
                )
            ).all()
            if qids
            else []
        )
        behavioral_ids = {
            str(q.id)
            for q in questions
            if q.question_type == "behavioral" or (q.category or "").startswith("behavioral")
        }
        qids = [qid for qid in qids if qid in behavioral_ids]
    elif payload.mode == "technical_mock":
        questions = (
            (
                await session.scalars(
                    select(Question).where(Question.id.in_([UUID(qid) for qid in qids]))
                )
            ).all()
            if qids
            else []
        )
        non_behavioral = {
            str(q.id)
            for q in questions
            if q.question_type != "behavioral" and not (q.category or "").startswith("behavioral")
        }
        qids = [qid for qid in qids if qid in non_behavioral]
    if not qids:
        raise HTTPException(
            422, "This preparation plan has no questions for the selected practice mode"
        )
    practice = PracticeSession(
        plan_id=plan.id,
        mode=payload.mode,
        question_queue=qids,
        current_position=0,
        status="in_progress",
    )
    session.add(practice)
    await session.commit()
    await session.refresh(practice)
    return await _session_payload(session, practice)


@app.get("/api/v1/practice-sessions/{session_id}")
async def get_practice_session(
    session_id: UUID, session: AsyncSession = Depends(session_dependency)
):
    practice = await session.get(PracticeSession, session_id)
    if practice is None:
        raise HTTPException(404, "Practice session not found")
    return await _session_payload(session, practice)


@app.post("/api/v1/practice-sessions/{session_id}/next")
async def next_practice_question(
    session_id: UUID, session: AsyncSession = Depends(session_dependency)
):
    practice = await session.get(PracticeSession, session_id)
    if practice is None:
        raise HTTPException(404, "Practice session not found")
    return await _session_payload(session, practice)


@app.post("/api/v1/practice-sessions/{session_id}/responses")
async def submit_practice_response(
    session_id: UUID,
    request: Request,
    payload: PracticeResponseCreate,
    session: AsyncSession = Depends(session_dependency),
):
    practice = await session.scalar(
        select(PracticeSession).where(PracticeSession.id == session_id).with_for_update()
    )
    if practice is None:
        raise HTTPException(404, "Practice session not found")
    if payload.submission_key:
        prior = await session.scalar(
            select(CandidateResponse).where(
                CandidateResponse.submission_key == payload.submission_key
            )
        )
        if prior:
            return {
                "status": "duplicate_submission",
                "evaluation": prior.evaluation,
                "session": await _session_payload(session, practice),
            }
    if practice.status != "in_progress":
        raise HTTPException(409, "Practice session is already complete")
    queue = practice.question_queue or []
    if practice.current_position >= len(queue):
        practice.status = "completed"
        practice.completed_at = datetime.now(UTC)
        await session.commit()
        return {"status": "completed", "session": await _session_payload(session, practice)}
    question = await session.scalar(
        select(Question)
        .options(
            selectinload(Question.skills).selectinload(QuestionSkill.skill),
            selectinload(Question.role_families),
        )
        .where(Question.id == UUID(queue[practice.current_position]))
    )
    if question is None:
        raise HTTPException(409, "Current question is no longer available")
    expected = question.expected_points.splitlines()
    evaluation = fallback_evaluate(expected, question.rubric, payload.answer)
    method = "deterministic_keyword_heuristic"
    if payload.allow_ai_evaluation:
        enforce_ai_rate_limit(request)
        try:
            provider = get_ai_provider()
            ai_result = await provider.evaluate_answer(
                question.question_text, question.rubric, payload.answer
            )
            if any(
                (item.assessment in {"demonstrated", "partial"} and not item.evidence.strip())
                or (item.evidence and item.evidence.casefold() not in payload.answer.casefold())
                for item in ai_result.criteria
            ):
                raise AIProviderError("AI evaluation evidence was not grounded in the answer")
            evaluation = ai_result.model_dump() | {"method": "ai_rubric", "approximate": True}
            method = "ai_rubric"
        except AIConfigurationError as exc:
            if settings.ai_provider == "openai":
                raise HTTPException(503, str(exc)) from exc
            evaluation["provider_notice"] = "AI is disabled; the local rubric heuristic was used."
        except AIProviderError:
            evaluation["provider_notice"] = (
                "AI evaluation was unavailable; the local rubric heuristic was used."
            )
    logger.info(
        "answer_evaluation_complete",
        extra={"evaluation_method": method, "evaluation_outcome": evaluation.get("outcome")},
    )
    response_row = CandidateResponse(
        session_id=practice.id,
        question_id=question.id,
        response_text=payload.answer,
        evaluation=evaluation,
        evaluation_method=method,
        submission_key=payload.submission_key,
    )
    session.add(response_row)
    queue_meta = {}
    if len(queue) > practice.current_position + 1:
        rows = (
            await session.scalars(
                select(Question)
                .options(selectinload(Question.skills).selectinload(QuestionSkill.skill))
                .where(
                    Question.id.in_(
                        [UUID(value) for value in queue[practice.current_position + 1 :]]
                    )
                )
            )
        ).all()
        queue_meta = {
            str(row.id): {
                "primary_skill": next(
                    (
                        skill.skill.name
                        for skill in row.skills
                        if skill.skill_id == row.primary_skill_id
                    ),
                    None,
                ),
                "difficulty": row.difficulty,
            }
            for row in rows
        }
    primary_skill = next(
        (item.skill.name for item in question.skills if item.skill_id == question.primary_skill_id),
        None,
    )
    remaining = queue[practice.current_position + 1 :]
    adaptive = reorder_adaptive_queue(remaining, queue_meta, primary_skill, evaluation["outcome"])
    practice.question_queue = queue[: practice.current_position + 1] + adaptive
    practice.current_position += 1
    if practice.current_position >= len(practice.question_queue):
        practice.status = "completed"
        practice.completed_at = datetime.now(UTC)
    await session.commit()
    return {
        "status": practice.status,
        "submitted_question_id": str(question.id),
        "evaluation": evaluation,
        "evaluation_method": method,
        "reference_answer": question.reference_answer,
        "adaptation": {
            "outcome": evaluation["outcome"],
            "next_question_adjusted": adaptive != remaining,
            "strategy": "same-skill difficulty adjustment, bounded to unanswered plan questions",
        },
        "session": await _session_payload(session, practice),
    }


@app.get("/api/v1/practice-sessions/{session_id}/results")
async def practice_session_results(
    session_id: UUID, session: AsyncSession = Depends(session_dependency)
):
    practice = await session.get(PracticeSession, session_id)
    if practice is None:
        raise HTTPException(404, "Practice session not found")
    rows = (
        await session.execute(
            select(CandidateResponse, Question)
            .options(selectinload(Question.skills).selectinload(QuestionSkill.skill))
            .join(Question, Question.id == CandidateResponse.question_id)
            .where(CandidateResponse.session_id == practice.id)
            .order_by(CandidateResponse.created_at)
        )
    ).all()
    weak = {}
    responses = []
    for response, question in rows:
        evaluation = response.evaluation or {}
        if evaluation.get("outcome") in {"partial", "needs_review"}:
            for item in question.skills:
                weak[item.skill.name] = weak.get(item.skill.name, 0) + 1
        responses.append(
            {
                "question_id": str(question.id),
                "question": question.question_text,
                "answer": response.response_text,
                "reference_answer": question.reference_answer,
                "evaluation": evaluation,
                "evaluation_method": response.evaluation_method,
            }
        )
    return {
        "session_id": str(practice.id),
        "status": practice.status,
        "mode": practice.mode,
        "responses": responses,
        "weak_skills_revision_queue": sorted(weak, key=lambda key: (-weak[key], key)),
        "approximate_feedback_notice": "AI and deterministic evaluations are practice guidance, not validated assessments.",
    }
