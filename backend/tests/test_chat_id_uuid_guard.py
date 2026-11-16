# contract-test-file: infrastructure
from backend.core.api.app.utils.chat_id import is_valid_uuid


def test_uuid_guard():
    assert is_valid_uuid("123e4567-e89b-12d3-a456-426614174000")
    assert not is_valid_uuid("incognito-abc")
    assert not is_valid_uuid(None)
    assert not is_valid_uuid("")
