from __future__ import annotations

import pytest

from app.pieces.services import connectivity


@pytest.mark.asyncio
async def test_connectivity_requires_repeated_failures_before_offline(monkeypatch):
    async def no_probe():
        return []

    monkeypatch.setattr(connectivity, "_run_probes", no_probe)
    connectivity._failure_streak = 0
    connectivity._last_online_monotonic = None
    connectivity._last_online_status = None

    first = await connectivity.check_internet(force=True)
    second = await connectivity.check_internet(force=True)
    third = await connectivity.check_internet(force=True)

    assert first.online is False and first.conclusive is False
    assert second.online is False and second.conclusive is False
    assert third.online is False and third.conclusive is True


@pytest.mark.asyncio
async def test_any_successful_probe_confirms_connectivity_and_resets_failures(monkeypatch):
    async def one_probe():
        return ["ICMP"]

    monkeypatch.setattr(connectivity, "_run_probes", one_probe)
    connectivity._failure_streak = 2
    status = await connectivity.check_internet(force=True)

    assert status.online is True
    assert status.conclusive is True
    assert "ICMP" in status.detail
    assert connectivity._failure_streak == 0
