# contract-test-file: infrastructure
"""Guard the one-time AI-memory removal migration.

The migration must delete only rows owned by the AI app from the shared
encrypted app-memory collection. Historical chat collections and every other
app's rows remain outside the migration boundary.
"""

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = ROOT / "backend/core/directus/setup/migrate_remove_ai_memories.sql"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def load_setup_schemas_module():
    if "dotenv" not in sys.modules and importlib.util.find_spec("dotenv") is None:
        dotenv_stub = ModuleType("dotenv")
        dotenv_stub.load_dotenv = lambda *_args, **_kwargs: None
        sys.modules["dotenv"] = dotenv_stub
    return importlib.import_module("backend.core.directus.setup.setup_schemas")


def test_ai_memory_removal_sql_uses_exact_app_predicate() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    normalized = " ".join(migration.lower().split())

    assert (
        "delete from public.user_app_settings_and_memories where app_id = 'ai'"
        in normalized
    )
    assert " chats " not in f" {normalized} "
    assert "hashed_user_id" not in normalized
    assert "hashed_team_id" not in normalized


def test_ai_memory_removal_is_applied_and_verified(monkeypatch, tmp_path) -> None:
    setup_schemas = load_setup_schemas_module()

    migration = tmp_path / "migrate_remove_ai_memories.sql"
    migration.write_text(
        "DELETE FROM public.user_app_settings_and_memories WHERE app_id = 'ai';",
        encoding="utf-8",
    )
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        rowcount = 2

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            if sql.lstrip().lower().startswith("select"):
                self.rowcount = 1

        def fetchone(self):
            return (0,)

    class FakeConnection:
        autocommit = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        setup_schemas, "AI_MEMORY_REMOVAL_MIGRATION_PATH", str(migration)
    )
    monkeypatch.setattr(setup_schemas, "connect_database", FakeConnection)

    deleted_count = setup_schemas.apply_and_verify_ai_memory_removal()

    assert deleted_count == 2
    assert executed[0][0] == migration.read_text(encoding="utf-8")
    assert "where app_id = %s" in " ".join(executed[1][0].lower().split())
    assert executed[1][1] == ("ai",)


def test_ai_memory_removal_migration_is_packaged() -> None:
    setup_dockerfile = (ROOT / "backend/core/directus/setup/Dockerfile").read_text(
        encoding="utf-8"
    )
    selfhost_dockerfile = (
        ROOT / "backend/core/directus/Dockerfile.setup.selfhost"
    ).read_text(encoding="utf-8")

    assert "COPY . ." in setup_dockerfile
    assert "migrate_remove_ai_memories.sql" in selfhost_dockerfile


@pytest.mark.anyio
async def test_api_startup_purge_uses_only_exact_ai_filter() -> None:
    from backend.core.api.app.services.app_memory_removal import (
        MEMORY_COLLECTION,
        purge_removed_app_memory_rows,
    )

    class FakeDirectus:
        def __init__(self):
            self.rows = [
                {"id": "ai-personal", "app_id": "ai"},
                {"id": "ai-team", "app_id": "ai"},
                {"id": "travel", "app_id": "travel"},
            ]
            self.collections: list[str] = []
            self.filters: list[dict] = []

        async def get_items(self, collection, params):
            self.collections.append(collection)
            self.filters.append(params["filter"])
            app_id = params["filter"]["app_id"]["_eq"]
            return [
                {"id": row["id"]}
                for row in self.rows
                if row["app_id"] == app_id
            ][: params["limit"]]

        async def bulk_delete_items(self, collection, item_ids):
            self.collections.append(collection)
            self.rows = [row for row in self.rows if row["id"] not in item_ids]
            return True

    directus = FakeDirectus()
    deleted_count = await purge_removed_app_memory_rows(directus)

    assert deleted_count == 2
    assert directus.rows == [{"id": "travel", "app_id": "travel"}]
    assert set(directus.collections) == {MEMORY_COLLECTION}
    assert directus.filters
    assert all(item == {"app_id": {"_eq": "ai"}} for item in directus.filters)
