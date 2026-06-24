"""FSM states for the support conversation flow."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SupportStates(StatesGroup):
    """States for the support conversation."""

    browsing = State()
    asking = State()
    answered = State()
    escalated = State()
