from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True
    database_url: str = "postgresql+psycopg://fleet:fleet@localhost:5432/fleet"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 60
    upload_dir: str = "uploads"
    # frontend/'s dev server origin -- without this, every browser request
    # from the Next.js app is blocked before it reaches any route below,
    # surfacing as a generic "could not reach the server" network error.
    cors_origins: list[str] = ["http://localhost:3000"]

    # Agent-memory vector search (Pinecone_Migration_Hardened.md). Unset key =
    # memory runs Postgres-only (scope + keyword recall, no similarity).
    pinecone_api_key: str | None = None
    pinecone_index: str = "fleet-memory"
    pinecone_namespace: str = "agent-memory"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
