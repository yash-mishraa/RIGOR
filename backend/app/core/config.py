from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://rigor:rigor@localhost:5432/rigor"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    max_job_description_chars: int = 30000
    ai_provider: str = "none"
    ai_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    ai_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    ai_max_generation_batch: int = Field(default=5, ge=1, le=5)
    ai_max_output_tokens: int = Field(default=3000, ge=128, le=8000)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
