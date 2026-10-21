from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

from app.ai import AnswerEvaluationOutput, get_ai_provider
from app.core.config import settings
from app.personalization import extract_resume_evidence, fallback_evaluate, match_resume_to_job
from app.services import analyze_job
from app.taxonomy import SKILL_TAXONOMY

DATASET = Path(__file__).resolve().parents[2] / "evaluations" / "dataset_v1.json"
PROMPT_VERSION = "rigor-ai-prompts-v1"


def _ratio(expected: set[str], actual: set[str]) -> float:
    return round(len(expected & actual) / len(expected), 4) if expected else 1.0


def _concept_match_rate(expected: list[str], predicted: list[str]) -> tuple[float, float]:
    def tokens(value: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9+#]+", value.casefold()) if len(word) > 3}

    expected_tokens = [tokens(item) for item in expected]
    predicted_tokens = [tokens(item) for item in predicted]
    hits = sum(
        any(bool(label) and label.issubset(prediction) for prediction in predicted_tokens)
        for label in expected_tokens
    )
    predicted_hits = sum(
        any(bool(label) and label.issubset(prediction) for label in expected_tokens)
        for prediction in predicted_tokens
    )
    recall = hits / len(expected_tokens) if expected_tokens else 1.0
    precision = (
        predicted_hits / len(predicted_tokens)
        if predicted_tokens
        else (1.0 if not expected else 0.0)
    )
    return round(precision, 4), round(recall, 4)


def _deterministic(case: dict, question_texts: list[str]) -> dict:
    profile = analyze_job(case["role"], case["description"])
    extracted_required = {row["name"] for row in profile["required_skills"]}
    extracted_preferred = {row["name"] for row in profile["preferred_skills"]}
    all_taxonomy = {row["name"] for row in SKILL_TAXONOMY}
    extracted = profile["required_skills"] + profile["preferred_skills"]
    evidence_aligned = sum(
        bool(row["evidence"]) and row["evidence"].casefold() in case["description"].casefold()
        for row in extracted
    )
    resume = extract_resume_evidence(case["profile"])
    matched = match_resume_to_job(resume, case["required_skills"], case["preferred_skills"])
    actual_matched = set(matched["supported_required_skills"])
    actual_gaps = set(matched["required_skills_without_resume_evidence"])
    project_skills = {
        skill
        for project in matched["relevant_projects"]
        for skill in project["job_requirements_connected"]
    }
    question = case["question"]
    target = case["target_skill"]
    expected_points = case["expected_points"]
    answer_eval = AnswerEvaluationOutput.model_validate(
        fallback_evaluate(expected_points, case["rubric"], case["answer"])
    )
    complete_question = (
        len(expected_points) >= 2
        and len(case["reference_answer"].split()) >= 15
        and len(case["rubric"].split()) >= 7
    )
    exact_dupes = 0
    near_dupes = 0
    normalized = [re.sub(r"\W+", " ", text.casefold()).strip() for text in question_texts]
    pairs = max(1, len(normalized) * (len(normalized) - 1) // 2)
    for index, left in enumerate(normalized):
        for right in normalized[index + 1 :]:
            similarity = SequenceMatcher(None, left, right).ratio()
            exact_dupes += left == right
            near_dupes += left != right and similarity >= 0.9
    expected_missing = case["expected_missing_concepts"]
    missing_precision, missing_recall = _concept_match_rate(
        expected_missing, answer_eval.missing_concepts
    )
    company_claims = bool(
        re.search(
            r"\b(?:at|our|the)\s+(?:company|team)\b|\b[A-Z][a-z]+\s+(?:Inc\.?|Corp\.?|Ltd\.?)",
            question,
        )
    )
    return {
        "required_skill_recall": _ratio(set(case["required_skills"]), extracted_required),
        "required_skill_precision": _ratio(extracted_required, set(case["required_skills"])),
        "preferred_skill_recall": _ratio(set(case["preferred_skills"]), extracted_preferred),
        "preferred_skill_precision": _ratio(extracted_preferred, set(case["preferred_skills"])),
        "evidence_alignment": round(evidence_aligned / max(1, len(extracted)), 4),
        "unsupported_requirement_rate": round(
            len({row["name"] for row in extracted} - all_taxonomy) / max(1, len(extracted)), 4
        ),
        "resume_matched_skill_recall": _ratio(set(case["matched_skills"]), actual_matched),
        "resume_unsupported_skill_claims": len(
            {row["skill"] for row in resume["skills"]} - all_taxonomy
        ),
        "relevant_project_skill_recall": _ratio(set(case["project_skills"]), project_skills),
        "skill_gap_recall": _ratio(set(case["gap_skills"]), actual_gaps),
        "question_target_skill_relevance": int(case["question_relevant"]),
        "question_required_skill_coverage": round(
            len({target} & set(case["required_skills"])) / max(1, len(case["required_skills"])), 4
        ),
        "question_exact_duplicate_rate": round(exact_dupes / pairs, 4),
        "question_near_duplicate_rate": round(near_dupes / pairs, 4),
        "question_answer_and_rubric_completeness": int(complete_question),
        "unsupported_company_specific_claims": int(company_claims),
        "answer_schema_valid": 1,
        "answer_rubric_coverage": round(
            len(answer_eval.criteria) / max(1, len(expected_points)), 4
        ),
        "answer_evidence_grounding_rate": round(
            sum(
                criterion.evidence.casefold() in case["answer"].casefold()
                for criterion in answer_eval.criteria
                if criterion.evidence
            )
            / max(1, sum(bool(criterion.evidence) for criterion in answer_eval.criteria)),
            4,
        ),
        "answer_missing_concept_precision": missing_precision,
        "answer_missing_concept_recall": round(missing_recall, 4),
    }


async def _openai(case: dict) -> dict:
    provider = get_ai_provider()
    taxonomy = [row["name"] for row in SKILL_TAXONOMY]
    job = await provider.analyze_job(case["description"], taxonomy)
    generation = await provider.generate_questions(
        f"Role: {case['role']}; role family: {case['role_family']}; job: {case['description']}",
        [case["target_skill"]],
        1,
    )
    evaluation = await provider.evaluate_answer(case["question"], case["rubric"], case["answer"])
    skill_aliases = {
        alias.casefold(): row["name"]
        for row in SKILL_TAXONOMY
        for alias in [row["name"], *row["aliases"]]
    }
    required = {row.name for row in job.required_skills}
    preferred = {row.name for row in job.preferred_skills}
    relevant_generation = [
        item
        for item in generation.questions
        if skill_aliases.get(item.primary_skill.casefold()) == case["target_skill"]
        and item.primary_skill.casefold() in item.question_text.casefold()
    ]
    evidence_rows = job.required_skills + job.preferred_skills
    grounded = [row.evidence.casefold() in case["description"].casefold() for row in evidence_rows]
    answer_evidence = [
        item.evidence.casefold() in case["answer"].casefold()
        for item in evaluation.criteria
        if item.evidence
    ]
    missing_precision, missing_recall = _concept_match_rate(
        case["expected_missing_concepts"], evaluation.missing_concepts
    )
    result = _deterministic(case, [case["question"]])
    result.update(
        {
            "required_skill_recall": _ratio(set(case["required_skills"]), required),
            "required_skill_precision": _ratio(required, set(case["required_skills"])),
            "preferred_skill_recall": _ratio(set(case["preferred_skills"]), preferred),
            "preferred_skill_precision": _ratio(preferred, set(case["preferred_skills"])),
            "evidence_alignment": round(sum(grounded) / max(1, len(grounded)), 4),
            "unsupported_requirement_rate": round(
                len({row.name for row in evidence_rows} - set(skill_aliases.values()))
                / max(1, len(evidence_rows)),
                4,
            ),
            "question_target_skill_relevance": int(bool(relevant_generation)),
            "question_required_skill_coverage": round(
                len(
                    {skill_aliases[item.primary_skill.casefold()] for item in relevant_generation}
                    & set(case["required_skills"])
                )
                / max(1, len(case["required_skills"])),
                4,
            ),
            "question_exact_duplicate_rate": 0.0,
            "question_near_duplicate_rate": 0.0,
            "question_answer_and_rubric_completeness": int(
                bool(relevant_generation)
                and all(
                    item.expected_points and item.reference_answer and item.rubric
                    for item in relevant_generation
                )
            ),
            "unsupported_company_specific_claims": int(
                any(
                    re.search(
                        r"\b(?:at|our)\s+(?:company|team)\b",
                        item.question_text,
                        re.IGNORECASE,
                    )
                    for item in generation.questions
                )
            ),
            "answer_schema_valid": 1,
            "answer_rubric_coverage": round(
                len(evaluation.criteria) / max(1, len(case["expected_points"])), 4
            ),
            "answer_evidence_grounding_rate": round(
                sum(answer_evidence) / max(1, len(answer_evidence)), 4
            ),
            "answer_missing_concept_precision": missing_precision,
            "answer_missing_concept_recall": missing_recall,
        }
    )
    result["_generated_question_texts"] = [item.question_text for item in generation.questions]
    return result


def _aggregate(rows: list[dict]) -> dict:
    keys = rows[0].keys()
    result = {}
    for key in keys:
        values = [row[key] for row in rows]
        numeric = [value for value in values if isinstance(value, (float, int))]
        result[key] = round(sum(numeric) / len(numeric), 4) if numeric else values[0]
    return result


async def run(mode: str) -> dict:
    dataset = json.loads(DATASET.read_text())
    questions = [case["question"] for case in dataset["cases"]]
    if mode == "openai":
        if os.getenv("RIGOR_RUN_AI_EVALUATIONS") != "1":
            raise SystemExit(
                "Set RIGOR_RUN_AI_EVALUATIONS=1 to authorize model-dependent evaluation calls."
            )
        if settings.ai_configuration_status != "configured":
            raise SystemExit("OpenAI is not configured; no provider calls were made.")
        rows = [await _openai(case) for case in dataset["cases"]]
        generated_texts = [
            text for row in rows for text in row.pop("_generated_question_texts", [])
        ]
        exact = near = 0
        pairs = max(1, len(generated_texts) * (len(generated_texts) - 1) // 2)
        for index, left_value in enumerate(generated_texts):
            left = re.sub(r"\W+", " ", left_value.casefold()).strip()
            for right_value in generated_texts[index + 1 :]:
                right = re.sub(r"\W+", " ", right_value.casefold()).strip()
                similarity = SequenceMatcher(None, left, right).ratio()
                exact += left == right
                near += left != right and similarity >= 0.9
        for row in rows:
            row["question_exact_duplicate_rate"] = round(exact / pairs, 4)
            row["question_near_duplicate_rate"] = round(near / pairs, 4)
    else:
        rows = [_deterministic(case, questions) for case in dataset["cases"]]
    return {
        "dataset_version": dataset["dataset_version"],
        "prompt_template_version": PROMPT_VERSION,
        "mode": mode,
        "model": settings.ai_model if mode == "openai" else None,
        "provider": settings.ai_provider if mode == "openai" else "deterministic-local",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "reproduction_config": {
            "ai_timeout_seconds": settings.ai_timeout_seconds if mode == "openai" else None,
            "ai_max_output_tokens": settings.ai_max_output_tokens if mode == "openai" else None,
            "live_requests_per_case": 3 if mode == "openai" else 0,
        },
        "case_count": len(rows),
        "metrics": _aggregate(rows),
        "per_case_metrics": rows,
        "limitations": [
            "Synthetic fixture results do not establish production quality.",
            "Model answer missing-concept labels require human review.",
            "Near-duplicate rates use a simple text similarity threshold.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("deterministic", "openai"), default="deterministic")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run(args.mode))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
