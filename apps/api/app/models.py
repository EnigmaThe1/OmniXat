import uuid
from datetime import datetime, timezone
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def uid() -> str:
    return str(uuid.uuid4())

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    company_number: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    company_status: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    accounts_due: Mapped[datetime.date | None] = mapped_column(Date)
    confirmation_due: Mapped[datetime.date | None] = mapped_column(Date)
    accounts_period_end: Mapped[datetime.date | None] = mapped_column(Date)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class PersonalTaxYear(Base):
    __tablename__ = "personal_tax_years"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    start_year: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    self_assessment_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    second_payment_expected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class CorporationTaxPeriod(Base):
    __tablename__ = "corporation_tax_periods"
    __table_args__ = (UniqueConstraint("company_id", "period_end"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    period_end: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    hmrc_return_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
