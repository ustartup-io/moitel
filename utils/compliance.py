"""Compliance gate helpers shared across middleware and routers."""
from __future__ import annotations

from db.models import User


def is_user_compliant(user: User | None) -> bool:
    """Check if a user has completed ALL compliance steps."""
    if user is None:
        return False
    return (
        user.age_confirmed_at is not None
        and user.jurisdiction_code is not None
        and user.jurisdiction_attested_at is not None
        and user.terms_accepted_at is not None
    )


def user_has_any_compliance(user: User | None) -> bool:
    """Check if a user has started (but not necessarily finished) compliance."""
    if user is None:
        return False
    return (
        user.age_confirmed_at is not None
        or user.jurisdiction_code is not None
        or user.terms_accepted_at is not None
    )
