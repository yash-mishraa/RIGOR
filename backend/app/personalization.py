"""Deterministic resume evidence, job match and practice adaptation helpers."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.ai import AnswerEvaluationOutput, CriterionAssessment
from app.services import _phrase_pattern, normalize_text
from app.taxonomy import SKILL_TAXONOMY

_ACTION = re.compile(
    r"\b(built|developed|designed|architected|implemented|maintained|led|improved|optimized|optimised|created|deployed|tested|analyzed|analysed|automated|reduced|increased|delivered|used|managed|owned|launched|scaled)\b",
    re.IGNORECASE,
)
_PROJECT_HEADING = re.compile(
    r"^\s*(projects?|selected projects?|personal projects?)\s*:?\s*$", re.IGNORECASE
)
_SECTION_HEADING = re.compile(
    r"^\s*(experience|work experience|employment history|education|qualifications|skills|technical skills|projects?)\s*:?\s*$",
    re.IGNORECASE,
)


def extract_resume_evidence(text: str) -> dict:
    lines = [
        normalize_text(re.sub(r"^\s*(?:[-*•▪]|\d+[.)])\s*", "", line)) for line in text.splitlines()
    ]
    lines = [line for line in lines if line]
    evidence = []
    for item in SKILL_TAXONOMY:
        occurrences = [
            line
            for line in lines
            if any(
                _phrase_pattern(alias).search(line) for alias in [item["name"], *item["aliases"]]
            )
        ]
        if not occurrences:
            continue
        excerpts = list(dict.fromkeys(occurrences))[:3]
        strong = [line for line in excerpts if _ACTION.search(line) and len(line.split()) >= 8]
        evidence.append(
            {
                "skill": item["name"],
                "category": item["category"],
                "evidence_level": "demonstrated" if strong else "mentioned",
                "evidence": strong[:2] or excerpts[:2],
            }
        )
    projects, experience, education, achievements = [], [], [], []
    in_projects, section = False, None
    for line in text.splitlines():
        heading = normalize_text(line)
        if _SECTION_HEADING.match(heading):
            section = heading.casefold().rstrip(":")
            in_projects = section in {"project", "projects"}
            continue
        if _PROJECT_HEADING.match(heading):
            in_projects = True
            section = "projects"
            continue
        clean = normalize_text(re.sub(r"^\s*(?:[-*•▪]|\d+[.)])\s*", "", line))
        if not clean:
            continue
        if section in {"experience", "work experience", "employment history"} and len(clean) >= 20:
            experience.append(clean[:500])
        elif section in {"education", "qualifications"} and len(clean) >= 10:
            education.append(clean[:300])
        if in_projects and len(clean) >= 20:
            matched = sorted(
                {row["skill"] for row in evidence if _phrase_pattern(row["skill"]).search(clean)}
            )
            projects.append({"description": clean[:500], "skills": matched})
        if re.search(
            r"\b(\d+(?:\.\d+)?%|\$\s?\d|\d+x|reduced|increased|saved|improved|grew|cut)\b",
            clean,
            re.IGNORECASE,
        ):
            achievements.append(clean[:500])
    tools = sorted(
        row["skill"]
        for row in evidence
        if row["category"]
        in {"tools", "cloud", "platform", "database", "programming", "machine_learning", "quality"}
    )
    return {
        "skills": evidence,
        "tools_and_technologies": tools,
        "projects": projects[:12],
        "work_experience_evidence": experience[:20],
        "education_evidence": education[:12],
        "measurable_achievements": list(dict.fromkeys(achievements))[:20],
        "evidence_count": sum(len(row["evidence"]) for row in evidence),
    }


def match_resume_to_job(profile: dict, required: list[str], preferred: list[str]) -> dict:
    by_skill = {row["skill"]: row for row in profile["skills"]}
    supported = [
        name
        for name in required
        if name in by_skill and by_skill[name]["evidence_level"] == "demonstrated"
    ]
    mentioned = [name for name in required if name in by_skill and name not in supported]
    missing = [name for name in required if name not in by_skill]
    preferred_gap = [
        name
        for name in preferred
        if name not in by_skill or by_skill[name]["evidence_level"] != "demonstrated"
    ]
    project_matches = []
    for project in profile["projects"]:
        matched = sorted(set(project["skills"]) & set(required + preferred))
        if matched:
            project_matches.append({**project, "job_requirements_connected": matched})
    study = list(dict.fromkeys(mentioned + missing + preferred_gap))
    return {
        "supported_required_skills": supported,
        "required_skills_with_mentions_only": mentioned,
        "required_skills_without_resume_evidence": missing,
        "preferred_skills_without_demonstrated_evidence": preferred_gap,
        "relevant_projects": project_matches,
        "potential_project_questions": [
            f"What design decision did you make in this project involving {skill}, and what evidence shows it worked?"
            for skill in sorted(
                {s for p in project_matches for s in p["job_requirements_connected"]}
            )
        ],
        "study_priorities": study,
        "practice_priority": "review_gaps_first" if study else "practice_scenarios_and_deep_dives",
        "evidence_caveat": "Keyword mentions are not proof of proficiency; demonstrated evidence requires an action-oriented resume line.",
    }


def fallback_evaluate(expected_points: list[str], rubric: str, answer: str) -> dict:
    words = set(re.findall(r"[a-z0-9+#.]+", answer.casefold()))
    assessments = []
    for point in expected_points[:8] or [rubric]:
        tokens = {word for word in re.findall(r"[a-z0-9+#.]+", point.casefold()) if len(word) > 3}
        overlap = tokens & words
        ratio = len(overlap) / max(1, len(tokens))
        outcome = (
            "demonstrated" if ratio >= 0.35 else "partial" if ratio >= 0.12 else "not_demonstrated"
        )
        assessments.append(
            {
                "criterion": point[:120],
                "assessment": outcome,
                "evidence": "Keyword overlap heuristic; verify against the full response."
                if overlap
                else "No matching key terms found by the local heuristic.",
            }
        )
    demonstrated = sum(row["assessment"] == "demonstrated" for row in assessments)
    partial = sum(row["assessment"] == "partial" for row in assessments)
    overall = (
        "strong"
        if demonstrated >= max(1, len(assessments) // 2)
        else "partial"
        if demonstrated + partial
        else "needs_review"
    )
    missing = [row["criterion"] for row in assessments if row["assessment"] != "demonstrated"]
    result = AnswerEvaluationOutput(
        criteria=[CriterionAssessment.model_validate(row) for row in assessments],
        strengths=["Your answer addressed at least one rubric point."] if demonstrated else [],
        missing_concepts=missing,
        suggested_improvements=[
            "Explain the underlying mechanism and connect it to a concrete example."
        ]
        if missing
        else [],
        outcome=overall,
    ).model_dump()
    return result | {"method": "deterministic_keyword_heuristic", "approximate": True}


def reorder_adaptive_queue(
    remaining: list[str], question_meta: dict[str, dict], skill: str | None, outcome: str
) -> list[str]:
    """Move a same-skill question matching a bounded difficulty adjustment forward."""
    if not skill or outcome not in {"strong", "partial", "needs_review"}:
        return remaining
    target = {"strong": "advanced", "partial": "intermediate", "needs_review": "beginner"}[outcome]
    ranked = sorted(
        enumerate(remaining),
        key=lambda item: (
            question_meta.get(item[1], {}).get("primary_skill") != skill,
            question_meta.get(item[1], {}).get("difficulty") != target,
            item[0],
        ),
    )
    return [question_id for _, question_id in ranked]


def is_duplicate_question(candidate: str, existing: list[str]) -> bool:
    normalized = normalize_text(candidate).casefold()
    return any(
        SequenceMatcher(None, normalized, normalize_text(text).casefold()).ratio() >= 0.90
        for text in existing
    )
