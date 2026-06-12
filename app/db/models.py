from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RequestType(str, PyEnum):
    DATA_ACCESS = "data-access"
    SYSTEM_ACCESS = "system-access"
    APP_ACCESS = "app-access"
    PRIVILEGE_ELEVATION = "privilege-elevation"


class RequestStatus(str, PyEnum):
    PENDING_REVIEW = "pending_review"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    REJECTED = "rejected"


class DecisionAction(str, PyEnum):
    APPROVE = "approve"
    REJECT = "reject"
    OVERRIDE = "override"


class Requester(Base):
    __tablename__ = "requesters"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    access_requests: Mapped[list["AccessRequest"]] = relationship(
        back_populates="requester"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    resource: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AccessRequest(Base):
    __tablename__ = "access_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("requesters.id"), nullable=False
    )
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[RequestType] = mapped_column(
        SAEnum(RequestType), nullable=False
    )
    classification_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    anomaly_factors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommended_approver: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    status: Mapped[RequestStatus] = mapped_column(
        SAEnum(RequestStatus),
        default=RequestStatus.PENDING_REVIEW,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    requester: Mapped["Requester"] = relationship(back_populates="access_requests")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="access_request")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    access_request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("access_requests.id"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[DecisionAction] = mapped_column(
        SAEnum(DecisionAction), nullable=False
    )
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    access_request: Mapped["AccessRequest"] = relationship(back_populates="decisions")
