"""Optional structured AI provider adapters. Secrets stay in backend settings."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from app.core.config import settings


class SkillEvidence(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    evidence: str = Field(min_length=3, max_length=500)


class EvidenceStatement(BaseModel):
    statement: str = Field(min_length=3, max_length=500)
    evidence: str = Field(min_length=3, max_length=500)


class JobAnalysisOutput(BaseModel):
    responsibilities: list[EvidenceStatement] = Field(default_factory=list, max_length=15)
    competencies: list[EvidenceStatement] = Field(default_factory=list, max_length=12)
    required_skills: list[SkillEvidence] = Field(default_factory=list, max_length=30)
    preferred_skills: list[SkillEvidence] = Field(default_factory=list, max_length=30)
    seniority_clues: list[str] = Field(default_factory=list, max_length=8)


class GeneratedQuestion(BaseModel):
    question_text: str = Field(min_length=30, max_length=1500)
    question_type: str = Field(
        pattern=r"^(technical|coding|sql|scenario|behavioral|multiple_choice)$"
    )
    difficulty: str = Field(pattern=r"^(beginner|intermediate|advanced)$")
    primary_skill: str = Field(min_length=2, max_length=120)
    skills: list[str] = Field(min_length=1, max_length=8)
    expected_points: list[str] = Field(min_length=2, max_length=8)
    reference_answer: str = Field(min_length=80, max_length=2000)
    rubric: str = Field(min_length=40, max_length=800)


class QuestionGenerationOutput(BaseModel):
    questions: list[GeneratedQuestion] = Field(default_factory=list, max_length=5)


class CriterionAssessment(BaseModel):
    criterion: str = Field(min_length=2, max_length=120)
    assessment: str = Field(pattern=r"^(demonstrated|partial|not_demonstrated)$")
    evidence: str = Field(default="", max_length=500)


class AnswerEvaluationOutput(BaseModel):
    criteria: list[CriterionAssessment] = Field(min_length=1, max_length=8)
    strengths: list[str] = Field(default_factory=list, max_length=8)
    missing_concepts: list[str] = Field(default_factory=list, max_length=8)
    suggested_improvements: list[str] = Field(default_factory=list, max_length=8)
    follow_up_question: str | None = Field(default=None, max_length=1000)
    skill_feedback: list[str] = Field(default_factory=list, max_length=8)
    outcome: str = Field(pattern=r"^(strong|partial|needs_review)$")


class AIProvider(Protocol):
    provider_name: str
    model_name: str

    async def analyze_job(
        self, description: str, canonical_skills: list[str]
    ) -> JobAnalysisOutput: ...
    async def generate_questions(
        self, job_context: str, skill_names: list[str], limit: int
    ) -> QuestionGenerationOutput: ...
    async def evaluate_answer(
        self, question: str, rubric: str, answer: str
    ) -> AnswerEvaluationOutput: ...


class AIConfigurationError(RuntimeError):
    pass


class AIProviderError(RuntimeError):
    pass


class OpenAIProvider:
    provider_name = "openai"

    def __init__(self, api_key: str, model_name: str, timeout: float = 30.0):
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise AIConfigurationError(
                "Install the backend 'ai' extra to enable OpenAI features"
            ) from exc
        self.client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=1)
        self.model_name = model_name

    async def _parse(self, schema: type[BaseModel], instructions: str, payload: str):
        try:
            result = await self.client.chat.completions.parse(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": payload},
                ],
                response_format=schema,
                max_completion_tokens=settings.ai_max_output_tokens,
            )
            parsed = result.choices[0].message.parsed
            if parsed is None:
                raise AIProviderError("The AI provider returned no validated structured result")
            return parsed
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError("The configured AI provider request failed") from exc

    async def analyze_job(self, description: str, canonical_skills: list[str]) -> JobAnalysisOutput:
        return await self._parse(
            JobAnalysisOutput,
            "Extract only facts explicitly supported by the job text. Preserve short verbatim evidence. Never infer employer policies or interview questions. Select skills only from the supplied canonical list.",
            f"Canonical skills: {canonical_skills}\nJob description:\n{description[:18000]}",
        )

    async def generate_questions(
        self, job_context: str, skill_names: list[str], limit: int
    ) -> QuestionGenerationOutput:
        return await self._parse(
            QuestionGenerationOutput,
            "Create useful original practice questions for uncovered skills. Do not claim these are employer questions. Only use supplied skill names. Include accurate answers and explicit rubrics.",
            f"Job context:\n{job_context[:5000]}\nSkills: {skill_names}\nGenerate at most {limit} questions.",
        )

    async def evaluate_answer(
        self, question: str, rubric: str, answer: str
    ) -> AnswerEvaluationOutput:
        return await self._parse(
            AnswerEvaluationOutput,
            "Assess only the submitted answer against the rubric. Cite short evidence spans. Do not infer candidate traits. Use approximate qualitative categories, not a numeric score.",
            f"Question: {question}\nRubric: {rubric}\nCandidate answer:\n{answer[:10000]}",
        )


def get_ai_provider() -> AIProvider:
    if settings.ai_provider != "openai":
        raise AIConfigurationError(
            "AI is not configured. Set AI_PROVIDER=openai and OPENAI_API_KEY in backend/.env."
        )
    if not settings.openai_api_key:
        raise AIConfigurationError("OPENAI_API_KEY is required when AI_PROVIDER=openai.")
    return OpenAIProvider(settings.openai_api_key, settings.ai_model, settings.ai_timeout_seconds)
