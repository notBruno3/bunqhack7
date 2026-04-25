from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    amount_eur: Mapped[float] = mapped_column(Float)
    merchant: Mapped[str] = mapped_column(String)
    tier: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    merchant_reputation: Mapped[str] = mapped_column(String, default="UNKNOWN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    verifications: Mapped[list[Verification]] = relationship(back_populates="transaction")


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    tier: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING|COMPLETE
    # Embedding-driven risk score components captured at initiate time.
    risk_signals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Per-question Hume buckets and transcripts captured during verification.
    questions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    transaction: Mapped[Transaction] = relationship(back_populates="verifications")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # Nullable for NO_RISK transactions where no verification was opened.
    verification_id: Mapped[str | None] = mapped_column(
        ForeignKey("verifications.id"), index=True, nullable=True
    )
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    tier: Mapped[str] = mapped_column(String)
    hume_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    gemini_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    merchant_reputation: Mapped[str] = mapped_column(String)
    verdict: Mapped[dict] = mapped_column(JSON)
    risk_signals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    questions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[datetime] = mapped_column(DateTime)
    duration_ms: Mapped[int] = mapped_column(Integer)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    verification_id: Mapped[str] = mapped_column(ForeignKey("verifications.id"), index=True)
    audit_log_id: Mapped[str] = mapped_column(ForeignKey("audit_logs.id"))
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN|APPROVED|REJECTED
    note: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
