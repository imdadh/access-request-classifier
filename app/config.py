from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    Attributes:
        database_url: PostgreSQL connection string.
        anomaly_threshold: Float in [0.0, 1.0]; requests below this threshold
            are auto-approved (given a confident role mapping).
        llm_api_key: API key for the hosted LLM provider.
        llm_provider: Optional name of the LLM provider adapter to use
            (defaults to the built-in default).
    """

    database_url: str = Field(validation_alias="DATABASE_URL")
    anomaly_threshold: float = Field(
        default=0.5, validation_alias="ANOMALY_THRESHOLD", ge=0.0, le=1.0
    )
    llm_api_key: SecretStr = Field(validation_alias="LLM_API_KEY")
    llm_provider: str = Field(default="default", validation_alias="LLM_PROVIDER")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


# Singleton instance for easy import
settings = Settings()
