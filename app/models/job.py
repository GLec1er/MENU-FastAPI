import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base
from app.jobs.states import STATUSES


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind = Column(String(32), nullable=False)
    snapshot = Column(JSONB, nullable=False)
    status = Column(String(16), nullable=False)
    attempts = Column(Integer, nullable=False, server_default="0")
    max_attempts = Column(Integer, nullable=False)
    next_run_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    owner_token = Column(UUID(as_uuid=True))
    lease_expires_at = Column(DateTime(timezone=True))
    error_code = Column(String(64))
    error_message = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN (%s)" % ", ".join(f"'{s}'" for s in STATUSES),
            name="ck_jobs_status",
        ),
        Index("ix_jobs_status_created", "status", "created_at"),
    )


class Outbox(Base):
    __tablename__ = "outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(16), nullable=False)
    attempt = Column(Integer, nullable=False)
    publish_seq = Column(Integer, nullable=False, server_default="0")
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at = Column(DateTime(timezone=True))
    publish_failures = Column(Integer, nullable=False, server_default="0")
    last_error = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("job_id", "kind", "attempt", "publish_seq", name="uq_outbox_event"),
        Index(
            "ix_outbox_pending",
            "available_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )


class JobResult(Base):
    __tablename__ = "job_results"

    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    content_type = Column(String(128), nullable=False)
    content = Column(LargeBinary, nullable=False)
    sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
