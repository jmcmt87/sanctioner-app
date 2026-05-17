from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SSA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sanctions_db"

    llm_base_url: str = "https://api.mistral.ai/v1"
    llm_model_name: str = "mistral-large-latest"
    llm_api_key: str = ""

    s3_bucket: str = "sanctions-data"
    s3_region: str = "eu-central-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    langsmith_api_key: str = ""
    langsmith_project: str = "sanctions-screening-assistant"

    log_level: str = "INFO"
    cors_origins: list[str] = Field(default=["http://localhost:3000"])


settings = Settings()
