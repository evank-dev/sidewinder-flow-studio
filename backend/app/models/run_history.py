from sqlalchemy import String, Text, DateTime, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime, UTC
from app.core.database import Base


class RunHistory(Base):
    """Audit trail of every flow execution — manual and scheduled."""
    __tablename__ = "run_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    flow_id: Mapped[str] = mapped_column(String(36), index=True)
    flow_name: Mapped[str | None] = mapped_column(String(255))
    trigger: Mapped[str] = mapped_column(String(16))          # manual | schedule
    status: Mapped[str] = mapped_column(String(16))           # running | ok | error | stopped
    attempt: Mapped[int] = mapped_column(Integer, default=1)  # 1..max_retries+1
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    nodes_ok: Mapped[int | None] = mapped_column(Integer)
    nodes_error: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
