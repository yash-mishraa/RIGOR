from datetime import datetime
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def new_id():
    return uuid4()


class DemoVisitorSession(Base):
    __tablename__ = "demo_visitor_sessions"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequestRateBucket(Base):
    __tablename__ = "request_rate_buckets"
    bucket_key: Mapped[str] = mapped_column(String(240), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    jobs: Mapped[list["JobPost"]] = relationship(back_populates="company")


class JobPost(Base):
    __tablename__ = "job_posts"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    company_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL")
    )
    company_name: Mapped[str | None] = mapped_column(String(200))
    role_title: Mapped[str] = mapped_column(String(240), index=True)
    description: Mapped[str] = mapped_column(Text)
    role_family: Mapped[str] = mapped_column(String(80), index=True)
    seniority: Mapped[str | None] = mapped_column(String(80), index=True)
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    employment_type: Mapped[str | None] = mapped_column(String(80))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    normalized_source_url: Mapped[str | None] = mapped_column(String(2048), index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="user_import")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_session_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("demo_visitor_sessions.id", ondelete="CASCADE"), index=True
    )
    responsibilities: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    qualifications: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    competencies: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    tools_technologies: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)
    ai_analysis_fingerprint: Mapped[str | None] = mapped_column(String(64))
    content_version: Mapped[int] = mapped_column(Integer, default=1)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    company: Mapped[Company | None] = relationship(back_populates="jobs")
    skills: Mapped[list["JobSkill"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    versions: Mapped[list["JobPostVersion"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobPostVersion(Base):
    __tablename__ = "job_post_versions"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    job_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("job_posts.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    role_title: Mapped[str | None] = mapped_column(String(240))
    company_name: Mapped[str | None] = mapped_column(String(200))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    job: Mapped[JobPost] = relationship(back_populates="versions")
    __table_args__ = (UniqueConstraint("job_id", "version"),)


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(80), default="technical")
    aliases: Mapped[list["SkillAlias"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )


class SkillAlias(Base):
    __tablename__ = "skill_aliases"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    skill_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    skill: Mapped[Skill] = relationship(back_populates="aliases")


class SkillRoleFamily(Base):
    __tablename__ = "skill_role_families"
    skill_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    role_family: Mapped[str] = mapped_column(String(80), primary_key=True)


class JobSkill(Base):
    __tablename__ = "job_skills"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    job_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("job_posts.id", ondelete="CASCADE"), index=True
    )
    skill_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), index=True
    )
    requirement_type: Mapped[str] = mapped_column(String(20))
    evidence: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(40), default="deterministic_taxonomy")
    job: Mapped[JobPost] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship()
    __table_args__ = (UniqueConstraint("job_id", "skill_id", "requirement_type"),)


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    question_text: Mapped[str] = mapped_column(Text)
    stable_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    question_type: Mapped[str] = mapped_column(String(40), default="technical")
    difficulty: Mapped[str] = mapped_column(String(24), default="intermediate")
    role_family: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str] = mapped_column(String(60), default="technical_fundamentals", index=True)
    competencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    primary_skill_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL")
    )
    expected_points: Mapped[str] = mapped_column(Text, default="")
    reference_answer: Mapped[str] = mapped_column(Text, default="")
    common_mistakes: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    rubric: Mapped[str] = mapped_column(Text, default="")
    provenance: Mapped[str] = mapped_column(String(40), default="curated_practice")
    validation_status: Mapped[str] = mapped_column(String(30), default="reviewed")
    owner_session_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("demo_visitor_sessions.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    skills: Mapped[list["QuestionSkill"]] = relationship(cascade="all, delete-orphan")
    role_families: Mapped[list["QuestionRoleFamily"]] = relationship(cascade="all, delete-orphan")


class QuestionSkill(Base):
    __tablename__ = "question_skills"
    question_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    skill: Mapped[Skill] = relationship()


class QuestionRoleFamily(Base):
    __tablename__ = "question_role_families"
    question_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    role_family: Mapped[str] = mapped_column(String(80), primary_key=True)


class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255))
    content_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    skills: Mapped[list["ResumeSkill"]] = relationship(cascade="all, delete-orphan")


class ResumeSkill(Base):
    __tablename__ = "resume_skills"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    resume_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    skill_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), index=True
    )
    evidence: Mapped[str] = mapped_column(Text)
    evidence_type: Mapped[str] = mapped_column(String(30), default="resume_text")
    resume: Mapped[Resume] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship()
    __table_args__ = (UniqueConstraint("resume_id", "skill_id", "evidence"),)


class LearningModule(Base):
    __tablename__ = "learning_modules"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(240))
    purpose: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, default="")
    stable_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    learning_objectives: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    core_concepts: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    examples: Mapped[str] = mapped_column(Text, default="")
    common_mistakes: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    practical_exercises: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    revision_checklist: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    prerequisites: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    validation_status: Mapped[str] = mapped_column(String(30), default="reviewed")
    skills: Mapped[list["LearningModuleSkill"]] = relationship(cascade="all, delete-orphan")


class LearningModuleSkill(Base):
    __tablename__ = "learning_module_skills"
    module_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("learning_modules.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    skill: Mapped[Skill] = relationship()


class PlanItem(Base):
    __tablename__ = "plan_items"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    plan_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("preparation_plans.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    item_type: Mapped[str] = mapped_column(String(20))
    question_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    module_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("learning_modules.id", ondelete="SET NULL")
    )
    relevance_score: Mapped[float | None] = mapped_column()
    match_reasons: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    __table_args__ = (UniqueConstraint("plan_id", "position"),)


class ContentGenerationRun(Base):
    __tablename__ = "content_generation_runs"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    content_type: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(80), default="deterministic")
    model: Mapped[str | None] = mapped_column(String(120))
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="not_requested")
    owner_session_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("demo_visitor_sessions.id", ondelete="CASCADE"), index=True
    )
    validation_metadata: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PreparationPlan(Base):
    __tablename__ = "preparation_plans"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    job_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("job_posts.id", ondelete="CASCADE"), index=True
    )
    resume_id: Mapped[PyUUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    owner_session_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("demo_visitor_sessions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="active")
    content_coverage: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    plan_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("preparation_plans.id", ondelete="CASCADE"), index=True
    )
    owner_session_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("demo_visitor_sessions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="in_progress")
    mode: Mapped[str] = mapped_column(String(32), default="guided_practice")
    current_position: Mapped[int] = mapped_column(Integer, default=0)
    question_queue: Mapped[list[str]] = mapped_column(JSON, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CandidateResponse(Base):
    __tablename__ = "candidate_responses"
    id: Mapped[PyUUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    session_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), index=True
    )
    owner_session_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("demo_visitor_sessions.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[PyUUID] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"))
    response_text: Mapped[str] = mapped_column(Text)
    evaluation: Mapped[dict | None] = mapped_column(JSON)
    evaluation_method: Mapped[str | None] = mapped_column(String(40))
    submission_key: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index(
            "ix_candidate_responses_owner_submission_key",
            "owner_session_id",
            "submission_key",
            unique=True,
        ),
    )
