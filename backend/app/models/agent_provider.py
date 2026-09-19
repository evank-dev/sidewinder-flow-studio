from sqlalchemy import String, Text, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime, UTC
from app.core.database import Base


class AgentProvider(Base):
    __tablename__ = "agent_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # "anthropic" | "ollama" | "openai_compatible"
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # Model identifier, e.g. "claude-sonnet-4-6" or "qwen2.5-coder:7b"
    model: Mapped[str] = mapped_column(String(255), nullable=False)

    # Base URL — required for ollama / openai_compatible, optional for anthropic
    base_url: Mapped[str | None] = mapped_column(String(512))

    # API key, Fernet-encrypted at rest. Null for local providers that need none.
    api_key_enc: Mapped[str | None] = mapped_column(Text)

    # Only one provider is active (used by the agent) at a time
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
