from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    offline_edit_seconds: int = 86400
    offline_grant_audience: str = "synchrohq-offline-drafts"
    attachment_max_bytes: int = 10485760
    s3_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "synchrohq"
    s3_access_key: str = "synchrohq_dev"
    s3_secret_key: str = "synchrohq_dev_secret"

    form_schema_max_bytes: int = 262144
    form_schema_max_depth: int = 12
    form_schema_max_fields: int = 200
    form_array_max_items: int = 100
    form_answers_max_bytes: int = 1048576

    app_name: str = "SynchroHQ"
    app_env: str = "development"
    demo_login_enabled: bool = False
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "synchrohq"
    postgres_user: str = "synchrohq"
    postgres_password: str = ""
    database_url: str | None = None
    auth_jwt_secret: str = "development-only-change-me-32-chars"
    auth_issuer: str = "synchrohq-community"
    auth_audience: str = "synchrohq-api"

    @property
    def effective_database_url(self) -> str:
        return self.database_url or (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
