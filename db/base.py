"""Declarative Base, shared enums, and naming conventions.

Single source of truth for the ORM metadata (`Base`) and all DB-level enums.
Naming conventions keep Alembic-generated constraint/index names stable.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import MetaData

# Stable naming convention so Alembic-generated DDL is deterministic.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Lang(enum.StrEnum):
    en = "en"
    ru = "ru"


class UserStatus(enum.StrEnum):
    active = "active"
    blocked = "blocked"
    flagged = "flagged"


class OfferKind(enum.StrEnum):
    affiliate_link = "affiliate_link"
    paid_access = "paid_access"


class DeliveryType(enum.StrEnum):
    external_link = "external_link"
    access_link = "access_link"
    file_ref = "file_ref"
    access_code = "access_code"
    text = "text"


class ClickSource(enum.StrEnum):
    telegram = "telegram"
    landing = "landing"
    external = "external"


class ConversionStatus(enum.StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ConversionSource(enum.StrEnum):
    postback = "postback"
    callback = "callback"
    manual = "manual"


class PaymentProvider(enum.StrEnum):
    xrocket = "xrocket"
    manual = "manual"


class PaymentStatus(enum.StrEnum):
    created = "created"
    pending = "pending"
    paid = "paid"
    expired = "expired"
    failed = "failed"
    refunded = "refunded"


class DeliveryStatus(enum.StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class SupportState(enum.StrEnum):
    open = "open"
    answered = "answered"
    escalated = "escalated"
    closed = "closed"


class WebhookStatus(enum.StrEnum):
    received = "received"
    processed = "processed"
    failed = "failed"


class BroadcastStatus(enum.StrEnum):
    draft = "draft"
    queued = "queued"
    sending = "sending"
    sent = "sent"
    failed = "failed"
    cancelled = "cancelled"


class RecipientStatus(enum.StrEnum):
    queued = "queued"
    sent = "sent"
    failed = "failed"
    skipped_optout = "skipped_optout"


class TimestampMixin:
    """created_at / updated_at on every table."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
