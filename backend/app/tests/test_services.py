from app.seed import validate_seed_content
from app.services import (
    RankingWeights,
    analyze_job,
    build_content_coverage,
    detect_job_duplicate,
    normalize_source_url,
    rank_question,
    select_balanced_questions,
)


def test_alias_normalization_and_false_positive_prevention():
    profile = analyze_job(
        "Senior Backend Engineer", "Required skills: Python 3, Postgres, and REST APIs."
    )
    names = {item["name"] for item in profile["required_skills"]}
    assert {"Python", "PostgreSQL", "REST APIs"}.issubset(names)
    unrelated = analyze_job(
        "Analyst", "The word 'postgraduate' and a JavaScript button appear in this description."
    )
    assert "PostgreSQL" not in {
        item["name"] for item in unrelated["required_skills"] + unrelated["mentioned_skills"]
    }
    assert "Java" not in {
        item["name"] for item in unrelated["required_skills"] + unrelated["mentioned_skills"]
    }


def test_job_extraction_distinguishes_preferred_and_parses_explicit_sections():
    description = """Required skills: Python and SQL.

Responsibilities:
- Build reliable APIs for internal teams.
- Diagnose data pipeline incidents.

Qualifications:
- Three years of backend experience.

Nice to have: Docker.
"""
    profile = analyze_job("Senior Backend Engineer", description)
    assert {x["name"] for x in profile["required_skills"]} == {"Python", "SQL"}
    assert [x["name"] for x in profile["preferred_skills"]] == ["Docker"]
    assert len(profile["responsibilities"]) == 2
    assert profile["qualifications"] == ["Three years of backend experience."]
    assert profile["seniority"] == "senior"


def test_normalized_source_url_and_conservative_duplicate_detection():
    canonical = normalize_source_url("https://www.example.com/jobs/123/?utm_source=mail&ref=home")
    assert canonical == "https://example.com/jobs/123"
    listing = {
        "id": 1,
        "role_title": "Backend Engineer",
        "company_name": "Acme",
        "description": "Python backend APIs and relational databases. " * 5,
        "normalized_source_url": canonical,
    }
    match, reason = detect_job_duplicate(
        [listing],
        title="Backend Engineer",
        company="Acme",
        description="Completely different role involving embedded systems and C++. " * 5,
        normalized_url=canonical,
    )
    assert match == listing and reason == "source_url"
    no_match, _ = detect_job_duplicate(
        [listing],
        title="Backend Engineer",
        company="Other",
        description=listing["description"],
        normalized_url=None,
    )
    assert no_match is None


def test_required_skill_weighting_and_explainable_role_relevance():
    question = {
        "id": "q1",
        "stable_key": "python-api",
        "skills": ["Python"],
        "role_families": ["backend"],
        "category": "api_design",
    }
    ranked = rank_question(
        question,
        role_family="backend",
        required={"Python", "SQL"},
        preferred={"Docker"},
        competencies=set(),
    )
    assert ranked["relevance_score"] == 47
    assert "Matches required skill: Python." in ranked["match_reasons"]
    weights = RankingWeights()
    assert weights.required_skill > weights.preferred_skill


def test_balanced_plan_prioritizes_uncovered_required_skills_without_duplicates():
    candidates = [
        {
            "id": "q1",
            "stable_key": "python-1",
            "skills": ["Python"],
            "category": "fundamentals",
            "relevance_score": 70,
        },
        {
            "id": "q2",
            "stable_key": "python-2",
            "skills": ["Python"],
            "category": "fundamentals",
            "relevance_score": 69,
        },
        {
            "id": "q3",
            "stable_key": "sql-1",
            "skills": ["SQL"],
            "category": "sql_data",
            "relevance_score": 55,
        },
        {
            "id": "q4",
            "stable_key": "weak",
            "skills": ["Git"],
            "category": "collaboration",
            "relevance_score": 0,
        },
    ]
    selected = select_balanced_questions(candidates, 3, {"Python", "SQL"})
    assert [item["stable_key"] for item in selected] == ["python-1", "sql-1", "python-2"]
    assert [item["position"] for item in selected] == [1, 2, 3]


def test_coverage_reports_missing_questions_and_learning_content():
    coverage = build_content_coverage(
        {"Python", "SQL"},
        {"Docker"},
        [{"skills": ["Python"], "category": "coding_algorithms", "difficulty": "beginner"}],
        [{"skills": ["SQL"]}],
    )
    assert coverage["required_skills_without_questions"] == ["SQL"]
    assert coverage["required_skills_without_learning"] == ["Python"]
    assert coverage["preferred_skills_without_questions"] == ["Docker"]
    assert coverage["content_coverage_percent"] == 67


def test_curated_content_passes_schema_and_duplicate_validation():
    questions, modules = validate_seed_content()
    assert len(questions) >= 45
    assert len(modules) >= 10
    assert len({item.stable_key for item in questions}) == len(questions)
    assert any(item.question_type == "coding" for item in questions)
    assert any(item.question_type == "sql" for item in questions)
    assert any(item.question_type == "behavioral" for item in questions)
