"""Content-free timing for the Project-file completion path."""

import asyncio

import pytest

pytest.importorskip("celery")

from backend.apps.ai.tasks import stream_consumer


def _record_stage_logs(monkeypatch):
    records = []
    monkeypatch.setattr(stream_consumer.logger, "info", lambda message, *args: records.append(message % args))
    return records


# contract-test: tooling
def test_project_file_finalization_stage_reports_failure_without_request_data(monkeypatch):
    records = _record_stage_logs(monkeypatch)
    with pytest.raises(RuntimeError):
        with stream_consumer._project_file_finalization_stage("persistence", True):
            raise RuntimeError("private response text")

    assert len(records) == 1
    assert "stage=persistence" in records[0]
    assert "outcome=error" in records[0]
    assert "duration_ms=" in records[0]
    assert "private response text" not in records[0]


# contract-test: tooling
def test_project_file_finalization_stage_reports_cancellation_and_disabled_path(monkeypatch):
    records = _record_stage_logs(monkeypatch)
    with pytest.raises(asyncio.CancelledError):
        with stream_consumer._project_file_finalization_stage("ticket", True):
            raise asyncio.CancelledError()
    with stream_consumer._project_file_finalization_stage("billing", False):
        pass

    assert len(records) == 1
    assert "stage=ticket" in records[0]
    assert "outcome=cancelled" in records[0]


@pytest.mark.asyncio
# contract-test: tooling
async def test_project_file_finalization_stage_finishes_after_awaited_ack(monkeypatch):
    records = _record_stage_logs(monkeypatch)
    entered = asyncio.Event()
    acknowledged = asyncio.Event()

    async def persist():
        with stream_consumer._project_file_finalization_stage("persistence", True):
            entered.set()
            await acknowledged.wait()

    pending = asyncio.create_task(persist())
    await entered.wait()
    assert records == []
    acknowledged.set()
    await pending

    assert len(records) == 1
    assert "stage=persistence" in records[0]
    assert "outcome=ok" in records[0]
