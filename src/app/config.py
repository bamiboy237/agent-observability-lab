"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, SecretStr, field_serializer
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings shared by the application."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    database_url: PostgresDsn
    environment: Literal["local", "test", "production"] = "local"
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "agent-reliability-lab"

    @field_serializer("database_url")
    def serialize_database_url(self, database_url: PostgresDsn) -> str:
        """Keep database credentials out of serialized settings and logs."""
        return f"{database_url.scheme}://[REDACTED]"

    def __str__(self) -> str:
        return str(self.model_dump(mode="json"))

    def __repr__(self) -> str:
        return f"Settings({self.model_dump(mode='json')!r})"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
