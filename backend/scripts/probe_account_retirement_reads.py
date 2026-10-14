"""Prove account cleanup reads against real Directus in disposable CI only."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid

import httpx


def require_isolation() -> None:
    required = {
        "CI": "true", "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_CI_MAIL_CAPTURE": "1", "CMS_URL": "http://cms:8055",
        "SERVER_ENVIRONMENT": "development",
    }
    if any(os.getenv(key) != value for key, value in required.items()):
        raise RuntimeError("Account retirement read probe requires isolated CI")


def project_fixture_records(*, project_ids: list[str], item_ids: list[str],
                            target_ids: list[str], owner_hashes: list[str], timestamp: int) -> dict:
    """Build real Project ownership/actor context around existing chat targets."""
    from scripts.verify_projects_api import opaque_ciphertext, project_payload

    if not (len(project_ids) == len(item_ids) == len(target_ids) == len(owner_hashes) == 2):
        raise ValueError("Project read probe requires two complete Project contexts")
    projects, wrappers, items = [], [], []
    for project_id, item_id, target_id, owner in zip(project_ids, item_ids, target_ids, owner_hashes):
        payload = project_payload(project_id, timestamp=timestamp)
        payload.pop("key_wrappers")  # API input only; durable wrappers are separate rows.
        wrapped_key = payload.pop("encrypted_project_key")
        project_hash = hashlib.sha256(project_id.encode()).hexdigest()
        projects.append({
            **payload, "id": project_id, "hashed_user_id": owner, "hashed_team_id": None,
            "created_by_user_hash": owner, "pinned": False, "archived": False,
            "is_private": True, "is_shared": False, "version": 1, "item_count": 1,
        })
        wrappers.append({
            "id": str(uuid.uuid4()), "hashed_project_id": project_hash,
            "hashed_user_id": owner, "hashed_team_id": None, "key_type": "master",
            "encrypted_project_key": wrapped_key, "wrapper_version": 1, "created_at": timestamp,
        })
        items.append({
            "id": item_id, "project_item_id": item_id, "hashed_project_id": project_hash,
            "hashed_user_id": owner, "hashed_team_id": None, "attached_by_user_hash": owner,
            "hashed_folder_id": None, "item_type": "chat", "deleted_target_state": None,
            "target_id_hash": hashlib.sha256(target_id.encode()).hexdigest(),
            "target_id_encrypted": opaque_ciphertext(), "encrypted_display_name": opaque_ciphertext(),
            "created_at": timestamp, "updated_at": timestamp, "position": 0,
        })
    return {"projects": projects, "project_key_wrappers": wrappers, "project_items": items}


async def require_account_project_fence(directus, *, owner_id: str, owner_hash: str) -> None:
    from backend.core.api.app.services.storage_reference_service import assert_no_surviving_account_project_references

    try:
        await assert_no_surviving_account_project_references(
            directus_service=directus, user_id=owner_id, user_id_hash=owner_hash,
        )
    except RuntimeError as error:
        if str(error) != "A surviving Project references account content; move or detach it before deletion":
            raise
    else:
        raise AssertionError("Full account preflight did not preserve the foreign Project reference")


async def main() -> dict:
    require_isolation()  # Before opening any account or database connection.
    logging.disable(logging.CRITICAL)
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.scoped_directus_pagination import read_complete_scoped_records
    from backend.core.api.app.services.account_content_deletion_service import load_account_personal_embed_key_ids
    from backend.core.api.app.services.storage_reference_service import (
        AccountDeletableEmbedRows, _surviving_project_target_hashes,
    )

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    prefix = "ci-account-retirement-" + uuid.uuid4().hex
    owner_id, foreign_owner_id = str(uuid.uuid4()), str(uuid.uuid4())
    owner, foreign, team = digest(owner_id), digest(foreign_owner_id), digest(prefix + "team")
    personal_ids = [str(uuid.uuid4()) for _ in range(121)]
    team_id, foreign_id = str(uuid.uuid4()), str(uuid.uuid4())
    key_ids = personal_ids + [team_id, foreign_id]
    item_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    project_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    targets = [str(uuid.uuid4()) for _ in range(500)]
    project_fixture = project_fixture_records(
        project_ids=project_ids, item_ids=item_ids, target_ids=targets[:2],
        owner_hashes=[owner, foreign], timestamp=int(time.time()),
    )
    # Cleanup children before parents, respecting the real deletion guards.
    created = {"embed_keys": key_ids, "project_items": item_ids,
               "project_key_wrappers": [row["id"] for row in project_fixture["project_key_wrappers"]],
               "projects": project_ids,
               "embeds": key_ids, "chats": targets[:2]}
    admin = httpx.Client(base_url="http://cms:8055", timeout=30)
    directus = DirectusService()
    try:
        response = admin.post("/auth/login", json={
            "email": os.environ["DATABASE_ADMIN_EMAIL"],
            "password": os.environ["DATABASE_ADMIN_PASSWORD"], "mode": "json",
        })
        response.raise_for_status()
        admin.headers["Authorization"] = "Bearer " + response.json()["data"]["access_token"]
        keys = [{"id": key_id, "hashed_embed_id": digest(key_id),
                 "key_type": "master", "hashed_user_id": owner,
                 "encrypted_embed_key": "synthetic-ci-ciphertext"} for key_id in personal_ids]
        keys += [
            {**keys[0], "id": team_id, "hashed_embed_id": digest(team_id), "hashed_team_id": team},
            {**keys[0], "id": foreign_id, "hashed_embed_id": digest(foreign_id), "hashed_user_id": foreign},
        ]
        response = admin.post("/items/embeds", json=[
            {"id": key["id"], "embed_id": key["id"], "hashed_embed_id": key["hashed_embed_id"],
             "hashed_user_id": key["hashed_user_id"], "hashed_team_id": key.get("hashed_team_id"),
             "status": "finished", "storage_state": "hot", "encryption_mode": "client",
             "encrypted_content": "synthetic-ci-ciphertext"}
            for key in keys
        ])
        response.raise_for_status()
        response = admin.post("/items/chats", json=[
            {"id": target, "hashed_user_id": owner, "storage_state": "hot"}
            for target in targets[:2]
        ])
        response.raise_for_status()
        response = admin.post("/items/embed_keys", json=keys)
        response.raise_for_status()
        for collection, records in project_fixture.items():
            response = admin.post(f"/items/{collection}", json=records)
            response.raise_for_status()

        rows = await read_complete_scoped_records(
            directus, "embed_keys", admin_required=True,
            params={"fields": "id", "filter[hashed_user_id][_eq]": owner},
        )
        if {row["id"] for row in rows} != set(personal_ids + [team_id]):
            raise AssertionError("UUID pagination truncated keys or escaped the owner scope")
        selected = await load_account_personal_embed_key_ids(
            directus_service=directus, user_id_hash=owner,
            eligible_embed_rows=AccountDeletableEmbedRows(embeds=(), versions=()),
        )
        if set(selected) != set(personal_ids):
            raise AssertionError("Account deletion selected shared or foreign keys or lost personal keys")
        surviving = await _surviving_project_target_hashes(
            directus_service=directus, target_ids=targets, item_type="chat", user_id_hash=owner,
        )
        if surviving != {digest(targets[1])}:
            raise AssertionError("Large Project reference query lost its foreign ownership fence")
        await require_account_project_fence(directus, owner_id=owner_id, owner_hash=owner)
        return {"status": "passed", "personal_keys": 121, "uuid_rows": 122,
                "shared_keys_preserved": True, "foreign_keys_preserved": True,
                "large_query_targets": 500, "foreign_project_fence": True,
                "full_account_project_preflight_blocked": True}
    finally:
        try:
            if "Authorization" in admin.headers:
                for collection, ids in created.items():
                    response = admin.request("DELETE", f"/items/{collection}", json=ids)
                    response.raise_for_status()
                    response = admin.get(f"/items/{collection}", params={
                        "filter[id][_in]": ",".join(ids), "fields": "id", "limit": len(ids),
                    })
                    response.raise_for_status()
                    if response.json()["data"]:
                        raise RuntimeError("Account retirement CI fixture cleanup incomplete")
        finally:
            await directus.close()
            admin.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main())))
