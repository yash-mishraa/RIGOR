from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, case, delete, exists, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.models import (
    Company,
    JobPost,
    JobPostVersion,
    JobSkill,
    LearningModule,
    LearningModuleSkill,
    PlanItem,
    PreparationPlan,
    Question,
    QuestionRoleFamily,
    QuestionSkill,
    Skill,
    SkillAlias,
)
from app.schemas import JobImport, JobPage, PlanCreate
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="RIGOR Interview Workbench API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


async def session_dependency():
    async with SessionLocal() as session:
        yield session


@app.get("/api/v1/health")
async def health(session: AsyncSession = Depends(session_dependency)):
    try:
        await session.execute(select(1))
        return {"status": "ok", "database": "ready"}
    except SQLAlchemyError:
        return {"status": "ok", "database": "unavailable"}


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
async def analyse(job_id: UUID, session: AsyncSession = Depends(session_dependency)):
    job = await session.get(JobPost, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    profile = analyze_job(job.role_title, job.description)
    return {
        "job_id": str(job.id),
        "analysis": profile,
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
        .where(Question.id == question_id)
    )
    question = await session.scalar(query)
    if question is None:
        raise HTTPException(404, "Question not found")
    return question_payload(question)


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
