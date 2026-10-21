import argparse
import re
from difflib import SequenceMatcher

from sqlalchemy import delete, select

from app.catalog_content import DEMO_JOBS, MODULE_CONTENT, QUESTION_CONTENT
from app.core.database import SessionLocal
from app.models import (
    Company,
    JobPost,
    JobPostVersion,
    JobSkill,
    LearningModule,
    LearningModuleSkill,
    Question,
    QuestionRoleFamily,
    QuestionSkill,
    Skill,
    SkillAlias,
    SkillRoleFamily,
)
from app.schemas import LearningModuleSeed, QuestionSeed
from app.services import analyze_job, description_hash, normalize_source_url
from app.taxonomy import ROLE_FAMILIES, SKILL_TAXONOMY

CONTENT_VERSION = 2

SKILL_ROLES = {
    "Python": ["backend", "data_engineer", "data_analyst", "ml_engineer", "qa_automation"],
    "SQL": ["backend", "data_engineer", "data_analyst"],
    "PostgreSQL": ["backend", "data_engineer", "data_analyst"],
    "JavaScript": ["frontend", "qa_automation"],
    "TypeScript": ["frontend", "qa_automation"],
    "React": ["frontend"],
    "Machine Learning": ["ml_engineer", "data_analyst"],
    "Statistics and Probability": ["ml_engineer", "data_analyst"],
    "REST APIs": ["backend", "frontend", "qa_automation"],
    "Docker": ["platform", "backend"],
    "Kubernetes": ["platform"],
    "AWS": ["platform", "data_engineer", "ml_engineer"],
    "Testing": ["qa_automation", "frontend", "backend"],
    "System Design": ["backend", "distributed", "platform"],
    "Operating Systems": ["systems", "platform"],
    "Computer Networks": ["systems", "platform", "security"],
    "Application Security": ["security", "backend"],
    "Linux": ["systems", "platform", "security"],
    "ETL": ["data_engineer", "data_analyst"],
    "Apache Kafka": ["data_engineer", "distributed"],
    "Data Visualization": ["data_analyst"],
    "Data Structures and Algorithms": ["backend", "frontend", "systems"],
}


