"""Support service: FAQ matching, escalation tracking, admin routing.

Rules-based: keyword matching (no ML/NLP). Escalation after N=2 unmatched
attempts or on explicit triggers (stuck payment, delivery, suspicious state).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_conf import get_logger
from db.base import SupportState
from db.models import SupportRequest, User
from db.repositories import SupportRepository
from utils.faq import FaqMatcher

log = get_logger("app.support")

MAX_UNMATCHED_ATTEMPTS = 2


@dataclass
class SupportInteraction:
    """Result of a user's support interaction."""

    action: Literal["answered", "escalate", "no_match"]
    answer: str = ""
    faq_id: str = ""
    attempt_count: int = 0
    request: SupportRequest | None = None


class SupportService:
    """Handles FAQ matching, escalation, and support request lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        faq: FaqMatcher | None = None,
    ) -> None:
        self.session = session
        self.repo = SupportRepository(session)
        self._faq = faq

    def _get_faq_matcher(self) -> FaqMatcher:
        if self._faq is not None:
            return self._faq
        from utils.faq import faq_matcher
        return faq_matcher

    async def get_or_create_request(self, user: User) -> SupportRequest:
        """Get the user's open support request, or create a new one."""
        existing = await self.repo.get_open_for_user(user.id)
        if existing:
            return existing
        return await self.repo.create(user_id=user.id, lang=user.lang)

    async def process_message(
        self,
        user: User,
        message: str,
        category: str | None = None,
    ) -> SupportInteraction:
        """Process a free-text support message.

        Returns SupportInteraction with the action to take.
        """
        request = await self.get_or_create_request(user)

        # Update last message + context.
        request.last_message = message[:500]
        if category:
            request.category = category

        # Track unmatched attempts in context_json.
        context = self._parse_context(request.context_json)
        attempt_count: int = int(context.get("unmatched_count", 0))

        # Try FAQ match.
        matcher = self._get_faq_matcher()
        result = matcher.match(message, str(user.lang))

        if result.matched and result.item:
            # Answer found — update context, return to user.
            context["unmatched_count"] = 0
            context["last_faq_id"] = result.item.id
            request.context_json = json.dumps(context)
            request.state = SupportState.answered
            await self.session.flush()

            return SupportInteraction(
                action="answered",
                answer=result.answer,
                faq_id=result.item.id,
                attempt_count=0,
                request=request,
            )

        # No match — increment attempt counter.
        attempt_count += 1
        context["unmatched_count"] = attempt_count
        request.context_json = json.dumps(context)
        request.last_message = message[:500]
        await self.session.flush()

        # Escalate after N unmatched attempts.
        if attempt_count >= MAX_UNMATCHED_ATTEMPTS:
            return await self._escalate(request, user, reason="unmatched_threshold")

        return SupportInteraction(
            action="no_match",
            attempt_count=attempt_count,
            request=request,
        )

    async def escalate_now(
        self, user: User, reason: str = "user_requested"
    ) -> SupportInteraction:
        """Immediately escalate to admin (explicit user/admin action)."""
        request = await self.get_or_create_request(user)
        return await self._escalate(request, user, reason)

    async def _escalate(
        self, request: SupportRequest, user: User, reason: str
    ) -> SupportInteraction:
        """Transition a request to escalated state."""
        request.state = SupportState.escalated
        context = self._parse_context(request.context_json)
        context["escalation_reason"] = reason
        context["escalated_at"] = True
        request.context_json = json.dumps(context)
        await self.session.flush()

        log.info(
            "support.escalated",
            request_id=request.id,
            user_id=user.id,
            reason=reason,
        )
        return SupportInteraction(
            action="escalate",
            attempt_count=int(context.get("unmatched_count", 0)),
            request=request,
        )

    async def close_request(self, request_id: int) -> SupportRequest | None:
        """Close a support request."""
        req = await self.session.get(SupportRequest, request_id)
        if req is None:
            return None
        req.state = SupportState.closed
        await self.session.flush()
        log.info("support.closed", request_id=request_id)
        return req

    async def get_by_id(self, request_id: int) -> SupportRequest | None:
        """Get a support request by ID."""
        return await self.session.get(SupportRequest, request_id)

    def build_admin_card(
        self, request: SupportRequest, user: User, username: str | None = None
    ) -> str:
        """Build a structured escalation card for the admin."""
        context = self._parse_context(request.context_json)
        reason = context.get("escalation_reason", "unknown")
        card = (
            f"🔔 New escalation\n"
            f"User: {user.id} (@{username or 'unknown'})\n"
            f"Lang: {request.lang}\n"
            f"Request: #{request.id}\n"
            f"Reason: {reason}\n"
            f"State: {request.state}\n"
            f"Message: {request.last_message or '(none)'}"
        )
        return card

    def _parse_context(self, context_json: str | None) -> dict[str, Any]:
        """Parse context_json safely."""
        if not context_json:
            return {}
        try:
            parsed = json.loads(context_json)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
