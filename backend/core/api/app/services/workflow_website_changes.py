"""Encrypted last-good website snapshots and independently recoverable Check events.

Only opaque HMAC generations, run IDs and Vault references are indexed. Snapshot
replacement and event creation use the same workflow-row lock as run deletion.
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
import uuid
from typing import Any

from backend.core.api.app.services.workflow_delivery_history import WorkflowDeliveryHistory, hash_owner_id, keyed_fingerprint
from backend.shared.python_utils.website_text import normalize_page_text, website_read_status, website_text_diff

_REFERENCE = re.compile(r"(?:steps\.([\w-]+)\.|\$nodes\.([\w-]+)\.output\.)([\w.]+)")
MAX_PENDING_EVENTS = 100


def references(value: Any) -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(a or b, field) for a, b, field in _REFERENCE.findall(value)]
    if isinstance(value, dict):
        return [ref for item in value.values() for ref in references(item)]
    if isinstance(value, list):
        return [ref for item in value for ref in references(item)]
    return []


def website_plan(graph: Any) -> dict[str, Any]:
    """Derived from authored references; no public skill flags or new node types."""
    plans = {}
    for read in graph.nodes:
        if (read.config.get("app_id"), read.config.get("skill_id")) != ("web", "read"):
            continue
        consuming_ids = {n.id for n in graph.nodes if n.type.value == "check" and
                         any(source == read.id and field in {"changes", "has_changed"}
                             for source, field in references({"config": n.config, "mapping": n.input_mapping}))}
        consumers = []
        for node in graph.nodes:
            refs = references({"config": node.config, "mapping": node.input_mapping})
            if node.type.value != "check" or not any(n == read.id and f in {"changes", "has_changed"} for n, f in refs):
                continue
            descendants, pending = set(), [e.to_node for e in graph.edges if e.from_node == node.id and e.branch in {"true", "yes"}]
            while pending:
                current = pending.pop()
                if current in descendants or current in consuming_ids:
                    continue
                descendants.add(current)
                pending.extend(e.to_node for e in graph.edges if e.from_node == current)
            targets = [n.id for n in graph.nodes if n.id in descendants and n.type.value == "send_chat_message"]
            consumers.append({"node_id": node.id, "config": node.config, "targets": targets,
                              "destinations": {n.id: n.config for n in graph.nodes if n.id in descendants and
                                               (n.type.value == "send_chat_message" or
                                                (n.config.get("app_id"), n.config.get("skill_id")) == ("ai", "ask"))}})
        if consumers:
            # A chain such as Has changed -> AI relevance consumes one occurrence.
            # Independent Check branches retain independent pending occurrences.
            nested = {}
            for consumer in consumers:
                reachable, pending = set(), [e.to_node for e in graph.edges
                    if e.from_node == consumer["node_id"] and e.branch in {"true", "yes"}]
                while pending:
                    current = pending.pop()
                    if current in reachable:
                        continue
                    reachable.add(current)
                    if any(n.id == current and n.type.value == "send_chat_message" for n in graph.nodes):
                        continue
                    pending.extend(e.to_node for e in graph.edges if e.from_node == current)
                nested[consumer["node_id"]] = reachable
            leaves = [c for c in consumers if not any(other["node_id"] in nested[c["node_id"]]
                                                     for other in consumers if other is not c)]
            for leaf in leaves:
                leaf["gates"] = [{"node_id": c["node_id"], "config": c["config"]} for c in consumers
                                 if leaf["node_id"] in nested[c["node_id"]]]
            consumers = leaves
            # Current-page references deliberately keep the ordinary full-text safety scan.
            full_text = any(n == read.id and f not in {"changes", "has_changed", "source_url", "read_status", "change_status"}
                            for node in graph.nodes if node.id != read.id
                            for n, f in references({"config": node.config, "mapping": node.input_mapping}))
            plans[read.id] = {"consumers": consumers, "full_text": full_text}
    return plans


class WebsiteChangesError(ValueError):
    pass


class WorkflowWebsiteChanges:
    def __init__(self, service: Any, workflow_id: str, user_id: str, run_id: str, version_id: str, vault_key_id: str | None = None):
        self.service, self.repository = service, service.repository
        self.workflow_id, self.user_id, self.run_id, self.version_id = workflow_id, user_id, run_id, version_id
        self.vault_key_id = service._vault_key_id_for_user(user_id, vault_key_id)
        self.history = WorkflowDeliveryHistory(service)
        self.key = self.history.key(workflow_id, user_id, self.vault_key_id)
        if not hasattr(self.repository, "_request") and not hasattr(self.repository, "_website_state"):
            self.repository._website_state = {}

    def fingerprint(self, value: Any) -> str:
        return keyed_fingerprint(self.key, json.dumps(value, sort_keys=True, separators=(",", ":")))

    def _blob(self, payload: Any) -> dict[str, Any]:
        # Existing Vault blob checksums cover plaintext. An encrypted nonce
        # prevents public page text from becoming a checksum lookup oracle.
        encrypted = self.service.payload_cipher.encrypt_json(
            {"version": 1, "nonce": uuid.uuid4().hex, "payload": payload}, self.vault_key_id)
        return {"ref": f"vault://workflows/website_state/{uuid.uuid4()}", "kind": "website_state",
                "hashed_user_id": hash_owner_id(self.user_id), "ciphertext": encrypted["ciphertext"],
                "checksum": encrypted["checksum"], "vault_key_ref": encrypted.get("vault_key_ref"),
                "key_version": encrypted.get("key_version"), "expires_at": None, "created_at": int(time.time())}

    def _load(self, ref: str) -> dict[str, Any]:
        envelope = self.service._load_encrypted_blob(ref, self.vault_key_id)
        if not isinstance(envelope, dict) or envelope.get("version") != 1 or not isinstance(envelope.get("payload"), dict):
            raise WebsiteChangesError("WORKFLOW_WEBSITE_STATE_UNAVAILABLE")
        return envelope["payload"]

    def transaction(self, action: str, **data: Any) -> dict[str, Any]:
        body = {"protocol_version": 1, "action": action, "workflow_id": self.workflow_id,
                "hashed_user_id": hash_owner_id(self.user_id), "run_id": self.run_id,
                "version_id": self.version_id, **data}
        if hasattr(self.repository, "_request"):
            token = os.environ.get("INTERNAL_API_SHARED_TOKEN")
            if not token:
                raise WebsiteChangesError("WORKFLOW_WEBSITE_STATE_UNAVAILABLE")
            try:
                result = self.repository._request("POST", "/workflow-runtime-transaction",
                    headers={"X-Internal-Service-Token": token}, json={"operation": "website_changes", "data": body}).json()["data"]
            except Exception as exc:
                raise WebsiteChangesError("WORKFLOW_WEBSITE_STATE_UNAVAILABLE") from exc
            return result
        with self.repository._delivery_history_lock:
            workflow = self.repository.get_workflow(self.workflow_id, self.user_id)
            run = self.repository.get_run(self.workflow_id, self.run_id, self.user_id)
            if not workflow or workflow.get("status") == "deleted" or not run or run.get("status") in {"deleted", "cancelled", "cancellation_requested", "failed", "completed"}:
                raise WebsiteChangesError("WORKFLOW_WEBSITE_STATE_FENCED")
            if workflow.get("current_version_id") != self.version_id:
                raise WebsiteChangesError("WORKFLOW_WEBSITE_VERSION_CHANGED")
            rows = self.repository._website_state
            scoped = [r for r in rows.values() if r["workflow_id"] == self.workflow_id and r["hashed_user_id"] == hash_owner_id(self.user_id)]
            if action == "read":
                source = next((r for r in scoped if r["id"] == data["source_id"]), None)
                return copy.deepcopy({"source": source, "events": [r for r in scoped if r["source_id"] == data["source_id"] and r["kind"] == "event"], "memberships": self.repository._delivery_history})
            if action == "commit":
                old = rows.get(data["source_id"])
                if (old or {}).get("revision", 0) != data["expected_revision"]:
                    return {"conflict": True}
                snapshot = next(r for r in data["rows"] if r["kind"] == "snapshot")
                if old and snapshot["observed_at"] < int(old.get("observed_at") or 0):
                    raise WebsiteChangesError("WORKFLOW_WEBSITE_STALE_READ")
                remove = [r for r in scoped if r["id"] in data.get("remove_ids", [])]
                writes = data["rows"]
                if old:
                    remove.append(old)
                for row in remove:
                    rows.pop(row["id"], None)
                    self.repository.delete_encrypted_blob(row["encrypted_ref"])
                for blob in data["blobs"]:
                    saved = {**blob, "owner_hash": blob["hashed_user_id"]}
                    self.repository.save_encrypted_blob(saved)
                for row in writes:
                    rows[row["id"]] = copy.deepcopy(row)
                return {"committed": True}
            if action == "update_event":
                old = rows.get(data["event_id"])
                if not old or old not in scoped or old["revision"] != data["expected_revision"]:
                    return {"conflict": True}
                if old.get("processing_run_id") and (old["processing_run_id"] != self.run_id or old["processing_expires_at"] <= int(time.time())):
                    return {"conflict": True}
                if data.get("blob"):
                    blob = data["blob"]
                    self.repository.save_encrypted_blob({**blob, "owner_hash": blob["hashed_user_id"]})
                    self.repository.delete_encrypted_blob(old["encrypted_ref"])
                    old["encrypted_ref"], old["revision"] = blob["ref"], old["revision"] + 1
                else:
                    self.repository.delete_encrypted_blob(old["encrypted_ref"])
                    rows.pop(old["id"])
                return {"updated": True}
            if action == "claim_event":
                event = rows.get(data["event_id"])
                if not event or event not in scoped:
                    return {"claimed": False}
                other = self.repository.runs.get(event.get("processing_run_id")) or {}
                if event.get("processing_run_id") != self.run_id and event.get("processing_expires_at", 0) > int(time.time()) and other.get("status") in {"running", "queued"}:
                    return {"claimed": False}
                event.update(processing_run_id=self.run_id, processing_expires_at=int(time.time()) + 300)
                return {"claimed": True}
            raise WebsiteChangesError("WORKFLOW_WEBSITE_STATE_UNAVAILABLE")

    def project(self, read_id: str, request: dict[str, Any], plan: dict[str, Any], raw: dict[str, Any], observed_at: int | None = None) -> dict[str, Any]:
        from backend.core.api.app.services.workflow_app_skill_adapter import _search_results
        pages = _search_results(raw)
        if not pages:
            raise WebsiteChangesError("WORKFLOW_WEBSITE_READ_FAILED")
        if len(pages) != 1:
            raise WebsiteChangesError("WORKFLOW_WEBSITE_REQUIRES_ONE_PAGE")
        page = pages[0]
        status = website_read_status(page)
        if status != "usable":
            raise WebsiteChangesError("WORKFLOW_WEBSITE_READ_" + status.upper())
        text = normalize_page_text(page["markdown"])
        observed_at = observed_at if observed_at is not None else int(time.time() * 1000)
        source_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.workflow_id}:website:{read_id}"))
        source_request = (request.get("requests") or [request])[0]
        only_main_content = source_request.get("only_main_content")
        generation = self.fingerprint({"url": source_request.get("url"),
            "only_main_content": True if only_main_content is None else only_main_content, "extractor": 1})
        consumers = {self.fingerprint({"source": generation, "node": c["node_id"], "config": c["config"],
                                      "gates": c.get("gates", []), "destinations": c["destinations"]}): c for c in plan["consumers"]}
        for _ in range(3):
            loaded = self.transaction("read", source_id=source_id)
            previous = loaded["source"]
            if previous and observed_at < int(previous.get("observed_at") or 0):
                raise WebsiteChangesError("WORKFLOW_WEBSITE_STALE_READ")
            snapshot = self._load(previous["encrypted_ref"]) if previous else None
            initialized = previous is not None and previous["generation"] == generation
            diff = website_text_diff(snapshot["text"], text) if initialized else ""
            events, remove = {}, []
            for row in sorted(loaded["events"], key=lambda r: (r["created_at"], r["source_revision"], r["id"])):
                if row["generation"] != generation or row["consumer_key"] not in consumers:
                    remove.append(row["id"])
                    continue
                payload = self._load(row["encrypted_ref"])
                delivered = {r["node_id"] for r in loaded["memberships"] if r.get("change_id") == row["id"] and r["status"] == "delivered"}
                if payload["targets"] and set(payload["targets"]) <= delivered:
                    remove.append(row["id"])
                    continue
                payload["reserved_targets"] = [r["node_id"] for r in loaded["memberships"] if r.get("change_id") == row["id"] and r["status"] in {"reserved", "delivered"} and (r.get("expires_at") is None or r["expires_at"] > int(time.time()))]
                event = {**payload, "id": row["id"], "revision": row["revision"]}
                existing = events.get(row["consumer_key"])
                if existing is None or (existing["targets"] and set(existing["targets"]) <= set(existing.get("reserved_targets", []))):
                    events[row["consumer_key"]] = event
            if len(loaded["events"]) - len(remove) + (len(consumers) if diff else 0) > MAX_PENDING_EVENTS:
                raise WebsiteChangesError("WORKFLOW_WEBSITE_PENDING_LIMIT")
            now = int(time.time())
            revision = (previous or {}).get("revision", 0) + 1
            blob = self._blob({"text": text})
            base = {"workflow_id": self.workflow_id, "hashed_user_id": hash_owner_id(self.user_id), "source_id": source_id,
                    "origin_run_id": self.run_id, "generation": generation, "created_at": now, "observed_at": observed_at, "source_revision": revision}
            rows, blobs = [{**base, "id": source_id, "kind": "snapshot", "consumer_key": "", "revision": revision, "encrypted_ref": blob["ref"]}], [blob]
            if diff:
                for consumer_key, consumer in consumers.items():
                    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_id}:{generation}:{self.run_id}:{revision}:{consumer_key}"))
                    payload = {"changes": diff, "source_url": page.get("source_url") or page.get("url"), "node_id": consumer["node_id"], "targets": consumer["targets"], "outputs": {}, "reserved_targets": []}
                    event_blob = self._blob(payload)
                    rows.append({**base, "id": event_id, "kind": "event", "consumer_key": consumer_key, "revision": 1, "encrypted_ref": event_blob["ref"]})
                    blobs.append(event_blob)
                    existing = events.get(consumer_key)
                    if existing is None or (existing["targets"] and set(existing["targets"]) <= set(existing.get("reserved_targets", []))):
                        events[consumer_key] = {**payload, "id": event_id, "revision": 1}
            if self.transaction("commit", source_id=source_id, expected_revision=(previous or {}).get("revision", 0), rows=rows, blobs=blobs, remove_ids=remove).get("conflict"):
                continue
            active = {event["node_id"]: event for event in events.values()}
            available = [event for event in active.values() if not event["targets"] or
                         not set(event["targets"]) <= set(event.get("reserved_targets", []))]
            # Offline deliveries already own this diff. Keep only routing metadata
            # in the read projection so unchanged polling makes no semantic scan.
            for event in active.values():
                if event not in available:
                    event["changes"], event["outputs"] = "", {}
            changes = available[0]["changes"] if available else ""
            output = {"text": "", "source_url": page.get("source_url") or page.get("url") or "", "read_status": status,
                      "has_changed": bool(available), "changes": changes, "change_status": "changed" if available else "delivery_pending" if active else "unchanged" if initialized else "initialized", "_website_events": active}
            if plan["full_text"]:
                output.update(raw)
                output["text"] = text
            return output
        raise WebsiteChangesError("WORKFLOW_WEBSITE_CONCURRENT_READ")

    def save_event_output(self, event: dict[str, Any], node_id: str, output: dict[str, Any], *, discard: bool = False) -> None:
        payload = {k: v for k, v in event.items() if k not in {"id", "revision", "reserved_targets"}}
        payload["reserved_targets"] = []
        payload.setdefault("outputs", {})[node_id] = output
        result = self.transaction("update_event", event_id=event["id"], expected_revision=event["revision"], blob=None if discard else self._blob(payload))
        if result.get("conflict"):
            raise WebsiteChangesError("WORKFLOW_WEBSITE_EVENT_CONFLICT")
        event["outputs"] = payload["outputs"]
        event["revision"] += 1
