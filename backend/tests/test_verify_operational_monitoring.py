"""
Behavior tests for the operational monitoring delivery verifier.

The verifier must parse only its structured CLI result and require an exact
environment/channel match with accepted per-channel receipts. Process success
alone must never count as delivery evidence.
"""

import json

from scripts.verify_operational_monitoring import _parse_output, _receipts_accepted


def _result(*, discord_state: str = "accepted") -> dict:
    return {
        "command": "monitoring digest",
        "deliveryState": "accepted" if discord_state == "accepted" else "partial_failure",
        "reportId": "report-1",
        "reportSha256": "abc123",
        "receipts": [
            {"environment": "development", "channel": "email", "state": "accepted"},
            {"environment": "development", "channel": "discord", "state": discord_state},
        ],
    }


# contract-test: direct surface=cli assertions=operational-monitoring.delivery.observable
def test_verifier_parses_structured_cli_output_after_non_json_lines():
    result = _result()
    assert _parse_output(f"building CLI\n{json.dumps(result)}\n") == result


# contract-test: direct surface=cli assertions=operational-monitoring.delivery.real-data-test,operational-monitoring.environments.isolated-labeled
def test_verifier_requires_exact_accepted_environment_and_channels():
    result = _result()
    assert _receipts_accepted(result, channels={"email", "discord"}, environment="development", returncode=0)
    assert not _receipts_accepted(result, channels={"email"}, environment="development", returncode=0)
    assert not _receipts_accepted(result, channels={"email", "discord"}, environment="production", returncode=0)
    assert not _receipts_accepted(result, channels={"email", "discord"}, environment="development", returncode=1)
    assert not _receipts_accepted(_result(discord_state="failed"), channels={"email", "discord"}, environment="development", returncode=0)
