import pytest
from pydantic import ValidationError

from app.ai import AIConfigurationError, GeneratedQuestion
from app.personalization import (
    extract_resume_evidence,
    fallback_evaluate,
    is_duplicate_question,
    match_resume_to_job,
    reorder_adaptive_queue,
)


def test_resume_evidence_distinguishes_demonstrated_from_keyword_only():
    profile = extract_resume_evidence(
        "Skills: Python, PostgreSQL\nExperience\n- Built a Python service using PostgreSQL to process daily customer events.\nProjects:\n- Developed a reporting API using Python and PostgreSQL with automated tests."
    )
    match = match_resume_to_job(profile, ["Python", "PostgreSQL", "Docker"], ["AWS"])
    assert match["supported_required_skills"] == ["Python", "PostgreSQL"]
    assert match["required_skills_without_resume_evidence"] == ["Docker"]
    assert match["preferred_skills_without_demonstrated_evidence"] == ["AWS"]
    assert match["relevant_projects"]


def test_keyword_only_resume_mention_is_not_treated_as_proficiency():
    profile = extract_resume_evidence("Skills: Python, Docker")
    match = match_resume_to_job(profile, ["Python"], [])
    assert match["supported_required_skills"] == []
    assert match["required_skills_with_mentions_only"] == ["Python"]


def test_local_evaluation_is_explicitly_approximate_and_adaptation_is_bounded():
    result = fallback_evaluate(
        ["Validate input at boundaries", "Keep transactions short"],
        "Check correctness and safety",
        "Validate input at boundaries and keep transactions short.",
    )
    assert result["method"] == "deterministic_keyword_heuristic"
    assert result["approximate"] is True
    assert result["outcome"] == "strong"
    queue = reorder_adaptive_queue(
        ["q2", "q3"],
        {
            "q2": {"primary_skill": "Python", "difficulty": "advanced"},
            "q3": {"primary_skill": "SQL", "difficulty": "advanced"},
        },
        "Python",
        "strong",
    )
    assert queue == ["q2", "q3"]


def test_generation_duplicate_detector_and_output_schema():
    text = "How would you validate a request before storing a record in a production Python API?"
    assert is_duplicate_question(text, [text.lower()])
    assert not is_duplicate_question(text, ["Explain how database indexes speed up a query."])
    with pytest.raises(ValidationError):
        GeneratedQuestion(
            question_text="short",
            question_type="unknown",
            difficulty="expert",
            primary_skill="Python",
            skills=["Python"],
            expected_points=["one", "two"],
            reference_answer="short",
            rubric="short",
        )


def test_ai_provider_fails_clearly_when_not_configured(monkeypatch):
    from app import ai

    monkeypatch.setattr(ai.settings, "ai_provider", "none")
    with pytest.raises(AIConfigurationError, match="AI is not configured"):
        ai.get_ai_provider()
