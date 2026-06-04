"""Tests for Projects V1 backend helpers.

Projects protect referenced embeds from chat/message deletion. These tests use
mocked Directus services so they run quickly without a live CMS.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.project_methods import ProjectMethods, hash_id


@pytest.mark.asyncio
async def test_project_reference_counts_group_by_project() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(
        return_value=[
            {"target_id_hash": hash_id("embed-1"), "hashed_project_id": "project-a"},
            {"target_id_hash": hash_id("embed-1"), "hashed_project_id": "project-b"},
            {"target_id_hash": hash_id("embed-1"), "hashed_project_id": "project-a"},
            {"target_id_hash": hash_id("embed-2"), "hashed_project_id": "project-a"},
        ]
    )

    methods = ProjectMethods(directus)
    counts = await methods.get_project_embed_reference_counts(["embed-1", "embed-2", "embed-3"], "user-1")

    assert counts == {"embed-1": 2, "embed-2": 1, "embed-3": 0}
    directus.get_items.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_items_for_target_hashes_filters_by_user_and_type() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    directus.delete_items = AsyncMock(return_value=2)

    methods = ProjectMethods(directus)
    deleted = await methods.remove_items_for_target_hashes([hash_id("embed-1")], "embed", "user-1")

    assert deleted == 2
    directus.delete_items.assert_awaited_once_with(
        "project_items",
        {
            "target_id_hash": {"_in": [hash_id("embed-1")]},
            "item_type": {"_eq": "embed"},
            "hashed_user_id": {"_eq": hash_id("user-1")},
        },
    )


@pytest.mark.asyncio
async def test_remove_items_for_target_hashes_decrements_each_project_count() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(
        side_effect=[
            [
                {"hashed_project_id": "project-a"},
                {"hashed_project_id": "project-a"},
                {"hashed_project_id": "project-b"},
            ],
            [{"id": "a", "item_count": 5}],
            [{"id": "b", "item_count": 2}],
        ]
    )
    directus.delete_items = AsyncMock(return_value=3)
    directus.update_item = AsyncMock()

    methods = ProjectMethods(directus)
    deleted = await methods.remove_items_for_target_hashes([hash_id("embed-1")], "embed", "user-1")

    assert deleted == 3
    directus.update_item.assert_any_await("projects", "a", {"item_count": 3})
    directus.update_item.assert_any_await("projects", "b", {"item_count": 1})
