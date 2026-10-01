"""Account-scoped, ciphertext-only persistence for chatless Apps result graphs."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from backend.core.api.app.services.directus.team_methods import TeamPermissionError


class AppsResultConflict(ValueError):
    pass


class AppsWorkspaceResultsService:
    def __init__(self, directus: Any):
        self.directus = directus

    async def _authorize(self, user_id: str, team_id: str | None, *, write: bool) -> tuple[str, str | None]:
        owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
        team_hash = hashlib.sha256(team_id.encode()).hexdigest() if team_id else None
        if team_id:
            roles = {"owner", "admin", "member"} if write else {"owner", "admin", "member", "viewer"}
            await self.directus.team.require_team_role(team_id, user_id, roles)
        return owner_hash, team_hash

    @staticmethod
    def _scope_matches(row: dict[str, Any], owner_hash: str, team_hash: str | None) -> bool:
        return (row.get("hashed_team_id") is None and row.get("hashed_user_id") == owner_hash) if team_hash is None else row.get("hashed_team_id") == team_hash

    async def _find_embed(self, embed_id: str) -> dict[str, Any] | None:
        rows = await self.directus.get_items(
            "embeds", params={"filter[embed_id][_eq]": embed_id, "fields": "*", "limit": 1},
            no_cache=True, admin_required=True, raise_on_error=True,
        )
        return rows[0] if rows else None

    async def index_existing(self, user_id: str, embed_id: str, app_id: str, team_id: str | None) -> str:
        """Project a previously saved chat embed into the bounded app catalog."""
        owner_hash, team_hash = await self._authorize(user_id, team_id, write=True)
        selected = await self._find_embed(embed_id)
        if not selected or not self._scope_matches(selected, owner_hash, team_hash):
            raise AppsResultConflict("Saved embed is unavailable in the selected account")
        root_id = selected.get("parent_embed_id") or embed_id
        root = selected if root_id == embed_id else await self._find_embed(root_id)
        if not root or not self._scope_matches(root, owner_hash, team_hash):
            raise AppsResultConflict("Saved embed root is unavailable in the selected account")
        if root.get("workspace_origin") == "web_apps":
            if root.get("app_id") != app_id:
                raise AppsResultConflict("Saved embed belongs to another app")
            return root_id
        if not root.get("hashed_chat_id"):
            raise AppsResultConflict("Only saved chat embeds can be indexed")
        if root.get("app_id") and root.get("app_id") != app_id:
            raise AppsResultConflict("Saved embed belongs to another app")
        updated = await self.directus.update_item("embeds", root["id"], {
            "app_id": app_id,
            "workspace_origin": "chat",
            "root_embed_id": root_id,
        }, admin_required=True)
        if not updated:
            raise RuntimeError("Could not index saved embed")
        return root_id

    async def index_legacy_batch(
        self, user_id: str, team_id: str | None, items: list[dict[str, str]],
    ) -> dict[str, int]:
        """Project only roots whose originating chat is in the selected account.

        The app/skill IDs come from client-decrypted local metadata; chat scope
        and the relationship between chat and embed are server verified.
        """
        # Viewers may classify an already Team-scoped row. Moving an unscoped
        # legacy row into Team requires the existing Team write role.
        owner_hash, team_hash = await self._authorize(user_id, team_id, write=False)
        indexed = 0
        for item in items:
            root_id, chat_id = item["embed_id"], item["chat_id"]
            root = await self._find_embed(root_id)
            if not root or root.get("parent_embed_id") or root.get("root_embed_id") not in (None, root_id) or root.get("workspace_origin") == "web_apps":
                continue
            if root.get("hashed_chat_id") != hashlib.sha256(chat_id.encode()).hexdigest():
                continue
            chats = await self.directus.get_items(
                "chats", params={"filter[id][_eq]": chat_id,
                                 "fields": "id,hashed_user_id,hashed_team_id", "limit": 1},
                no_cache=True, admin_required=True, raise_on_error=True,
            )
            if not chats:
                continue
            chat = chats[0]
            if chat.get("hashed_team_id") != team_hash:
                continue
            if team_hash is None and (chat.get("hashed_user_id") != owner_hash or root.get("hashed_user_id") != owner_hash):
                continue
            if root.get("hashed_team_id") not in (None, team_hash):
                continue
            moving_to_team = bool(team_hash and root.get("hashed_team_id") is None)
            if moving_to_team:
                try:
                    await self.directus.team.require_team_role(team_id, user_id, {"owner", "admin", "member"})
                except TeamPermissionError:
                    continue
                # A legacy root must belong either to the authoritative chat
                # owner or the active writer who authored it. A hash alone is
                # never evidence that a Personal row was created in this chat.
                if root.get("hashed_user_id") not in (chat.get("hashed_user_id"), owner_hash):
                    continue
            if root.get("app_id") not in (None, item["app_id"]):
                continue
            if root.get("skill_id") not in (None, item["skill_id"]):
                continue
            if root.get("workspace_origin") not in (None, "chat"):
                continue
            child_ids = root.get("embed_ids") or []
            if not isinstance(child_ids, list) or len(child_ids) > 500:
                continue
            team_children: list[dict[str, Any]] = []
            if team_hash and child_ids:
                for start in range(0, len(child_ids), 100):
                    team_children.extend(await self.directus.get_items(
                        "embeds", params={"filter[embed_id][_in]": ",".join(child_ids[start:start + 100]),
                                          "fields": "id,embed_id,hashed_user_id,hashed_chat_id,hashed_team_id,parent_embed_id,root_embed_id", "limit": 100},
                        no_cache=True, admin_required=True, raise_on_error=True,
                    ))
                children_by_id = {child["embed_id"]: child for child in team_children}
                if len(children_by_id) != len(child_ids) or any(
                    child.get("hashed_chat_id") != root["hashed_chat_id"]
                    or child.get("hashed_team_id") not in (None, team_hash)
                    or (child.get("hashed_team_id") is None and child.get("hashed_user_id") != root.get("hashed_user_id"))
                    or (child.get("parent_embed_id") != root_id and child.get("root_embed_id") != root_id)
                    for child in team_children
                ):
                    continue
                if any(child.get("hashed_team_id") is None for child in team_children) and not moving_to_team:
                    try:
                        await self.directus.team.require_team_role(team_id, user_id, {"owner", "admin", "member"})
                    except TeamPermissionError:
                        continue
                children_ready = True
                for child in team_children:
                    if child.get("hashed_team_id") != team_hash:
                        updated_child = await self.directus.update_item("embeds", child["id"], {
                            "hashed_team_id": team_hash, "root_embed_id": root_id,
                        }, admin_required=True)
                        if not updated_child:
                            children_ready = False
                            break
                if not children_ready:
                    continue
            updated = await self.directus.update_item("embeds", root["id"], {
                "app_id": item["app_id"],
                "skill_id": item["skill_id"],
                "hashed_team_id": team_hash,
                "workspace_origin": "chat",
                "root_embed_id": root_id,
            }, admin_required=True)
            if updated:
                indexed += 1
        return {"indexed": indexed, "received": len(items)}

    async def save(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner_hash, team_hash = await self._authorize(user_id, payload.get("team_id"), write=True)
        root_id = payload["root_embed_id"]
        app_id = payload["app_id"]
        skill_id = payload["skill_id"]
        rows = payload["embeds"]
        now = int(time.time())
        root = next(row for row in rows if row["embed_id"] == root_id)
        children = [row for row in rows if row["embed_id"] != root_id]
        existing_root = await self._find_embed(root_id)
        if existing_root and (
            not self._scope_matches(existing_root, owner_hash, team_hash)
            or existing_root.get("hashed_user_id") != owner_hash
            or existing_root.get("app_id") != app_id
            or existing_root.get("skill_id") != skill_id
            or existing_root.get("root_embed_id") != root_id
            or existing_root.get("workspace_origin") != "web_apps"
        ):
            raise AppsResultConflict("Result ID belongs to a different result or account")
        linked_existing: list[str] = []
        for linked_id in payload.get("linked_embed_ids") or []:
            linked = await self._find_embed(linked_id)
            if not linked or not self._scope_matches(linked, owner_hash, team_hash):
                raise AppsResultConflict("Linked embed is unavailable in the submitted account")
            linked_existing.append(linked_id)
        if not existing_root:
            # The unique root row elects the creator before any Team key can
            # be written. A second writer racing on the same UUID must read
            # the winner and fail ownership validation first.
            success, _ = await self.directus.create_item("embeds", {
                "embed_id": root_id,
                "hashed_embed_id": hashlib.sha256(root_id.encode()).hexdigest(),
                "hashed_user_id": owner_hash,
                "hashed_team_id": team_hash,
                "app_id": app_id,
                "skill_id": skill_id,
                "workspace_origin": "web_apps",
                "root_embed_id": root_id,
                "encrypted_type": root["encrypted_type"],
                "encrypted_content": root["encrypted_content"],
                "encrypted_text_preview": root.get("encrypted_text_preview"),
                "status": root.get("status", "finished"),
                "embed_ids": root.get("embed_ids"),
                "parent_embed_id": None,
                "encryption_mode": "client",
                "is_private": True,
                "created_at": now,
                "updated_at": now,
            }, admin_required=True)
            authoritative_root = await self._find_embed(root_id)
            if not authoritative_root or not self._scope_matches(authoritative_root, owner_hash, team_hash) or authoritative_root.get("hashed_user_id") != owner_hash or authoritative_root.get("app_id") != app_id or authoritative_root.get("skill_id") != skill_id or authoritative_root.get("workspace_origin") != "web_apps" or authoritative_root.get("root_embed_id") != root_id:
                raise AppsResultConflict("Result ID belongs to a different result or account")
            if not success and authoritative_root.get("encrypted_content") != root["encrypted_content"]:
                raise AppsResultConflict("Another request created this result ID")
        key_type = "team" if team_hash else "master"
        root_hash = hashlib.sha256(root_id.encode()).hexdigest()
        wrappers = await self.directus.get_items(
            "embed_keys", params={"filter[hashed_embed_id][_eq]": root_hash,
                                  "filter[key_type][_eq]": key_type,
                                  "fields": "id,hashed_user_id,hashed_team_id,encrypted_embed_key", "limit": 20},
            no_cache=True, admin_required=True, raise_on_error=True,
        )
        if any(key.get("hashed_team_id") == team_hash and key.get("hashed_user_id") != owner_hash for key in wrappers):
            raise AppsResultConflict("Result key belongs to another creator")
        wrapper = next((key for key in wrappers if key.get("hashed_team_id") == team_hash and key.get("hashed_user_id") == owner_hash), None)
        if wrapper and wrapper.get("encrypted_embed_key") != payload["encrypted_embed_key"]:
            raise AppsResultConflict("Result key wrapper changed for the same request")
        if not wrapper:
            success, _ = await self.directus.create_item("embed_keys", {
                "hashed_embed_id": root_hash,
                "hashed_user_id": owner_hash,
                "hashed_team_id": team_hash,
                "key_type": key_type,
                "encrypted_embed_key": payload["encrypted_embed_key"],
                "created_at": now,
            }, admin_required=True)
            if not success:
                raise RuntimeError("Could not persist encrypted Apps result key")
        # Retry fills absent children and updates a processing root. The root
        # was reserved before any key wrapper was written.
        for row in [*children, root]:
            embed_id = row["embed_id"]
            existing = await self._find_embed(embed_id)
            if existing:
                if embed_id != root_id and self._scope_matches(existing, owner_hash, team_hash) and existing.get("root_embed_id") != root_id:
                    linked_existing.append(embed_id)
                    continue
                if (not self._scope_matches(existing, owner_hash, team_hash)
                    or existing.get("hashed_user_id") != owner_hash
                    or existing.get("app_id") != app_id
                    or existing.get("root_embed_id") != root_id
                    or existing.get("workspace_origin") != ("web_apps" if embed_id == root_id else None)):
                    raise AppsResultConflict("Result ID belongs to a different result or account")
                if embed_id == root_id and (existing.get("encrypted_content") != row["encrypted_content"] or existing.get("status") != row.get("status", "finished") or existing.get("embed_ids") != row.get("embed_ids")):
                    if existing.get("status") == "finished" and row.get("status") == "processing":
                        raise AppsResultConflict("Completed result cannot return to processing")
                    updated = await self.directus.update_item("embeds", existing["id"], {
                        "encrypted_type": row["encrypted_type"],
                        "encrypted_content": row["encrypted_content"],
                        "encrypted_text_preview": row.get("encrypted_text_preview"),
                        "embed_ids": row.get("embed_ids"),
                        "status": row.get("status", "finished"),
                        "updated_at": now,
                    }, admin_required=True)
                    if not updated:
                        raise RuntimeError("Could not update encrypted Apps result")
                continue
            data = {
                "embed_id": embed_id,
                "hashed_embed_id": hashlib.sha256(embed_id.encode()).hexdigest(),
                "hashed_user_id": owner_hash,
                "hashed_team_id": team_hash,
                "app_id": app_id,
                "skill_id": skill_id,
                "workspace_origin": "web_apps" if embed_id == root_id else None,
                "root_embed_id": root_id,
                "encrypted_type": row["encrypted_type"],
                "encrypted_content": row["encrypted_content"],
                "encrypted_text_preview": row.get("encrypted_text_preview"),
                "status": row.get("status", "finished"),
                "embed_ids": row.get("embed_ids") if embed_id == root_id else None,
                "parent_embed_id": root_id if embed_id != root_id else None,
                "encryption_mode": "client",
                "is_private": True,
                "created_at": now,
                "updated_at": now,
            }
            success, _ = await self.directus.create_item("embeds", data, admin_required=True)
            if not success:
                # A concurrent retry may have won the unique insert race.
                concurrent = await self._find_embed(embed_id)
                if not concurrent or not self._scope_matches(concurrent, owner_hash, team_hash) or concurrent.get("root_embed_id") != root_id or concurrent.get("app_id") != app_id:
                    raise RuntimeError("Could not persist encrypted Apps result")
        return {"root_embed_id": root_id, "linked_embed_ids": list(dict.fromkeys(linked_existing))}

    async def list(self, user_id: str, app_id: str, team_id: str | None, offset: int, limit: int) -> dict[str, Any]:
        owner_hash, team_hash = await self._authorize(user_id, team_id, write=False)
        filters: dict[str, Any] = {
            "filter[app_id][_eq]": app_id,
            "filter[workspace_origin][_in]": "web_apps,chat",
            "filter[hashed_team_id][_eq]" if team_hash else "filter[hashed_team_id][_null]": team_hash if team_hash else True,
        }
        if not team_hash:
            filters["filter[hashed_user_id][_eq]"] = owner_hash
        rows = await self.directus.get_items(
            "embeds", params={**filters, "fields": "embed_id,app_id,skill_id,status,embed_ids,created_at,updated_at,encrypted_type,encrypted_content,encrypted_text_preview,hashed_user_id,hashed_team_id", "sort": "-created_at,-embed_id", "offset": offset, "limit": limit + 1},
            no_cache=True, admin_required=True, raise_on_error=True,
        )
        return {"items": rows[:limit], "has_more": len(rows) > limit, "offset": offset, "limit": limit}

    async def detail(self, user_id: str, root_id: str, team_id: str | None) -> dict[str, Any] | None:
        owner_hash, team_hash = await self._authorize(user_id, team_id, write=False)
        root = await self._find_embed(root_id)
        if not root or not self._scope_matches(root, owner_hash, team_hash) or root.get("workspace_origin") not in {"web_apps", "chat"} or root.get("root_embed_id") != root_id:
            return None
        child_ids = root.get("embed_ids") or []
        if not isinstance(child_ids, list) or len(child_ids) > 500:
            raise RuntimeError("Invalid stored Apps result graph")
        children: list[dict[str, Any]] = []
        if child_ids:
            rows = []
            for start in range(0, len(child_ids), 100):
                page = await self.directus.get_items(
                    "embeds", params={"filter[embed_id][_in]": ",".join(child_ids[start:start + 100]), "fields": "embed_id,encrypted_type,encrypted_content,encrypted_text_preview,status,parent_embed_id,root_embed_id,hashed_user_id,hashed_team_id,app_id,skill_id,created_at,updated_at", "limit": 100},
                    no_cache=True, admin_required=True, raise_on_error=True,
                )
                rows.extend(page)
            by_id = {row["embed_id"]: row for row in rows if self._scope_matches(row, owner_hash, team_hash)}
            if len(by_id) != len(child_ids):
                raise RuntimeError("Incomplete Apps result graph")
            children = [by_id[child_id] for child_id in child_ids if by_id[child_id].get("root_embed_id") == root_id or by_id[child_id].get("parent_embed_id") == root_id]
            linked = [by_id[child_id] for child_id in child_ids if by_id[child_id] not in children]
        root_hash = hashlib.sha256(root_id.encode()).hexdigest()
        wrappers = await self.directus.get_items(
            "embed_keys", params={"filter[hashed_embed_id][_eq]": root_hash, "filter[key_type][_eq]": "team" if team_hash else "master", "fields": "hashed_user_id,hashed_team_id,encrypted_embed_key,key_type,hashed_embed_id,created_at", "limit": 20},
            no_cache=True, admin_required=True, raise_on_error=True,
        )
        wrapper = next((row for row in wrappers if row.get("hashed_team_id") == team_hash and row.get("hashed_user_id") == root.get("hashed_user_id")), None)
        if not wrapper and root.get("workspace_origin") == "chat":
            # Legacy chat embeds may have only the original chat-key wrapper.
            # The client resolves it through the normal synced embed key store.
            return {"root": root, "children": children, "linked": linked if child_ids else [], "key": None}
        if not wrapper:
            raise RuntimeError("Apps result key unavailable")
        return {"root": root, "children": children, "linked": linked if child_ids else [], "key": wrapper}
