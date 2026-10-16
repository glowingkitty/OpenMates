"""Focused count and ciphertext byte bounds for interactive chat windows."""

from backend.core.api.app.services.bounded_message_window import (
    MESSAGE_WINDOW_BYTES, MESSAGE_WINDOW_LIMIT, bound_encrypted_message_window,
)


def _row(index: int, size: int) -> dict:
    return {"id": f"db-{index}", "client_message_id": f"message-{index}",
            "created_at": index, "encrypted_content": "A" * size}


# contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
def test_latest_window_stops_at_byte_boundary_and_keeps_cursor() -> None:
    rows = [_row(1, 150_000), _row(2, 80_000), _row(3, 80_000)]
    page = bound_encrypted_message_window({"messages": rows, "has_more_before": False}, direction="latest")
    assert [row["client_message_id"] for row in page["messages"]] == ["message-2", "message-3"]
    assert page["has_more_before"] is True
    assert page["start_cursor"] == {"created_at": 2, "message_id": "message-2"}
    assert page["payload_bytes"] <= MESSAGE_WINDOW_BYTES


# contract-test: supporting surface=rest_api assertions=storage.cold.independent-message-pages
def test_oversized_message_has_exact_cursor_without_silent_skip() -> None:
    rows = [_row(1, 20), _row(2, MESSAGE_WINDOW_BYTES)]
    page = bound_encrypted_message_window({"messages": rows, "has_more_before": False}, direction="latest")
    assert page["messages"] == []
    assert page["oversized_message"] is True
    assert page["oversized_message_cursor"] == {"created_at": 2, "message_id": "message-2"}
    assert page["has_more_before"] is True


# contract-test: supporting surface=rest_api assertions=storage.cold.independent-message-pages
def test_after_window_exposes_oversized_first_record() -> None:
    rows = [_row(1, MESSAGE_WINDOW_BYTES), _row(2, 20)]
    page = bound_encrypted_message_window({"messages": rows, "has_more_after": False}, direction="after")
    assert page["messages"] == []
    assert page["oversized_message_cursor"]["message_id"] == "message-1"
    assert page["has_more_after"] is True


# contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
def test_message_window_limit_is_fixed_for_all_interactive_readers() -> None:
    assert MESSAGE_WINDOW_LIMIT == 20


# contract-test: supporting surface=rest_api assertions=storage.cold.independent-message-pages
def test_large_archive_reference_signals_exact_read_without_hydration() -> None:
    ref = {"client_message_id": "large", "created_at": 10,
           "large_payload": {"size_bytes": 500_000, "checksum": "a" * 64,
                             "object_key": "message-pages/example/large.json"}}
    page = bound_encrypted_message_window({"messages": [ref]}, direction="latest")
    assert page["messages"] == []
    assert page["oversized_message_cursor"] == {"created_at": 10, "message_id": "large"}
    assert page["has_more_before"] is True

    second_pass = bound_encrypted_message_window(page, direction="latest")
    assert second_pass["oversized_message_cursor"] == page["oversized_message_cursor"]
