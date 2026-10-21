import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str | None] = ContextVar("rigor_request_id", default=None)


class PrivacyJsonFormatter(logging.Formatter):
    """Emit only an allowlist of structured, non-content operational fields."""

    safe_fields = (
        "request_id",
        "endpoint",
        "method",
        "status_code",
        "duration_ms",
        "ai_provider",
        "ai_model",
        "ai_schema",
        "ai_duration_ms",
        "ai_input_tokens",
        "ai_output_tokens",
        "ai_estimated_cost_usd",
        "ai_cost_estimate_basis",
        "ai_success",
        "ai_error_type",
        "error_type",
        "generation_accepted",
        "generation_rejected",
        "evaluation_method",
        "evaluation_outcome",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for field in self.safe_fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_privacy_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    for handler in root.handlers:
        handler.setFormatter(PrivacyJsonFormatter())
