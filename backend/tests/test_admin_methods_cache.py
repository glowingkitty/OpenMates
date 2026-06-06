"""
Regression tests for server administrator cache synchronization.

Admin promotion updates Directus and emits a WebSocket event, but the session
endpoint reads from the auth-session user cache. These tests keep the cached
is_admin flag aligned so self-hosted users can be promoted without logging out.
"""

import asyncio
import hashlib

from backend.core.api.app.services.directus.admin_methods import AdminMethods


class DummyCache:
    def __init__(self):
        self.deleted_keys = []
        self.updated_users = []
        self.published_events = []

    async def delete(self, key):
        self.deleted_keys.append(key)
        return True

    async def update_user(self, user_id, fields):
        self.updated_users.append((user_id, fields))
        return True

    async def publish_event(self, channel, event_data):
        self.published_events.append((channel, event_data))
        return True


class DummyDirectusService:
    def __init__(self, existing_admin=False):
        self.cache = DummyCache()
        self.user_updates = []
        self.created_items = []
        self.updated_items = []
        self.admins = []
        if existing_admin:
            self.admins.append(
                {"id": "admin-1", "hashed_user_id": self._hash_user_id("user-1"), "is_active": True}
            )

    @staticmethod
    def _hash_user_id(user_id):
        return hashlib.sha256(user_id.encode()).hexdigest()

    async def get_items(self, collection, params):
        assert collection == "server_admins"
        hashed_user_id = params["filter"]["hashed_user_id"]["_eq"]
        active = params["filter"]["is_active"]["_eq"]
        return [
            admin
            for admin in self.admins
            if admin["hashed_user_id"] == hashed_user_id and admin["is_active"] is active
        ]

    async def create_item(self, collection, data):
        assert collection == "server_admins"
        item = {"id": "admin-created", **data}
        self.admins.append(item)
        self.created_items.append((collection, item))
        return True, item

    async def update_item(self, collection, item_id, data):
        assert collection == "server_admins"
        self.updated_items.append((collection, item_id, data))
        for admin in self.admins:
            if admin["id"] == item_id:
                admin.update(data)
                return True
        return False

    async def update_user(self, user_id, fields):
        self.user_updates.append((user_id, fields))
        return True


def test_make_user_admin_updates_auth_session_cache_for_new_admin():
    directus_service = DummyDirectusService()

    success = asyncio.run(AdminMethods(directus_service).make_user_admin("user-1"))

    assert success is True
    assert directus_service.user_updates == [("user-1", {"is_admin": True})]
    assert directus_service.cache.updated_users == [("user-1", {"is_admin": True})]
    assert directus_service.cache.deleted_keys == []


def test_make_user_admin_updates_auth_session_cache_for_existing_admin():
    directus_service = DummyDirectusService(existing_admin=True)

    success = asyncio.run(AdminMethods(directus_service).make_user_admin("user-1"))

    assert success is True
    assert directus_service.created_items == []
    assert directus_service.user_updates == [("user-1", {"is_admin": True})]
    assert directus_service.cache.updated_users == [("user-1", {"is_admin": True})]


def test_revoke_admin_privileges_updates_auth_session_cache():
    directus_service = DummyDirectusService(existing_admin=True)

    success = asyncio.run(AdminMethods(directus_service).revoke_admin_privileges("user-1"))

    assert success is True
    assert directus_service.user_updates == [("user-1", {"is_admin": False})]
    assert directus_service.cache.updated_users == [("user-1", {"is_admin": False})]
    assert directus_service.cache.deleted_keys == []
