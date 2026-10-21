from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://rigor:rigor@localhost:5432/rigor"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    max_job_description_chars: int = 30000
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
