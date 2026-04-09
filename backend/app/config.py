from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LLM
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-flash-1.5"

    # Embeddings
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    local_embedding_fallback: bool = True

    # Database
    database_url: str = "postgresql://cortex:cortex_pass@postgres:5432/incident_cortex"

    # ChromaDB
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    chroma_collection: str = "ecommerce_codebase"

    # Repo
    ecommerce_repo_url: str = "https://github.com/reactioncommerce/reaction.git"
    ecommerce_repo_branch: str = "trunk"

    # Dedup
    dedup_suggestion_threshold: float = 0.85
    dedup_duplicate_threshold: float = 0.95

    # Mocks
    jira_mock_url: str = "http://jira-mock:8080"
    slack_mock_url: str = "http://slack-mock:8090"
    mailhog_smtp_host: str = "mailhog"
    mailhog_smtp_port: int = 1025
    notification_from_email: str = "cortex@incident-cortex.local"
    team_email: str = "sre-team@company.com"
    slack_channel: str = "#incidents"

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://langfuse:3000"

    # App
    log_level: str = "INFO"
    max_file_size_mb: int = 10
    rate_limit_per_minute: int = 10

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
