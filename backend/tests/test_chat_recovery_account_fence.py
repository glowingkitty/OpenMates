# contract-test-file: infrastructure
"""Account deletion must run the guarded recovery transaction before key removal."""

import pytest

from backend.core.api.app.services import chat_recovery_service


# contract-test: direct surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_account_fence_helper_uses_authoritative_guarded_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    class Recovery:
        def __init__(self, _directus: object) -> None:
            pass

        async def execute(self, operation: str, data: dict) -> dict:
            calls.append((operation, data))
            return {"invalidated_outputs": 2}

    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", Recovery)
    result = await chat_recovery_service.assert_no_pending_team_account_recovery(
        directus_service=object(), user_id_hash="a" * 64,
    )
    assert result == {"invalidated_outputs": 2}
    assert calls == [("invalidate_deletion", {
        "protocol_version": 1, "hashed_user_id": "a" * 64, "scope": "account",
    })]


# contract-test: direct surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_account_fence_helper_propagates_missing_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingRecovery:
        def __init__(self, _directus: object) -> None:
            pass

        async def execute(self, _operation: str, _data: dict) -> dict:
            raise chat_recovery_service.ChatRecoveryProtocolError(404, "extension_unavailable")

    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", MissingRecovery)
    with pytest.raises(chat_recovery_service.ChatRecoveryProtocolError) as error:
        await chat_recovery_service.assert_no_pending_team_account_recovery(
            directus_service=object(), user_id_hash="a" * 64,
        )
    assert error.value.status_code == 404
