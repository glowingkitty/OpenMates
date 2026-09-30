"""Disposable CI probe for the real Directus workflow authoring transaction.

Run only inside the isolated API container. It uses synthetic owner hashes,
workflow ids, and ciphertext markers; no account or Vault key is involved.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from copy import deepcopy
from typing import Any

import httpx


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _check(response: httpx.Response, status: int) -> dict[str, Any]:
    if response.status_code != status:
        raise AssertionError(f"Directus transaction returned HTTP {response.status_code}; expected {status}")
    if status == 200:
        value = response.json().get("data")
        if not isinstance(value, dict):
            raise AssertionError("Directus transaction omitted response data")
        return value
    return {}


def _mutation(owner: str, operation_id: str, workflow_id: str, kind: str, now: int) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()), "operation_id": operation_id, "session_id": None,
        "hashed_user_id": owner, "type": kind, "target_type": "workflow", "target_id": workflow_id,
        "encrypted_before_ref": None, "encrypted_before_checksum": None,
        "encrypted_after_ref": None, "encrypted_after_checksum": None,
        "undone_at": None, "created_at": now,
    }


def _fixture(owner: str, now: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    operation_id = f"ci-authoring:{uuid.uuid4()}"
    writes = []
    blobs = []
    mutations = []
    outcomes = []
    for _ in range(2):
        workflow_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        title_ref = f"vault://workflows/workflow_title/{uuid.uuid4()}"
        graph_ref = f"vault://workflows/workflow_graph/{uuid.uuid4()}"
        checksum = _digest(workflow_id)
        record = {
            "id": workflow_id, "owner_hash": owner,
            "encrypted_title_ref": title_ref, "encrypted_title_checksum": checksum,
            "encrypted_graph_ref": graph_ref, "encrypted_graph_checksum": checksum,
            "status": "disabled", "enabled": False, "lifecycle": "persisted", "source": "system",
            "version": 1, "current_version_id": version_id, "versions": [{
                "id": version_id, "version_number": 1, "encrypted_graph_ref": graph_ref,
                "encrypted_graph_checksum": checksum, "created_at": now,
            }], "created_at": now, "updated_at": now,
        }
        writes.append({"workflow_id": workflow_id, "expected_version": None, "record": record, "trigger": None})
        for ref, kind in ((title_ref, "workflow_title"), (graph_ref, "workflow_graph")):
            blobs.append({
                "ref": ref, "owner_hash": owner, "kind": kind,
                "ciphertext": "vault:v1:synthetic-ci-ciphertext", "checksum": checksum,
                "vault_key_ref": None, "key_version": None, "created_at": now,
            })
        mutations.append(_mutation(owner, operation_id, workflow_id, "create_workflow", now))
        outcomes.append({"workflow_id": workflow_id, "version": 1, "after_ref": None})
    return ({
        "owner_hash": owner, "operation_id": operation_id, "request_hash": _digest(operation_id),
        "session_id": None, "writes": writes, "blobs": blobs, "mutations": mutations,
        "outcomes": outcomes,
    }, [item["record"] for item in writes])


def _rows(admin: httpx.Client, table: str, owner: str) -> list[dict[str, Any]]:
    response = admin.get(f"/items/{table}", params={"filter[hashed_user_id][_eq]": owner, "limit": -1})
    response.raise_for_status()
    rows = response.json().get("data")
    if not isinstance(rows, list):
        raise AssertionError(f"Directus omitted {table} fixture rows")
    return rows


def main() -> None:
    if os.getenv("CI") != "true" or os.getenv("OPENMATES_CI_ISOLATED") != "1":
        raise RuntimeError("Workflow transaction probe requires a disposable isolated CI stack")
    cms_url = os.environ["CMS_URL"].rstrip("/")
    if cms_url != "http://cms:8055":
        raise RuntimeError("Workflow transaction probe requires the isolated CMS service")
    owner = "user_sha256:" + hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    now = int(time.time())
    original, records = _fixture(owner, now)
    private = httpx.Client(base_url=cms_url, headers={
        "X-Internal-Service-Token": os.environ["INTERNAL_API_SHARED_TOKEN"],
    }, timeout=30)
    admin = httpx.Client(base_url=cms_url, timeout=30)
    login = admin.post("/auth/login", json={
        "email": os.environ["DATABASE_ADMIN_EMAIL"],
        "password": os.environ["DATABASE_ADMIN_PASSWORD"],
        "mode": "json",
    })
    login.raise_for_status()
    admin.headers["Authorization"] = f"Bearer {login.json()['data']['access_token']}"
    tables = ("workflow_input_mutations", "workflow_authoring_operations", "workflow_versions",
              "workflow_encrypted_blobs", "workflows")
    try:
        created = _check(private.post("/workflow-authoring-transaction/", json=original), 200)
        assert len(created["outcomes"]) == 2
        assert len(_rows(admin, "workflows", owner)) == 2
        assert len(_rows(admin, "workflow_versions", owner)) == 2
        assert len(_rows(admin, "workflow_encrypted_blobs", owner)) == 4
        assert len(_rows(admin, "workflow_input_mutations", owner)) == 2
        assert len(_rows(admin, "workflow_authoring_operations", owner)) == 1

        stale_id = f"ci-authoring-stale:{uuid.uuid4()}"
        stale_writes = []
        stale_mutations = []
        stale_outcomes = []
        for index, record in enumerate(records):
            expected = 1 if index == 0 else 2
            candidate = deepcopy(record)
            candidate["version"] = expected + 1
            candidate["updated_at"] = now + 1
            stale_writes.append({"workflow_id": record["id"], "expected_version": expected,
                                 "record": candidate, "trigger": None})
            stale_mutations.append(_mutation(owner, stale_id, record["id"], "update_workflow", now))
            stale_outcomes.append({"workflow_id": record["id"], "version": expected + 1, "after_ref": None})
        stale = {"owner_hash": owner, "operation_id": stale_id, "request_hash": _digest(stale_id),
                 "session_id": None, "writes": stale_writes, "blobs": [],
                 "mutations": stale_mutations, "outcomes": stale_outcomes}
        _check(private.post("/workflow-authoring-transaction/", json=stale), 409)
        assert sorted(int(row["version"]) for row in _rows(admin, "workflows", owner)) == [1, 1]
        assert len(_rows(admin, "workflow_input_mutations", owner)) == 2
        assert len(_rows(admin, "workflow_authoring_operations", owner)) == 1

        replay = _check(private.post("/workflow-authoring-transaction/", json=original), 200)
        assert replay["outcomes"] == created["outcomes"]
        assert len(_rows(admin, "workflow_versions", owner)) == 2
        assert len(_rows(admin, "workflow_authoring_operations", owner)) == 1

        changed = deepcopy(records[1])
        changed["kept_at"] = now + 2
        changed["updated_at"] = now + 2
        metadata = {"owner_hash": owner, "workflow_id": changed["id"],
                    "expected_version": 1, "record": changed}
        _check(private.post("/workflow-authoring-transaction/legacy-head", json=metadata), 200)
        undo_id = f"ci-authoring-undo:{uuid.uuid4()}"
        inverse = []
        for record in records:
            candidate = deepcopy(record)
            candidate.update({"version": 2, "status": "deleted", "enabled": False, "updated_at": now + 3})
            inverse.append({"workflow_id": record["id"], "expected_version": 1,
                            "record": candidate, "trigger": None})
        undo = {"owner_hash": owner, "operation_id": undo_id, "request_hash": _digest(undo_id),
                "session_id": None, "undo_of_operation_id": original["operation_id"],
                "writes": inverse, "blobs": [],
                "mutations": [_mutation(owner, undo_id, item["id"], "delete_workflow", now) for item in records],
                "outcomes": [{"workflow_id": item["id"], "version": 2, "after_ref": None} for item in records]}
        _check(private.post("/workflow-authoring-transaction/", json=undo), 409)
        assert sorted(int(row["version"]) for row in _rows(admin, "workflows", owner)) == [1, 2]
        assert all(row["undone_at"] is None for row in _rows(admin, "workflow_input_mutations", owner))
        assert len(_rows(admin, "workflow_authoring_operations", owner)) == 1
        print("real-db workflow authoring transaction passed")
    finally:
        try:
            for table in tables:
                for row in _rows(admin, table, owner):
                    response = admin.delete(f"/items/{table}/{row['id']}")
                    response.raise_for_status()
        finally:
            private.close()
            admin.close()


if __name__ == "__main__":
    main()
