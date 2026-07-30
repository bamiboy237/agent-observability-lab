"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import PostgresDsn, SecretStr, field_serializer, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings shared by the application."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    database_url: PostgresDsn
    database_url_unpooled: PostgresDsn | None = None
    environment: Literal["local", "test", "production"] = "local"
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "agent-reliability-lab"

    @field_validator("database_url", "database_url_unpooled", mode="before")
    @classmethod
    def use_asyncpg_driver(cls, database_url: object) -> object:
        if not isinstance(database_url, str):
            return database_url

        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        parsed_url = urlsplit(database_url)
        query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        ssl_mode = query.pop("sslmode", None)
        query.pop("channel_binding", None)
        if ssl_mode is not None:
            query["ssl"] = ssl_mode

        return urlunsplit(parsed_url._replace(query=urlencode(query)))

    @field_serializer("database_url", "database_url_unpooled")
    def serialize_database_url(self, database_url: PostgresDsn | None) -> str | None:
        """Keep database credentials out of serialized settings and logs."""
        if database_url is None:
            return None
        return f"{database_url.scheme}://[REDACTED]"

    @property
    def migration_database_url(self) -> PostgresDsn:
        """Return the direct database URL required by schema migrations."""
        return self.database_url_unpooled or self.database_url

    def __str__(self) -> str:
        return str(self.model_dump(mode="json"))

    def __repr__(self) -> str:
        return f"Settings({self.model_dump(mode='json')!r})"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
