from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://user:pass@localhost:5432/access_requests"
    anomaly_threshold: float = 0.5
    llm_provider: str = "default"
    llm_api_key: SecretStr = SecretStr("")

    # Cold-start anomaly behavior
    cold_start_min_history: int = 2
    cold_start_anomaly_score: float = 0.8


settings = Settings()
