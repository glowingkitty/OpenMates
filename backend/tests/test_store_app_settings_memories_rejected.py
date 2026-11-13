"""Typed memory writes are rejected before persistence; first-party privacy data is not."""

from backend.shared.python_utils.app_memory_policy import (
    TYPED_MEMORY_REMOVED_ERROR,
    is_typed_memory_write_rejected,
)


# contract-test: supporting surface=rest_api assertions=app-memories.catalog.no-typed-types,app-memories.typed.removed
def test_typed_memory_owners_are_rejected_and_privacy_data_is_not():
    for app_id in ("code", "travel", "events", "study", "reminder", "", None):
        assert is_typed_memory_write_rejected(app_id)
    assert not is_typed_memory_write_rejected("privacy")
    assert "create a Memory" in TYPED_MEMORY_REMOVED_ERROR
