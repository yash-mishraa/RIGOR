from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://rigor:rigor@localhost:5432/rigor"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    max_job_description_chars: int = 30000
    max_request_bytes: int = Field(default=200_000, ge=1024, le=2_000_000)
    ai_provider: str = "none"
    ai_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    ai_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    ai_max_generation_batch: int = Field(default=5, ge=1, le=5)
    ai_max_output_tokens: int = Field(default=3000, ge=128, le=8000)
    ai_requests_per_minute: int = Field(default=10, ge=1, le=120)
    ai_input_cost_per_million_usd: float | None = Field(default=None, ge=0)
    ai_output_cost_per_million_usd: float | None = Field(default=None, ge=0)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def empty_api_key_is_unset(cls, value):
        return None if value == "" else value

    @field_validator(
        "ai_input_cost_per_million_usd",
        "ai_output_cost_per_million_usd",
        mode="before",
    )
    @classmethod
    def empty_cost_rate_means_unset(cls, value):
        return None if value == "" else value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def ai_configuration_status(self) -> str:
        if self.ai_provider == "none":
            return "disabled"
        if self.ai_provider != "openai":
            return "misconfigured"
        if not self.openai_api_key or not self.openai_api_key.strip() or not self.ai_model.strip():
            return "misconfigured"
        return "configured"


settings = Settings()
