
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime,
    ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    idempotency_key: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="queued"
    )
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, server_default="0"
    )
    fencing_token: Mapped[int] = mapped_column(
        BigInteger, server_default="0"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="valid_status"
        ),
    )


class JobEffect(Base):
    __tablename__ = "job_effects"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"),
        unique=True, nullable=False
    )
    worker_id: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    fencing_token: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
