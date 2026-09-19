from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    METADATA_DB_URL: str = "sqlite+aiosqlite:///./flow_studio.db"
    PROJECTS_DIR: str = "./projects"

    # Fernet key for credential encryption
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    SECRET_KEY: str = "CHANGE_ME_32_bytes_base64_encoded_"

    # Arrow IPC frame cache dir (node output frames stored here between runs)
    FRAME_CACHE_DIR: str = "./frame_cache"

    # Reports (Explore/Report nodes) — DuckDB file shared with the Streamlit viewer
    REPORTS_DIR: str = "./reports_data"
    # Persisted processor outputs (right-click → Persist)
    PERSIST_DB: str = "./reports_data/persist.duckdb"

    # Base URL of the optional Streamlit report viewer (for "Open report" links)
    REPORTS_URL: str = "http://localhost:8501"

    # Failure alerting (enterprise scheduler) — leave blank to disable a channel
    SLACK_WEBHOOK_URL: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "sfs@localhost"

    # Optional — enables the AI agent for generating processor/chart code
    ANTHROPIC_API_KEY: str = ""

    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
