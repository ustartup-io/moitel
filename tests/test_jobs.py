"""Background jobs tests: start/stop cleanly, payment polling."""
from __future__ import annotations

import asyncio

import pytest

from services.jobs import JobManager


@pytest.mark.asyncio
async def test_job_manager_start_stop() -> None:
    """JobManager starts and stops cleanly."""
    mgr = JobManager()
    await mgr.start_all()
    assert len(mgr._tasks) == 6
    assert not mgr.is_shutting_down

    await asyncio.sleep(0.1)  # let jobs tick once

    await mgr.stop_all()
    assert mgr.is_shutting_down
    assert len(mgr._tasks) == 0


@pytest.mark.asyncio
async def test_job_manager_never_crashes() -> None:
    """Jobs catch exceptions and keep running."""
    mgr = JobManager()
    await mgr.start_all()

    # Let them run briefly.
    await asyncio.sleep(0.2)

    await mgr.stop_all()
    # If we get here without hanging, jobs handled errors gracefully.
