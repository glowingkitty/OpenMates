"""Team trace fields must remain useful after normal privacy log filtering."""

import hashlib
import logging
import re

import pytest

from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.shared.python_utils.team_log_correlation import team_correlation_fields


# contract-test: supporting surface=rest_api assertions=teams.collaboration.realtime-team-sync,operational-monitoring.content.privacy-boundary
def test_team_correlation_survives_sensitive_data_filter_without_raw_ids():
    ids = {
        "team_id": "11111111-1111-4111-8111-111111111111",
        "chat_id": "22222222-2222-4222-8222-222222222222",
        "message_id": "33333333-3333-4333-8333-333333333333",
        "task_id": "44444444-4444-4444-8444-444444444444",
    }
    fields = team_correlation_fields(**ids)
    record = logging.makeLogRecord({
        "name": "backend.team", "levelno": logging.INFO,
        "msg": "Team AI pipeline correlation %s stage=main status=completed",
        "args": (fields,),
    })

    assert SensitiveDataFilter().filter(record)
    filtered = record.getMessage()
    for label, raw_id in zip(("team_hash", "chat_hash", "message_hash", "task_hash"), ids.values()):
        assert f"{label}={hashlib.sha256(raw_id.encode()).hexdigest()}" in filtered
        assert raw_id not in filtered
    assert "[REDACTED" not in filtered
    assert len(re.findall(r"(?:team|chat|message|task)_hash=[0-9a-f]{64}", filtered)) == 4


# contract-test: supporting surface=rest_api assertions=operational-monitoring.content.privacy-boundary
def test_team_correlation_rejects_missing_identifiers():
    with pytest.raises(ValueError):
        team_correlation_fields(team_id="team", chat_id="", message_id="message")