def validate_seed_content():
    questions = [QuestionSeed.model_validate(item) for item in QUESTION_CONTENT]
    modules = [LearningModuleSeed.model_validate(item) for item in MODULE_CONTENT]
    keys = [item.stable_key for item in questions]
    normalized_texts = [
        re.sub(r"\W+", " ", item.question_text.lower()).strip() for item in questions
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("Question seed contains duplicate stable keys")
    if len(normalized_texts) != len(set(normalized_texts)):
        raise ValueError("Question seed contains duplicate question text")
    canonical = {item["name"] for item in SKILL_TAXONOMY}
    aliases = [
        alias.casefold() for item in SKILL_TAXONOMY for alias in [item["name"], *item["aliases"]]
    ]
    if len(aliases) != len(set(aliases)):
        raise ValueError("Skill taxonomy contains duplicate canonical names or aliases")
    valid_roles = set(ROLE_FAMILIES)
    for item in questions:
        if item.primary_skill not in item.skills or not set(item.skills) <= canonical:
            raise ValueError(f"Question {item.stable_key} references a non-canonical skill")
        if not set(item.role_families) <= valid_roles:
            raise ValueError(f"Question {item.stable_key} references an unknown role family")
    for item in modules:
        if item.skill not in canonical or not set(item.prerequisites) <= {
            m.stable_key for m in modules
        }:
            raise ValueError(f"Learning module {item.stable_key} references invalid metadata")
    return questions, modules


async def seed_catalogue(include_demo_jobs: bool = False):
    questions, modules = validate_seed_content()
    async with SessionLocal() as session:
        skills: dict[str, Skill] = {}
        for definition in SKILL_TAXONOMY:
            skill = await session.scalar(select(Skill).where(Skill.name == definition["name"]))
            if skill is None:
                skill = Skill(name=definition["name"], category=definition["category"])
                session.add(skill)
                await session.flush()
            else:
                skill.category = definition["category"]
            skills[definition["name"]] = skill
            for alias in definition["aliases"]:
                existing = await session.scalar(
                    select(SkillAlias).where(SkillAlias.alias.ilike(alias))
                )
                if existing is None:
                    session.add(SkillAlias(skill_id=skill.id, alias=alias))
            for role in SKILL_ROLES.get(definition["name"], []):
                link = await session.get(SkillRoleFamily, (skill.id, role))
                if link is None:
                    session.add(SkillRoleFamily(skill_id=skill.id, role_family=role))
        await session.flush()

        question_count = 0
        question_update_count = 0
        existing_texts = list((await session.scalars(select(Question.question_text))).all())
        for item in questions:
            existing = await session.scalar(
                select(Question).where(Question.stable_key == item.stable_key)
            )
            duplicate_text = await session.scalar(
                select(Question).where(Question.question_text.ilike(item.question_text))
            )
            near_duplicate = duplicate_text is None and any(
                SequenceMatcher(None, item.question_text.casefold(), text.casefold()).ratio()
                >= 0.96
                for text in existing_texts
            )
            if duplicate_text is not None and existing is None:
                continue
            if near_duplicate and existing is None:
                continue
            if existing is not None and (
                existing.provenance != "curated_practice" or existing.version >= CONTENT_VERSION
            ):
                continue
            question = existing or Question(stable_key=item.stable_key, provenance=item.provenance)
            question.question_text = item.question_text
            question.question_type = item.question_type
            question.difficulty = item.difficulty
            question.role_family = item.role_families[0]
            question.category = item.category
            question.competencies = item.competencies
            question.primary_skill_id = skills[item.primary_skill].id
            question.expected_points = "\n".join(item.expected_points)
            question.reference_answer = item.reference_answer
            question.common_mistakes = item.common_mistakes
            question.rubric = item.rubric
            question.validation_status = "reviewed"
            question.version = CONTENT_VERSION
            session.add(question)
            await session.flush()
            if existing is not None:
                await session.execute(
                    delete(QuestionSkill).where(QuestionSkill.question_id == question.id)
                )
                await session.execute(
                    delete(QuestionRoleFamily).where(QuestionRoleFamily.question_id == question.id)
                )
                question_update_count += 1
            session.add_all(
                [
                    QuestionSkill(question_id=question.id, skill_id=skills[name].id)
                    for name in item.skills
                ]
            )
            session.add_all(
                [
                    QuestionRoleFamily(question_id=question.id, role_family=role)
                    for role in item.role_families
                ]
            )
            existing_texts.append(item.question_text)
            question_count += int(existing is None)

        module_count = 0
        for item in modules:
            existing = await session.scalar(
                select(LearningModule).where(LearningModule.stable_key == item.stable_key)
            )
            if existing is not None and existing.version >= CONTENT_VERSION:
                continue
            module = existing or LearningModule(stable_key=item.stable_key)
            module.title = item.title
            module.purpose = item.purpose
            module.content = item.content
            module.estimated_minutes = item.minutes
            module.learning_objectives = item.objectives
            module.core_concepts = item.concepts
            module.examples = item.examples
            module.common_mistakes = item.mistakes
            module.practical_exercises = item.exercises
            module.revision_checklist = item.checklist
            module.prerequisites = item.prerequisites
            module.validation_status = "reviewed"
            module.version = CONTENT_VERSION
            session.add(module)
            await session.flush()
            if existing is not None:
                await session.execute(
                    delete(LearningModuleSkill).where(LearningModuleSkill.module_id == module.id)
                )
            session.add(LearningModuleSkill(module_id=module.id, skill_id=skills[item.skill].id))
            module_count += int(existing is None)

        demo_count = 0
        if include_demo_jobs:
            company = await session.scalar(
                select(Company).where(Company.name == "RIGOR Demonstration")
            )
            if company is None:
                company = Company(name="RIGOR Demonstration")
                session.add(company)
                await session.flush()
            for title, family, stack, responsibilities in DEMO_JOBS:
                slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                source_url = f"https://demo.rigor.invalid/roles/{slug}"
                normalized_url = normalize_source_url(source_url)
                existing = await session.scalar(
                    select(JobPost).where(JobPost.normalized_source_url == normalized_url)
                )
                if existing is not None:
                    continue
                description = (
                    f"Demonstration listing only. This is fictional practice data, not an open vacancy.\n\n"
                    f"Required skills: {stack}.\n\nResponsibilities:\n- {responsibilities}"
                )
                profile = analyze_job(title, description)
                job = JobPost(
                    company=company,
                    company_name=company.name,
                    role_title=title,
                    description=description,
                    role_family=family,
                    source_url=source_url,
                    normalized_source_url=normalized_url,
                    source_type="demonstration",
                    is_demo=True,
                    status="active",
                    responsibilities=profile["responsibilities"],
                    qualifications=profile["qualifications"],
                    competencies=profile["competencies"],
                    tools_technologies=profile["tools_technologies"],
                )
                session.add(job)
                session.add(
                    JobPostVersion(
                        job=job,
                        version=1,
                        description=description,
                        role_title=title,
                        company_name=company.name,
                        content_hash=description_hash(description),
                    )
                )
                for kind, key in (
                    ("required", "required_skills"),
                    ("preferred", "preferred_skills"),
                    ("mentioned", "mentioned_skills"),
                ):
                    for evidence in profile[key]:
                        session.add(
                            JobSkill(
                                job=job,
                                skill=skills[evidence["name"]],
                                requirement_type=kind,
                                evidence=evidence["evidence"],
                                extraction_method=profile["method"],
                            )
                        )
                demo_count += 1
        await session.commit()
        return {
            "questions_added": question_count,
            "questions_updated": question_update_count,
            "modules_added": module_count,
            "demo_jobs_added": demo_count,
        }


async def main():
    parser = argparse.ArgumentParser(description="Seed RIGOR's reviewed content catalogue.")
    parser.add_argument(
        "--without-demo-jobs",
        action="store_true",
        help="Seed reviewed questions and learning modules but omit fictional demo jobs.",
    )
    args = parser.parse_args()
    result = await seed_catalogue(include_demo_jobs=not args.without_demo_jobs)
    print(result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
