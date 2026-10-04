# contract-test-file: infrastructure
"""Read-only inventory emits sizes and counts, never item ciphertext."""

from datetime import datetime, timezone

from backend.scripts.inventory_directus_storage import inventory


class Cursor:
    def __init__(self):
        self.queries = []
        self.rows = [
            [("messages", 12, 2048)],
            [("messages", "create", None, 12, 0, 0,
              datetime(2026, 1, 1, tzinfo=timezone.utc),
              datetime(2026, 1, 2, tzinfo=timezone.utc))],
        ]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, sql):
        self.queries.append(sql)

    def fetchall(self):
        return self.rows.pop(0)


class Connection:
    def __init__(self):
        self.selected = Cursor()

    def cursor(self):
        return self.selected


def test_inventory_runs_read_only_and_emits_no_revision_payload() -> None:
    connection = Connection()
    result = inventory(connection)
    assert connection.selected.queries[0] == "SET TRANSACTION READ ONLY"
    assert all("SELECT" in query for query in connection.selected.queries[1:])
    assert result["tables"] == [{"table": "messages", "estimated_rows": 12, "total_bytes": 2048}]
    assert result["by_collection"][0]["revision_rows"] == 0
    assert "2026-01-01" in result["by_collection"][0]["first_activity"]
    assert all("encrypted_content" not in query for query in connection.selected.queries)
