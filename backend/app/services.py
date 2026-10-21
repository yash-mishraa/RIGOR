import hashlib
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.taxonomy import COMPETENCIES, ROLE_FAMILIES, SKILL_TAXONOMY


def _phrase_pattern(value: str) -> re.Pattern:
    escaped = re.escape(value).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![\w]){escaped}(?![\w])", re.IGNORECASE)


def normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def description_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).casefold().encode("utf-8")).hexdigest()


def job_fingerprint(title: str, company: str | None, description: str) -> str:
    content = "\x1f".join(
        (normalize_text(title), normalize_text(company or ""), normalize_text(description))
    )
    return hashlib.sha256(content.casefold().encode("utf-8")).hexdigest()


def normalize_source_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.lower().removeprefix("www.")
    default_port = 80 if parsed.scheme.lower() == "http" else 443
    port = f":{parsed.port}" if parsed.port and parsed.port != default_port else ""
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    ignored = {"fbclid", "gclid", "ref", "source"}
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parsed.query)
            if not k.lower().startswith("utm_") and k.lower() not in ignored
        )
    )
    return urlunsplit((parsed.scheme.lower(), host + port, path, query, ""))


def _role_family(title: str) -> str:
    title = normalize_text(title)
    # More specific aliases win (e.g. "machine learning engineer" before "data engineer").
    candidates = sorted(
        ((alias, family) for family, aliases in ROLE_FAMILIES.items() for alias in aliases),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for alias, family in candidates:
        if _phrase_pattern(alias).search(title):
            return family
    return "general"


def _seniority(title: str) -> str | None:
    patterns = [
        (r"\b(intern|internship)\b", "intern"),
        (r"\b(junior|entry[ -]level|associate)\b", "junior"),
        (r"\b(staff|principal|distinguished)\b", "staff"),
        (r"\b(senior|sr\.?|lead)\b", "senior"),
        (r"\b(mid[ -]level|intermediate)\b", "mid"),
    ]
    lowered = title.lower()
    return next((level for pattern, level in patterns if re.search(pattern, lowered)), None)


def _labeled_value(description: str, label: str) -> str | None:
    match = re.search(rf"(?im)^\s*{re.escape(label)}\s*[:—-]\s*([^\n]+)", description)
    return normalize_text(match.group(1)).strip(" .;,")[:200] or None if match else None


def _employment_type(description: str) -> str | None:
    for pattern, normalized in [
        (r"\bfull[ -]time\b", "full-time"),
        (r"\bpart[ -]time\b", "part-time"),
        (r"\bcontract(?:or)?\b", "contract"),
        (r"\binternship\b", "internship"),
        (r"\btemporary\b", "temporary"),
    ]:
        if re.search(pattern, description, re.IGNORECASE):
            return normalized
    return None


def _list_section(description: str, heading_patterns: list[str]) -> list[str]:
    lines = [line.strip() for line in description.splitlines()]
    result: list[str] = []
    in_section = False
    for line in lines:
        clean = re.sub(r"^(?:[-*•▪]|\d+[.)])\s*", "", line).strip()
        if not clean:
            if in_section:
                in_section = False
            continue
        heading = re.sub(r"[:\s]+$", "", clean).lower()
        if any(re.fullmatch(pattern, heading) for pattern in heading_patterns):
            in_section = True
            continue
        if re.fullmatch(
            r"(responsibilities|what you(?:'|’)ll do|key duties|qualifications|what you(?:'|’)ll need|requirements|minimum requirements)",
            heading,
        ):
            in_section = False
            continue
        if re.fullmatch(r"[A-Z][A-Z /&-]{3,}", clean) and not clean[:1].islower():
            in_section = False
        elif in_section and len(clean) > 8:
            result.append(clean[:500])
    return result[:30]


def analyze_job(title: str, description: str) -> dict:
    """Extract only taxonomy-backed evidence and plainly labeled description sections."""
    required, preferred, mentioned = [], [], []
    lowered = description.lower()
    for skill in SKILL_TAXONOMY:
        matches = []
        for alias in sorted([skill["name"], *skill["aliases"]], key=len, reverse=True):
            matches.extend(_phrase_pattern(alias).finditer(description))
        if not matches:
            continue
        match = min(matches, key=lambda item: item.start())
        start = max(0, description.rfind("\n", 0, match.start()) + 1)
        end = description.find("\n", match.end())
        end = len(description) if end < 0 else end
        evidence = normalize_text(description[start:end])
        context = lowered[max(0, start - 120) : end]
        if re.search(r"\b(preferred|nice to have|bonus|desirable)\b", context):
            target = preferred
        elif re.search(
            r"\b(required|must[ -]have|minimum qualifications|basic qualifications)\b", context
        ):
            target = required
        else:
            target = mentioned
        target.append({"name": skill["name"], "category": skill["category"], "evidence": evidence})

    responsibilities = _list_section(
        description, [r"responsibilities", r"what you(?:'|’)ll do", r"key duties"]
    )
    qualifications = _list_section(
        description,
        [r"qualifications", r"what you(?:'|’)ll need", r"requirements", r"minimum requirements"],
    )
    competencies = sorted(
        name
        for name, aliases in COMPETENCIES.items()
        if any(_phrase_pattern(alias).search(description) for alias in aliases)
    )
    tools = sorted(
        {
            item["name"]
            for item in required + preferred + mentioned
            if item["category"]
            in {"tools", "cloud", "platform", "database", "programming", "machine_learning"}
        }
    )
    location = _labeled_value(description, "location")
    if location is None and re.search(r"(?im)^\s*remote\s*$", description):
        location = "Remote"
    return {
        "role_family": _role_family(title),
        "seniority": _seniority(title),
        "required_skills": required,
        "preferred_skills": preferred,
        "mentioned_skills": mentioned,
        "responsibilities": responsibilities,
        "qualifications": qualifications,
        "competencies": competencies,
        "tools_technologies": tools,
        "location": location,
        "employment_type": _employment_type(description),
        "analysis_version": 2,
        "method": "deterministic_taxonomy",
    }


def detect_job_duplicate(
    existing_jobs: list[dict],
    *,
    title: str,
    company: str | None,
    description: str,
    normalized_url: str | None,
) -> tuple[dict | None, str | None]:
    """Conservative duplicate check: URL identity or exact title/company plus near-identical text."""
    incoming_title = normalize_text(title).casefold()
    incoming_company = normalize_text(company or "").casefold()
    incoming_description = normalize_text(description).casefold()
    for job in existing_jobs:
        if normalized_url and job.get("normalized_source_url") == normalized_url:
            return job, "source_url"
        same_title = normalize_text(job["role_title"]).casefold() == incoming_title
        same_company = normalize_text(job.get("company_name") or "").casefold() == incoming_company
        similarity = SequenceMatcher(
            None, normalize_text(job["description"]).casefold(), incoming_description
        ).ratio()
        if same_title and same_company and similarity >= 0.92:
            return job, "title_company_description"
    return None, None


class RankingWeights:
    required_skill = 50.0
    preferred_skill = 18.0
    role_family = 22.0
    competency = 10.0
    difficulty = 5.0


def rank_question(
    question: dict,
    *,
    role_family: str,
    required: set[str],
    preferred: set[str],
    competencies: set[str],
    seniority: str | None = None,
    weights: RankingWeights = RankingWeights(),
) -> dict:
    skills = set(question.get("skills", []))
    qroles = set(question.get("role_families", [])) | {question.get("role_family", "")}
    matched_required = sorted(skills & required)
    matched_preferred = sorted(skills & preferred)
    score = 0.0
    reasons = []
    if required:
        score += weights.required_skill * len(matched_required) / len(required)
    if preferred:
        score += weights.preferred_skill * len(matched_preferred) / len(preferred)
    for skill in matched_required:
        reasons.append(f"Matches required skill: {skill}.")
    for skill in matched_preferred:
        reasons.append(f"Matches preferred skill: {skill}.")
    if role_family in qroles:
        score += weights.role_family
        reasons.append(f"Relevant to the {role_family.replace('_', ' ')} role family.")
    competency_tags = set(question.get("competencies", []))
    matched_competencies = sorted(competencies & competency_tags)
    if matched_competencies:
        score += weights.competency * min(
            1.0, len(matched_competencies) / max(1, len(competencies))
        )
        reasons.extend(
            f"Matches competency: {item.replace('_', ' ')}." for item in matched_competencies
        )
    target_difficulty = {
        "intern": "beginner",
        "junior": "beginner",
        "mid": "intermediate",
        "senior": "advanced",
        "staff": "advanced",
    }.get(seniority or "")
    if target_difficulty and question.get("difficulty") == target_difficulty:
        score += weights.difficulty
        reasons.append(f"Difficulty is calibrated for {seniority} level.")
    question["relevance_score"] = round(score, 2)
    question["match_reasons"] = reasons
    return question


def select_balanced_questions(
    candidates: list[dict], limit: int, required_skills: set[str]
) -> list[dict]:
    """Greedy ranked selection with small coverage/diversity bonuses and stable tie breaking."""
    remaining = [dict(item) for item in candidates if item.get("relevance_score", 0) > 0]
    selected: list[dict] = []
    covered: set[str] = set()
    categories: dict[str, int] = {}
    while remaining and len(selected) < limit:

        def adjusted(item):
            uncovered_bonus = 18 if selected else 0
            skill_bonus = (
                len((set(item.get("skills", [])) & required_skills) - covered) * uncovered_bonus
            )
            category = item.get("category", "uncategorized")
            diversity_bonus = 3 if categories.get(category, 0) == 0 else 0
            return (
                -(item["relevance_score"] + skill_bonus + diversity_bonus),
                -item["relevance_score"],
                item.get("stable_key", ""),
                str(item.get("id", "")),
            )

        remaining.sort(key=adjusted)
        chosen = remaining.pop(0)
        selected.append(chosen)
        covered.update(set(chosen.get("skills", [])) & required_skills)
        category = chosen.get("category", "uncategorized")
        categories[category] = categories.get(category, 0) + 1
    for index, item in enumerate(selected, start=1):
        item["position"] = index
    return selected


def build_content_coverage(
    required: set[str],
    preferred: set[str],
    questions: list[dict],
    modules: list[dict],
    role_family: str | None = None,
) -> dict:
    qskills = {skill for question in questions for skill in question.get("skills", [])}
    mskills = {skill for module in modules for skill in module.get("skills", [])}
    all_skills = required | preferred
    categories: dict[str, int] = {}
    difficulties: dict[str, int] = {}
    for item in questions:
        categories[item.get("category", "uncategorized")] = (
            categories.get(item.get("category", "uncategorized"), 0) + 1
        )
        difficulties[item.get("difficulty", "unknown")] = (
            difficulties.get(item.get("difficulty", "unknown"), 0) + 1
        )
    expected_categories = {
        "backend": {
            "api_design",
            "database_scenario",
            "backend_scenario",
            "debugging",
            "testing_strategy",
        },
        "frontend": {"frontend_debugging", "accessibility", "frontend_design", "testing_strategy"},
        "data_analyst": {
            "analytics_case",
            "experimentation",
            "sql_data",
            "analytics_communication",
        },
        "data_engineer": {
            "data_pipeline_scenario",
            "sql_data",
            "data_quality",
            "distributed_scenario",
        },
        "ml_engineer": {"ml_evaluation", "ml_operations", "ml_architecture"},
        "platform": {"platform_scenario", "platform_debugging", "reliability", "supply_chain"},
        "qa_automation": {"testing_strategy", "testing_debugging", "api_testing"},
        "security": {"security_scenario", "security_design", "incident_response"},
        "systems": {"systems_debugging", "network_debugging", "performance"},
        "distributed": {"distributed_scenario", "reliability"},
    }
    if role_family in expected_categories:
        expected_categories[role_family] |= {
            "behavioral_incident",
            "behavioral_collaboration",
            "behavioral_learning",
        }
    missing_categories = sorted(expected_categories.get(role_family or "", set()) - set(categories))
    return {
        "required_skills_with_questions": sorted(required & qskills),
        "required_skills_without_questions": sorted(required - qskills),
        "required_skills_with_learning": sorted(required & mskills),
        "required_skills_without_learning": sorted(required - mskills),
        "preferred_skills_without_questions": sorted(preferred - qskills),
        "question_count": len(questions),
        "question_distribution_by_category": categories,
        "question_distribution_by_difficulty": difficulties,
        "missing_content_categories": missing_categories,
        "content_coverage_percent": round(
            100 * len(all_skills & (qskills | mskills)) / len(all_skills)
        )
        if all_skills
        else 100,
        "note": "Coverage describes available tagged content; it is not a prediction of interview success.",
    }
