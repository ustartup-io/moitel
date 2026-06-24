"""ORM models — one per aggregate (singular PascalCase -> plural snake tables).

See MESSAGE 2 entity spec for the full field list. All models share the `Base`
from db.base and the TimestampMixin for created_at/updated_at.

Security note: Offer.delivery_payload stores a sensitive delivery value (access
code, private link). At rest it MUST be encrypted in a later step; the column
stores the ciphertext + we add a TODO. For MVP the column is nullable.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.base import (
    Base,
    BroadcastStatus,
    ClickSource,
    ConversionSource,
    ConversionStatus,
    DeliveryStatus,
    DeliveryType,
    Lang,
    OfferKind,
    PaymentProvider,
    PaymentStatus,
    RecipientStatus,
    SupportState,
    TimestampMixin,
    UserStatus,
    WebhookStatus,
)


class User(Base, TimestampMixin):
    """Bot user. PK = telegram_id (BIGINT, no autoincrement)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lang: Mapped[Lang] = mapped_column(
        Enum(Lang, name="lang_enum", native_enum=False, length=8),
        nullable=False,
        default=Lang.en,
        server_default="en",
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status_enum", native_enum=False, length=16),
        nullable=False,
        default=UserStatus.active,
        server_default="active",
    )
    age_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    jurisdiction_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    jurisdiction_attested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    marketing_opt_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    __table_args__ = (UniqueConstraint("id", name="uq_users_telegram_id"),)


class Offer(Base, TimestampMixin):
    """A single routable offer (affiliate link or paid access)."""

    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[OfferKind] = mapped_column(
        Enum(OfferKind, name="offer_kind_enum", native_enum=False, length=24),
        nullable=False,
        default=OfferKind.affiliate_link,
        server_default="affiliate_link",
    )
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    requires_payment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    price_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    delivery_type: Mapped[DeliveryType] = mapped_column(
        Enum(DeliveryType, name="delivery_type_enum", native_enum=False, length=32),
        nullable=False,
        default=DeliveryType.external_link,
        server_default="external_link",
    )
    # TODO(M-later): encrypt at rest; store ciphertext only after encryption wired.
    delivery_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction_allowlist: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )


class Referral(Base, TimestampMixin):
    """Referral code owned by a user, optionally tied to a specific offer."""

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    offer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("offers.id"), nullable=True, index=True
    )


class Click(Base):
    """Attribution click. Append-only (no updated_at)."""

    __tablename__ = "clicks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referral_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("referrals.id"), nullable=True, index=True
    )
    offer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("offers.id"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True, index=True
    )
    source: Mapped[ClickSource] = mapped_column(
        Enum(ClickSource, name="click_source_enum", native_enum=False, length=16),
        nullable=False,
        default=ClickSource.telegram,
        server_default="telegram",
    )
    ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ua_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )


class Conversion(Base, TimestampMixin):
    """A conversion event (pending/approved/rejected) tied to an offer."""

    __tablename__ = "conversions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    click_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("clicks.id"), nullable=True, index=True
    )
    referral_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("referrals.id"), nullable=True, index=True
    )
    offer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("offers.id"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True, index=True
    )
    partner_conversion_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    status: Mapped[ConversionStatus] = mapped_column(
        Enum(ConversionStatus, name="conversion_status_enum", native_enum=False, length=16),
        nullable=False,
        default=ConversionStatus.pending,
        server_default="pending",
    )
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[ConversionSource] = mapped_column(
        Enum(ConversionSource, name="conversion_source_enum", native_enum=False, length=16),
        nullable=False,
    )


class Payment(Base, TimestampMixin):
    """Crypto payment for a paid-access offer."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=True
    )
    offer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("offers.id"), nullable=False, index=True
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        Enum(PaymentProvider, name="payment_provider_enum", native_enum=False, length=16),
        nullable=False,
    )
    provider_invoice_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status_enum", native_enum=False, length=16),
        nullable=False,
        default=PaymentStatus.created,
        server_default="created",
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Delivery(Base, TimestampMixin):
    """A delivery record for digital access after payment/conversion."""

    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=True
    )
    payment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("payments.id"), nullable=True, index=True
    )
    conversion_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("conversions.id"), nullable=True, index=True
    )
    offer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("offers.id"), nullable=False, index=True
    )
    delivery_type: Mapped[DeliveryType] = mapped_column(
        Enum(DeliveryType, name="delivery_type_enum_offer", native_enum=False, length=32),
        nullable=False,
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status_enum", native_enum=False, length=16),
        nullable=False,
        default=DeliveryStatus.pending,
        server_default="pending",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportRequest(Base, TimestampMixin):
    """A user support request (open/answered/escalated/closed)."""

    __tablename__ = "support_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=True
    )
    lang: Mapped[Lang] = mapped_column(
        Enum(Lang, name="lang_enum_support", native_enum=False, length=8),
        nullable=False,
        default=Lang.en,
        server_default="en",
    )
    state: Mapped[SupportState] = mapped_column(
        Enum(SupportState, name="support_state_enum", native_enum=False, length=16),
        nullable=False,
        default=SupportState.open,
        server_default="open",
    )
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class WebhookEvent(Base):
    """Inbound webhook event (idempotent via dedupe_hash)."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_event_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    dedupe_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[WebhookStatus] = mapped_column(
        Enum(WebhookStatus, name="webhook_status_enum", native_enum=False, length=16),
        nullable=False,
        default=WebhookStatus.received,
        server_default="received",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Broadcast(Base, TimestampMixin):
    """An admin-initiated broadcast (queued + rate-limited sending)."""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    body_key_or_text: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[BroadcastStatus] = mapped_column(
        Enum(BroadcastStatus, name="broadcast_status_enum", native_enum=False, length=16),
        nullable=False,
        default=BroadcastStatus.draft,
        server_default="draft",
    )


class BroadcastRecipient(Base):
    """Per-recipient delivery status for a broadcast (opt-out respected)."""

    __tablename__ = "broadcast_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("broadcasts.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[RecipientStatus] = mapped_column(
        Enum(RecipientStatus, name="recipient_status_enum", native_enum=False, length=24),
        nullable=False,
        default=RecipientStatus.queued,
        server_default="queued",
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminAuditLog(Base):
    """Admin action audit trail."""

    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
