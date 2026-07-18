"""Teams V1 memory context isolation tests.

Team memories share the existing encrypted app settings/memories collection, but
server-visible context must remain explicit. Personal lookups require a null
team hash, while team lookups use the team hash and must not fall back to a
member's personal memories.
"""

from collections import defaultdict

import pytest

from backend.core.api.app.services.directus.app_settings_and_memories_methods import AppSettingsAndMemoriesMethods
from backend.core.api.app.services.directus.team_methods import hash_id


class FakeDirectusService:
    def __init__(self) -> None:
        self.cache_service = None
        self.rows: dict[str, list[dict]] = defaultdict(list)

    async def get_items(self, collection: str, params: dict | None = None, **_kwargs):
        rows = list(self.rows[collection])
        filters = (params or {}).get("filter") or {}
        for field, condition in filters.items():
            if not isinstance(condition, dict):
                continue
            if "_eq" in condition:
                rows = [row for row in rows if row.get(field) == condition["_eq"]]
            if condition.get("_null") is True:
                rows = [row for row in rows if row.get(field) is None]
        return rows[: (params or {}).get("limit", len(rows))]

    async def create_item(self, collection: str, payload: dict):
        row = {"id": payload.get("id") or f"row-{len(self.rows[collection]) + 1}", **payload}
        self.rows[collection].append(row)
        return row

    async def update_item(self, collection: str, item_id: str, payload: dict):
        for row in self.rows[collection]:
            if row.get("id") == item_id:
                row.update(payload)
                return row
        return None

    async def delete_item(self, collection: str, item_id: str):
        before = len(self.rows[collection])
        self.rows[collection] = [row for row in self.rows[collection] if row.get("id") != item_id]
        return len(self.rows[collection]) != before


@pytest.mark.anyio
async def test_memory_helper_separates_personal_and_team_rows() -> None:
    directus = FakeDirectusService()
    methods = AppSettingsAndMemoriesMethods(directus)
    directus.rows[methods.COLLECTION_NAME].extend(
        [
            {
                "id": "personal-row",
                "hashed_user_id": hash_id("alice"),
                "hashed_team_id": None,
                "app_id": "travel",
                "item_key": "prefs",
                "item_type": "preferences",
                "encrypted_item_json": "enc:personal",
            },
            {
                "id": "team-row",
                "hashed_user_id": hash_id("alice"),
                "hashed_team_id": hash_id("team-1"),
                "app_id": "travel",
                "item_key": "prefs",
                "item_type": "preferences",
                "encrypted_item_json": "enc:team",
            },
        ]
    )

    personal = await methods.get_user_app_item_raw("alice", "travel", "prefs")
    team = await methods.get_user_app_item_raw("bob", "travel", "prefs", team_id="team-1")

    assert personal and personal["id"] == "personal-row"
    assert team and team["id"] == "team-row"


@pytest.mark.anyio
async def test_team_memory_write_sets_team_hash_without_overwriting_personal_row() -> None:
    directus = FakeDirectusService()
    methods = AppSettingsAndMemoriesMethods(directus)
    directus.rows[methods.COLLECTION_NAME].append(
        {
            "id": "personal-row",
            "hashed_user_id": hash_id("alice"),
            "hashed_team_id": None,
            "app_id": "travel",
            "item_key": "prefs",
            "encrypted_item_json": "enc:personal",
        }
    )

    written = await methods.set_user_app_item_raw("alice", "travel", "prefs", "enc:team", 200, team_id="team-1")

    assert written and written["hashed_team_id"] == hash_id("team-1")
    assert {row["encrypted_item_json"] for row in directus.rows[methods.COLLECTION_NAME]} == {"enc:personal", "enc:team"}
