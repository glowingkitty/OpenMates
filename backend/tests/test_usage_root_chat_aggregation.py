"""
Root-chat usage aggregation contract tests.

Top-level billing groups all attributable descendant operations under one root
while raw rows retain actual chat, depth, and charge identity for auditing.
Legacy rows without provable root ancestry remain explicit and are never guessed.
"""

from backend.core.api.app.services.directus import usage as usage_module


def test_usage_rows_group_under_one_root_without_losing_descendant_identity() -> None:
    aggregate = getattr(usage_module, "aggregate_usage_rows_by_root", None)
    assert callable(aggregate), "root usage aggregation helper is not implemented"
    rows = [
        {"id": "u-root", "chat_id": "root-1", "root_chat_id": "root-1", "actual_chat_id": "root-1", "depth": 0, "charge_id": "charge-1", "credits": 100},
        {"id": "u-child", "chat_id": "child-1", "root_chat_id": "root-1", "actual_chat_id": "child-1", "depth": 1, "charge_id": "charge-2", "credits": 200},
        {"id": "u-grandchild", "chat_id": "grandchild-1", "root_chat_id": "root-1", "actual_chat_id": "grandchild-1", "depth": 2, "charge_id": "charge-3", "credits": 300},
    ]

    grouped = aggregate(rows)

    assert list(grouped) == ["root-1"]
    assert grouped["root-1"]["total_credits"] == 600
    assert [entry["actual_chat_id"] for entry in grouped["root-1"]["entries"]] == [
        "root-1",
        "child-1",
        "grandchild-1",
    ]


def test_unattributed_legacy_usage_is_not_guessed_into_a_root() -> None:
    aggregate = getattr(usage_module, "aggregate_usage_rows_by_root", None)
    assert callable(aggregate), "root usage aggregation helper is not implemented"
    grouped = aggregate([
        {"id": "legacy-1", "chat_id": "missing-child", "root_chat_id": None, "credits": 50},
    ])

    assert grouped["unmatched_legacy"]["total_credits"] == 50
    assert grouped["unmatched_legacy"]["entries"][0]["id"] == "legacy-1"
