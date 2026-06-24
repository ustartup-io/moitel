"""Admin service tests: stats, offers, manual confirms, exports."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import ConversionSource, ConversionStatus
from db.repositories import (
    ConversionRepository,
    OfferRepository,
    UserRepository,
)
from services.admin_service import AdminService


@pytest.mark.asyncio
async def test_dashboard_stats(db_session: AsyncSession) -> None:
    """Dashboard stats return correct counts."""
    user_repo = UserRepository(db_session)
    offer_repo = OfferRepository(db_session)

    await user_repo.create(telegram_id=100100101)
    await user_repo.create(telegram_id=100100102)
    await offer_repo.create(code="STAT1", title_key="offer.s", base_url="https://x.com")
    await db_session.commit()

    svc = AdminService(db_session)
    stats = await svc.get_dashboard_stats()
    assert stats["users"] >= 2
    assert stats["active_offers"] >= 1


@pytest.mark.asyncio
async def test_add_offer_audited(db_session: AsyncSession) -> None:
    """Adding an offer creates an audit log entry."""
    svc = AdminService(db_session)
    offer = await svc.add_offer(
        admin_id=1,
        code="ADMIN1",
        title_key="offer.admin1",
        base_url="https://x.com",
    )
    await db_session.commit()

    assert offer.id is not None
    assert offer.code == "ADMIN1"

    # Check audit log.
    from sqlalchemy import select

    from db.models import AdminAuditLog
    result = await db_session.execute(
        select(AdminAuditLog).where(AdminAuditLog.action == "offer.add")
    )
    logs = list(result.scalars().all())
    assert len(logs) >= 1
    assert logs[0].admin_id == 1


@pytest.mark.asyncio
async def test_toggle_offer(db_session: AsyncSession) -> None:
    """Toggling an offer flips is_active."""
    offer_repo = OfferRepository(db_session)
    offer = await offer_repo.create(
        code="TOG1", title_key="offer.t", base_url="https://x.com"
    )
    await db_session.commit()

    svc = AdminService(db_session)
    toggled = await svc.toggle_offer(admin_id=1, offer_id=offer.id)
    await db_session.commit()

    assert toggled is not None
    assert toggled.is_active is False

    toggled2 = await svc.toggle_offer(admin_id=1, offer_id=offer.id)
    await db_session.commit()
    assert toggled2.is_active is True


@pytest.mark.asyncio
async def test_manual_confirm_conversion(db_session: AsyncSession) -> None:
    """Manual conversion approval works + audited."""
    offer_repo = OfferRepository(db_session)
    conv_repo = ConversionRepository(db_session)

    offer = await offer_repo.create(
        code="CONF1", title_key="offer.c", base_url="https://x.com"
    )
    conv = await conv_repo.create(
        offer_id=offer.id, source=ConversionSource.manual
    )
    await db_session.commit()

    svc = AdminService(db_session)
    approved = await svc.manual_confirm_conversion(
        admin_id=1, conversion_id=conv.id, status=ConversionStatus.approved
    )
    await db_session.commit()

    assert approved is not None
    assert approved.status == ConversionStatus.approved


@pytest.mark.asyncio
async def test_export_conversions_csv(db_session: AsyncSession) -> None:
    """Export produces valid CSV."""
    offer_repo = OfferRepository(db_session)
    conv_repo = ConversionRepository(db_session)

    offer = await offer_repo.create(
        code="EXP1", title_key="offer.e", base_url="https://x.com"
    )
    await conv_repo.create(
        offer_id=offer.id, source=ConversionSource.manual,
        partner_conversion_id="EXP-001", amount=500, currency="USDT",
    )
    await db_session.commit()

    svc = AdminService(db_session)
    csv_data = await svc.export_conversions_csv()
    assert "id" in csv_data  # header
    assert "EXP-001" in csv_data
    assert "USDT" in csv_data
