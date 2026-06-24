"""Seed the ONE real offer row for launch.

Usage:
    python -m scripts.seed_offer

This inserts a single active affiliate offer that the bot routes users to.
Edit the values below to match your real partner offer.
"""
import asyncio

from db.base import OfferKind
from db.repositories import OfferRepository
from db.session import get_session

# EDIT THESE VALUES for your real partner offer.
OFFER_CODE = "MAIN"
OFFER_TITLE_KEY = "offer.main"
OFFER_BASE_URL = "https://your-partner-offer.example.com/landing"
OFFER_KIND = OfferKind.affiliate_link
OFFER_REQUIRES_PAYMENT = False


async def seed() -> None:
    async with get_session() as session:
        repo = OfferRepository(session)
        existing = await repo.get_by_code(OFFER_CODE)
        if existing:
            print(f"Offer '{OFFER_CODE}' already exists (id={existing.id}). Skipping.")
            return
        offer = await repo.create(
            code=OFFER_CODE,
            title_key=OFFER_TITLE_KEY,
            base_url=OFFER_BASE_URL,
            kind=OFFER_KIND,
            requires_payment=OFFER_REQUIRES_PAYMENT,
        )
        await session.commit()
        print(f"Seeded offer: {offer.code} (id={offer.id})")


if __name__ == "__main__":
    asyncio.run(seed())
