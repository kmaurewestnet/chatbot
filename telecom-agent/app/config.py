from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # Ollama
    ollama_base_url: str = "http://host.docker.internal:11434"
    llm_model: str = "qwen2.5:14b"
    embed_model: str = "nomic-embed-text"

    # Qdrant
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "telecom_knowledge"

    # Redis
    redis_url: str = "redis://redis:6379"
    redis_ttl_seconds: int = 86400

    # CRM interno
    crm_base_url: str = "https://tu-crm-interno.local/api/v1"
    crm_api_key: str = "change_me"

    # API de red interna
    net_diagnostics_url: str = "https://tu-api-red.local/api"
    net_diagnostics_key: str = "change_me"

    # Langfuse
    langfuse_host: str = "http://langfuse:3000"
    langfuse_public_key: str = "change_me"
    langfuse_secret_key: str = "change_me"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
