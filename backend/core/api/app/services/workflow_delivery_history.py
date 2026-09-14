"""Run-owned, keyed delivery membership. No result IDs, URLs or payloads are indexed.

The per-workflow random HMAC key is stored through the existing Vault blob cipher.
Production transitions share the Directus workflow-row transaction lock with delivery
acknowledgement and deletion; in-memory state exists only for injected test repositories.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

def hash_owner_id(user_id: str) -> str:
    return "user_sha256:" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()


class WorkflowDeliveryHistoryError(ValueError):
    pass


def canonical_result_identity(item: dict[str, Any]) -> str:
    """Prefer provider identity; never infer identity from mutable title/price text."""
    provider = str(item.get("provider") or item.get("source") or "")
    identifier = item.get("source_id") or item.get("id") or item.get("event_id") or item.get("listing_id") or item.get("article_id")
    if identifier is not None and str(identifier).strip():
        return f"v1:id:{provider}:{identifier}"
    url = item.get("canonical_url") or item.get("url") or item.get("link") or item.get("source_url")
    if not isinstance(url, str) or not url.strip():
        raise WorkflowDeliveryHistoryError("Selected result has no stable provider ID or URL")
    parts = urlsplit(url.strip())
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise WorkflowDeliveryHistoryError("Selected result URL is invalid")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "msclkid"}]
    canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(sorted(query)), ""))
    return f"v1:url:{canonical}"


def keyed_fingerprint(key: bytes, identity: str) -> str:
    return hmac.new(key, identity.encode("utf-8"), hashlib.sha256).hexdigest()


def runtime_transaction(repository: Any, **data: Any) -> dict[str, Any]:
    token = os.environ.get("INTERNAL_API_SHARED_TOKEN")
    if not token:
        raise WorkflowDeliveryHistoryError("Workflow delivery transaction is unavailable")
    try:
        response = repository._request(
            "POST", "/workflow-runtime-transaction",
        headers={"X-Internal-Service-Token": token},
            json={"operation": "delivery_history", "data": {"protocol_version": 1, **data}},
        )
    except Exception as exc:
        raise WorkflowDeliveryHistoryError("Workflow delivery transaction was rejected or unavailable") from exc
    result = response.json().get("data")
    if not isinstance(result, dict):
        raise WorkflowDeliveryHistoryError("Invalid workflow delivery transaction response")
    return result


class WorkflowDeliveryHistory:
    def __init__(self, workflow_service: Any) -> None:
        self.service = workflow_service
        self.repository = workflow_service.repository
        if not hasattr(self.repository, "_request"):
            if not hasattr(self.repository, "_delivery_history_lock"):
                self.repository._delivery_history_lock = threading.RLock()
                self.repository._delivery_history = []
                self.repository._delivery_keys = {}

    def key(self, workflow_id: str, user_id: str, vault_key_id: str | None = None) -> bytes:
        owner = hash_owner_id(user_id)
        vault_key_id = self.service._vault_key_id_for_user(user_id, vault_key_id)
        workflow = self.repository.get_workflow(workflow_id, user_id)
        if not workflow:
            raise PermissionError("Workflow not found")
        if hasattr(self.repository, "_request"):
            result = runtime_transaction(self.repository, action="key", workflow_id=workflow_id, hashed_user_id=owner)
            ref = result.get("encrypted_key_ref")
            if not ref:
                blob = self.service._save_encrypted_blob(user_id, "delivery_identity_key", {"key": secrets.token_hex(32)}, vault_key_id=vault_key_id)
                result = runtime_transaction(self.repository, action="key", workflow_id=workflow_id, hashed_user_id=owner, encrypted_key_ref=blob["ref"])
                ref = result["encrypted_key_ref"]
                if ref != blob["ref"]:
                    self.repository.delete_encrypted_blob(blob["ref"])
        else:
            with self.repository._delivery_history_lock:
                ref = self.repository._delivery_keys.get(workflow_id)
                if not ref:
                    blob = self.service._save_encrypted_blob(user_id, "delivery_identity_key", {"key": secrets.token_hex(32)}, vault_key_id=vault_key_id)
                    ref = self.repository._delivery_keys[workflow_id] = blob["ref"]
        return bytes.fromhex(self.service._load_encrypted_blob(ref, vault_key_id)["key"])

    def reserve(self, *, user_id: str, workflow_id: str, run_id: str, node_id: str,
                delivery_id: str, destination_hash: str, candidates: list[dict[str, Any]], expires_at: int) -> list[int]:
        data = dict(action="reserve", hashed_user_id=hash_owner_id(user_id), workflow_id=workflow_id,
                    run_id=run_id, node_id=node_id, delivery_id=delivery_id,
                    destination_hash=destination_hash, candidates=candidates, expires_at=expires_at)
        if hasattr(self.repository, "_request"):
            return runtime_transaction(self.repository, **data)["selected_indexes"]
        with self.repository._delivery_history_lock:
            run = self.repository.get_run(workflow_id, run_id, user_id)
            if not run or run.get("status") == "deleted":
                raise WorkflowDeliveryHistoryError("Run is unavailable for delivery")
            rows = self.repository._delivery_history
            own = [r for r in rows if r["delivery_id"] == delivery_id]
            if own:
                return [r["index"] for r in own]
            selected, seen = [], set()
            for candidate in candidates:
                fingerprint = candidate["fingerprint"]
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                known = any(r["workflow_id"] == workflow_id and r["destination_hash"] == destination_hash
                            and r["fingerprint"] == fingerprint and r["status"] in {"reserved", "delivered"} for r in rows)
                if candidate.get("only_new") and known:
                    continue
                selected.append(candidate["index"])
                rows.append({**data, **candidate, "status": "reserved", "candidates": None})
            return selected

    def release(self, delivery_id: str, workflow_id: str, user_id: str) -> None:
        if hasattr(self.repository, "_request"):
            runtime_transaction(self.repository, action="release", delivery_id=delivery_id, workflow_id=workflow_id, hashed_user_id=hash_owner_id(user_id))
            return
        with self.repository._delivery_history_lock:
            self.repository._delivery_history[:] = [r for r in self.repository._delivery_history
                if r["delivery_id"] != delivery_id or r["status"] == "delivered"]

    def acknowledge_in_memory(self, delivery: Any) -> None:
        """Used only by an injected delivery repository; production ACK is one SQL transaction."""
        with self.repository._delivery_history_lock:
            run = self.repository.runs.get(delivery.run_id)
            if not run or run.get("status") == "deleted":
                raise WorkflowDeliveryHistoryError("Run was deleted")
            for row in self.repository._delivery_history:
                if row["delivery_id"] == delivery.delivery_id:
                    row["status"] = "delivered"
