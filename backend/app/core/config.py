from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://rigor:rigor@localhost:5432/rigor"
    database_pool_size: int = Field(default=5, ge=1, le=30)
    database_pool_max_overflow: int = Field(default=2, ge=0, le=30)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=120)
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
    question_review_token: str | None = None
    app_environment: str = "development"
    demo_session_secret: str = "local-only-change-before-deploy-rigor-demo-secret"
    demo_cookie_secure: bool = False
    demo_cookie_samesite: str = "lax"
    demo_cookie_name: str = "rigor_demo"
    demo_session_days: int = Field(default=30, ge=1, le=90)
    demo_imports_per_minute: int = Field(default=3, ge=1, le=30)
    demo_plans_per_minute: int = Field(default=8, ge=1, le=60)
    demo_sessions_per_minute: int = Field(default=4, ge=1, le=30)
    demo_responses_per_minute: int = Field(default=20, ge=1, le=120)
    demo_max_imported_jobs: int = Field(default=10, ge=1, le=100)
    demo_max_plans: int = Field(default=20, ge=1, le=100)
    demo_max_practice_sessions: int = Field(default=20, ge=1, le=100)
    demo_max_answers: int = Field(default=100, ge=1, le=1000)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def empty_api_key_is_unset(cls, value):
        return None if value == "" else value

    @field_validator("question_review_token", mode="before")
    @classmethod
    def empty_review_token_is_unset(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def production_cookie_safety(self):
        if self.app_environment == "production":
            if not self.demo_cookie_secure:
                raise ValueError("DEMO_COOKIE_SECURE must be true in production")
            if self.demo_cookie_samesite.lower() != "none":
                raise ValueError("DEMO_COOKIE_SAMESITE must be none for cross-origin production APIs")
            if not self.demo_cookie_name.startswith("__Host-"):
                raise ValueError("DEMO_COOKIE_NAME must use the __Host- prefix in production")
            if len(self.demo_session_secret) < 32 or self.demo_session_secret.startswith("local-only"):
                raise ValueError("Set a unique DEMO_SESSION_SECRET of at least 32 characters")
        return self

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
