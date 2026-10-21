from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class JobImport(BaseModel):
    role_title: str = Field(min_length=2, max_length=240)
    description: str = Field(min_length=80, max_length=30000)
    company_name: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    seniority: str | None = Field(default=None, max_length=80)
    employment_type: str | None = Field(default=None, max_length=80)
    source_url: HttpUrl | None = None

    @field_validator("role_title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip()

    @field_validator("description")
    @classmethod
    def retain_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value


class PlanCreate(BaseModel):
    job_id: UUID
    question_limit: int = Field(default=12, ge=1, le=50)


class QuestionSeed(BaseModel):
    stable_key: str = Field(min_length=3, max_length=160, pattern=r"^[a-z0-9][a-z0-9-]+$")
    question_text: str = Field(min_length=30, max_length=2000)
    primary_skill: str = Field(min_length=2, max_length=120)
    skills: list[str] = Field(min_length=1, max_length=8)
    role_families: list[str] = Field(min_length=1, max_length=10)
    question_type: str = Field(
        pattern=r"^(technical|coding|sql|scenario|behavioral|multiple_choice)$"
    )
    category: str = Field(min_length=3, max_length=60)
    competencies: list[str] = Field(default_factory=list, max_length=8)
    difficulty: str = Field(pattern=r"^(beginner|intermediate|advanced)$")
    expected_points: list[str] = Field(min_length=2, max_length=10)
    reference_answer: str = Field(min_length=80, max_length=2500)
    common_mistakes: list[str] = Field(default_factory=list, max_length=8)
    rubric: str = Field(min_length=40, max_length=1000)
    provenance: str = Field(default="curated_practice", pattern=r"^curated_practice$")


class LearningModuleSeed(BaseModel):
    stable_key: str = Field(min_length=3, max_length=160, pattern=r"^[a-z0-9][a-z0-9-]+$")
    title: str = Field(min_length=5, max_length=240)
    skill: str = Field(min_length=2, max_length=120)
    purpose: str = Field(min_length=20, max_length=500)
    minutes: int = Field(ge=5, le=240)
    objectives: list[str] = Field(min_length=2, max_length=8)
    concepts: list[str] = Field(min_length=2, max_length=12)
    content: str = Field(min_length=120, max_length=3000)
    examples: str = Field(min_length=50, max_length=1200)
    mistakes: list[str] = Field(min_length=2, max_length=8)
    exercises: list[str] = Field(min_length=1, max_length=8)
    checklist: list[str] = Field(min_length=2, max_length=8)
    prerequisites: list[str] = Field(default_factory=list, max_length=8)


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role_title: str
    company_name: str | None
    role_family: str
    seniority: str | None
    location: str | None
    employment_type: str | None
    status: str
    is_demo: bool
    imported_at: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)


class JobPage(BaseModel):
    items: list[JobSummary]
    total: int
    limit: int
    offset: int
    next_offset: int | None


class AnalyseRequest(BaseModel):
    use_ai: bool = False


class ResumeAnalysisRequest(BaseModel):
    resume_text: str = Field(min_length=20, max_length=100000)


class ResumeJobMatchRequest(ResumeAnalysisRequest):
    job_id: UUID


class GenerateQuestionsRequest(BaseModel):
    max_questions: int = Field(default=3, ge=1, le=5)


class QuestionReviewRequest(BaseModel):
    decision: str = Field(pattern=r"^(approve|reject)$")


class PracticeSessionCreate(BaseModel):
    plan_id: UUID
    mode: str = Field(pattern=r"^(guided_practice|technical_mock|resume_deep_dive|behavioral)$")


class PracticeResponseCreate(BaseModel):
    answer: str = Field(min_length=1, max_length=20000)
    allow_ai_evaluation: bool = False
    submission_key: str | None = Field(default=None, min_length=8, max_length=80)
