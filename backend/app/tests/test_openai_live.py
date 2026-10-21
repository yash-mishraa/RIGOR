"""Single-call live provider smoke test; skipped unless explicitly enabled."""

import os

import pytest

from app.ai import AIConfigurationError, get_ai_provider
from app.core.config import settings
from app.taxonomy import SKILL_TAXONOMY


@pytest.mark.asyncio
async def test_configured_openai_structured_job_analysis():
    if os.getenv("RIGOR_RUN_OPENAI_INTEGRATION") != "1":
        pytest.skip("Set RIGOR_RUN_OPENAI_INTEGRATION=1 to opt in to one paid provider request")
    if settings.ai_configuration_status != "configured":
        pytest.fail(
            "OpenAI integration was explicitly enabled, but backend configuration is incomplete"
        )
    try:
        provider = get_ai_provider()
    except AIConfigurationError as exc:
        pytest.fail(str(exc))

    synthetic_job = (
        "Backend Engineer. Required skills: Python and PostgreSQL. "
        "Build tested APIs and maintain reliable services."
    )
    output = await provider.analyze_job(synthetic_job, [item["name"] for item in SKILL_TAXONOMY])
    output = type(output).model_validate(output.model_dump())
    assert any(item.name == "Python" for item in output.required_skills)
    assert all(
        item.evidence.casefold() in synthetic_job.casefold()
        for item in output.required_skills + output.preferred_skills
    )
    # Provider/model/token metadata is emitted by the privacy-safe adapter log.
    print(
        f"OpenAI structured smoke test succeeded: provider={provider.provider_name}, model={provider.model_name}"
    )
