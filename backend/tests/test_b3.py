from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from rakathon_backend.b3.service import B3Service
from rakathon_backend.b3.watchdog import compute_reminders
from rakathon_backend.common.contracts import DataKind, Envelope
from rakathon_backend.common.errors import AuthError

_NOW = datetime(2030, 6, 1, tzinfo=UTC)


def _task(tid: str, due: str, status: str = "OPEN") -> dict[str, Any]:
    return {
        "id": tid,
        "ownerId": "clinician",
        "dueAt": due,
        "status": status,
        "requiredAckUserIds": ["clinician"],
        "acknowledgedBy": [],
        "patientRef": "Patient/p1",
        "version": 1,
    }


def test_compute_overdue_missing_done() -> None:
    tasks = [
        _task("t1", "2000-01-01T00:00:00+00:00"),
        _task("t2", "2031-01-01T00:00:00+00:00"),
        _task("t3", "2000-01-01T00:00:00+00:00", status="DONE"),
    ]
    reminders = compute_reminders(tasks, _NOW)
    reasons = {r["taskId"]: r["reason"] for r in reminders}
    assert reasons["t1"] == "overdue"
    assert reasons["t2"] == "missing_ack"
    assert "t3" not in reasons


async def _ok_auth(*, user_id: str, action: str, correlation_id: str) -> bool:
    _ = (user_id, action, correlation_id)
    return True


def _tick_req() -> Envelope:
    return Envelope(
        request_id="r-1",
        correlation_id="c-tick",
        source="b3",
        target="b3",
        action="watchdog.tick",
        data_kind=DataKind.METADATA,
        payload={},
        user_id="watchdog",
    )


async def test_tick_returns_count_only_and_dedupes() -> None:
    delivered: list[list[dict[str, Any]]] = []

    async def fetch(correlation_id: str) -> list[dict[str, Any]]:
        _ = correlation_id
        return [_task("t1", "2000-01-01T00:00:00+00:00")]

    async def deliver(reminders: list[dict[str, Any]], correlation_id: str) -> None:
        _ = correlation_id
        delivered.append(reminders)

    service = B3Service(fetch, deliver, _ok_auth, clock=lambda: _NOW)
    first = await service.handle(_tick_req())
    assert first.payload["count"] == 1
    assert set(first.payload) == {"count", "mode"}
    fresh, _computed = await service.tick("c-other")
    assert fresh == []
    assert len(delivered) == 1


async def test_tick_rejects_non_watchdog_user() -> None:
    async def fetch(correlation_id: str) -> list[dict[str, Any]]:
        _ = correlation_id
        return []

    service = B3Service(fetch, None, _ok_auth)
    bad = Envelope(
        request_id="r-1",
        correlation_id="c-1",
        source="b3",
        target="b3",
        action="watchdog.tick",
        data_kind=DataKind.METADATA,
        payload={},
        user_id="clinician",
    )
    with pytest.raises(AuthError):
        await service.handle(bad)


async def test_periodic_loop_stop() -> None:
    count = 0

    async def fetch(correlation_id: str) -> list[dict[str, Any]]:
        nonlocal count
        _ = correlation_id
        count += 1
        return []

    service = B3Service(fetch, None, _ok_auth, clock=lambda: _NOW)
    await service.start_loop(interval=0.02)
    await asyncio.sleep(0.07)
    await service.stop_loop()
    seen = count
    await asyncio.sleep(0.05)
    assert count == seen
