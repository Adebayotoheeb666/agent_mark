"""Central configuration — env-driven, per N1 Environment foundation."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App runtime URL: least-privilege mark_api login (verification finding
    # 2026-09-28). Migrations keep running as the mark_app owner via
    # alembic.ini / OWNER_DATABASE_URL — never point migrations at this URL.
    database_url: str = "postgresql+psycopg2://mark_api:mark_api_password@localhost:5432/agent_mark"
    # DSN without driver prefix, for psycopg2 direct connections
    database_dsn: str = "postgresql://mark_api:mark_api_password@localhost:5432/agent_mark"

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    allow_public_bind: bool = False

    app_name: str = "Agent Mark Node — Local API"
    app_version: str = "0.1.0-n1"


settings = Settings()
