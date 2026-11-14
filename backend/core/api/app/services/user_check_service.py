"""Reusable mixed-source Checks: storage, revisions, runs, source results, links.

A Check groups sources of different kinds (e2e, unit, integration, AI evaluation,
human confirmation, ...). Gating metadata is plaintext so the run status can be
aggregated server-side; titles, definitions and result detail stay ciphertext.
"""

# test-file: backend/tests/test_user_checks_api.py

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from backend.core.api.app.services.user_specification_service import hash_id

DETERMINISTIC_KINDS = frozenset({"e2e", "unit", "integration", "static_analysis", "deterministic_audit"})
SOURCE_KINDS = DETERMINISTIC_KINDS | {"ai_evaluation", "human_confirmation"}
SOURCE_ROLES = frozenset({"required", "supporting"})
RESULT_STATUSES = frozenset({"pending", "running", "passed", "failed", "error", "blocked", "skipped", "cancelled", "waived"})
HUMAN_DECISION_STATUS = {"confirmed": "passed", "rejected": "failed", "blocked": "blocked", "waived": "waived"}
TERMINAL_RUN_STATUSES = frozenset({"passed", "failed", "error", "blocked", "cancelled"})

CHECK_FIELDS = (
    "id,check_id,hashed_user_id,hashed_team_id,home_project_hash,linked_project_hashes,status,"
    "current_revision_id,current_revision_number,encrypted_title,encrypted_description,key_wrappers,"
    "created_at,updated_at"
)
REVISION_FIELDS = (
    "revision_id,check_id,revision_number,base_revision_id,definition_hash,requires_deterministic,"
    "sources,encrypted_definition,created_at"
)
RUN_FIELDS = "id,run_id,check_id,check_revision_id,subject_revision,status,created_at,finished_at,encrypted_summary"
RESULT_FIELDS = (
    "id,run_id,check_id,source_binding_id,source_kind,status,test_result_embed_id,ai_score,ai_threshold,"
    "human_decision,confirmer_hash,confirmed_at,encrypted_result,updated_at"
)


class CheckError(ValueError):
    """A safe protocol error, suitable for first-party client presentation."""

    def __init__(self, code: str, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


# ---------------------------------------------------------------- pure logic

def validate_revision_sources(sources: list[dict[str, Any]], requires_deterministic: bool) -> None:
    """Raise CheckError when a revision's sources break the Check contract."""
    seen: set[str] = set()
    for source in sources:
        binding = source.get("source_binding_id")
        if not binding or binding in seen:
            raise CheckError("CHECK_SOURCE_INVALID", 422)
        seen.add(binding)
        if source.get("source_kind") not in SOURCE_KINDS or source.get("role") not in SOURCE_ROLES:
            raise CheckError("CHECK_SOURCE_INVALID", 422)
    required = [s for s in sources if s["role"] == "required"]
    if not required:
        raise CheckError("CHECK_REQUIRED_SOURCE_MISSING", 422)
    if requires_deterministic and not any(s["source_kind"] in DETERMINISTIC_KINDS for s in required):
        raise CheckError("CHECK_DETERMINISTIC_SOURCE_REQUIRED", 422)


def validate_result_kind(sources: list[dict[str, Any]], binding_id: str, source_kind: str) -> dict[str, Any]:
    """Return the binding and require the result kind to equal the binding kind."""
    binding = next((s for s in sources if s.get("source_binding_id") == binding_id), None)
    if binding is None:
        raise CheckError("source_not_found", 404)
    if binding["source_kind"] != source_kind:
        raise CheckError("CHECK_RESULT_MISMATCH", 422)
    return binding


def aggregate_run_status(sources: list[dict[str, Any]], results: list[dict[str, Any]]) -> str:
    """Aggregate over required sources only; supporting results never gate.

    failed > error > blocked > running > waiting_for_confirmation > passed.
    A missing result counts as pending. Cancelled counts as error, skipped as blocked.
    """
    by_binding = {r["source_binding_id"]: r.get("status", "pending") for r in results}
    statuses: list[tuple[str, str]] = []
    for source in sources:
        if source["role"] == "required":
            statuses.append((source["source_kind"], by_binding.get(source["source_binding_id"], "pending")))
    if any(s == "failed" for _, s in statuses):
        return "failed"
    if any(s in {"error", "cancelled"} for _, s in statuses):
        return "error"
    if any(s in {"blocked", "skipped"} for _, s in statuses):
        return "blocked"
    done = {"passed", "waived"}
    if any(s not in done and kind != "human_confirmation" for kind, s in statuses):
        return "running"
    if any(s not in done for _, s in statuses):
        return "waiting_for_confirmation"
    return "passed"


def classify_run_for_gating(run_status: str | None) -> str:
    """Map the latest run status on the current revision to a gating bucket."""
    if run_status is None:
        return "missing_run"
    if run_status == "passed":
        return "passed"
    if run_status in {"queued", "running"}:
        return "running"
    if run_status == "waiting_for_confirmation":
        return "waiting_for_confirmation"
    return "failing"


# ------------------------------------------------------------------- service

def _decode(row: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    result = {key: value for key, value in row.items() if key != "id"}
    for name in names:
        if isinstance(result.get(name), str):
            result[name] = json.loads(result[name])
    return result


class UserCheckService:
    """Authorization and storage for Checks, independent of any UI adapter."""

    def __init__(self, directus: Any) -> None:
        self.directus = directus

    # -- scope and loading
    @staticmethod
    def owner_filters(user_id: str, team_id: str | None) -> dict[str, Any]:
        if team_id:
            return {"filter[hashed_team_id][_eq]": hash_id(team_id), "filter[hashed_user_id][_null]": True}
        return {"filter[hashed_user_id][_eq]": hash_id(user_id), "filter[hashed_team_id][_null]": True}

    async def _rows(self, collection: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await self.directus.get_items(collection, params=params, no_cache=True, raise_on_error=True)
        if not isinstance(rows, list):
            raise CheckError("check_storage_unavailable", 503)
        return rows

    async def _create(self, collection: str, payload: dict[str, Any]) -> dict[str, Any]:
        ok, created = await self.directus.create_item(collection, payload)
        if not ok:
            raise CheckError("check_storage_unavailable", 503)
        return created

    async def _update(self, collection: str, row_id: str, data: dict[str, Any]) -> dict[str, Any]:
        updated = await self.directus._update_item(collection, row_id, data)
        if updated is None:
            raise CheckError("check_storage_unavailable", 503)
        return updated

    async def _get_check_row(self, check_id: str, user_id: str, team_id: str | None) -> dict[str, Any]:
        rows = await self._rows("user_checks", {
            **self.owner_filters(user_id, team_id), "filter[check_id][_eq]": check_id,
            "fields": CHECK_FIELDS, "limit": 1,
        })
        if not rows:
            raise CheckError("check_not_found", 404)
        return rows[0]

    async def _get_revision(self, check_id: str, revision_id: str) -> dict[str, Any]:
        rows = await self._rows("user_check_revisions", {
            "filter[check_id][_eq]": check_id, "filter[revision_id][_eq]": revision_id,
            "fields": REVISION_FIELDS, "limit": 1,
        })
        if not rows:
            raise CheckError("revision_not_found", 404)
        return _decode(rows[0], ("sources",))

    async def _get_run_row(self, run_id: str, user_id: str, team_id: str | None) -> dict[str, Any]:
        rows = await self._rows("user_check_runs", {
            **self.owner_filters(user_id, team_id), "filter[run_id][_eq]": run_id, "fields": RUN_FIELDS, "limit": 1,
        })
        if not rows:
            raise CheckError("run_not_found", 404)
        return rows[0]

    async def _project_hash(self, project_id: str, user_id: str, team_id: str | None) -> str:
        project = await self.directus.project.get_project(project_id, user_id, team_id=team_id)
        if not project:
            raise CheckError("project_not_found", 404)
        return hash_id(project_id)

    @staticmethod
    def _check_view(row: dict[str, Any]) -> dict[str, Any]:
        return _decode(row, ("key_wrappers", "linked_project_hashes"))

    # -- checks
    async def create_check(self, user_id: str, body: dict[str, Any], *, team_id: str | None = None) -> dict[str, Any]:
        """Create a Check together with its first revision."""
        project_hash = await self._project_hash(body["project_id"], user_id, team_id)
        revision = body["revision"]
        validate_revision_sources(revision["sources"], revision["requires_deterministic"])
        if await self._rows("user_checks", {"filter[check_id][_eq]": body["check_id"], "fields": "id", "limit": 1}):
            raise CheckError("check_exists", 409)
        now = int(time.time())
        owner = {"hashed_user_id": None if team_id else hash_id(user_id),
                 "hashed_team_id": hash_id(team_id) if team_id else None}
        head = await self._create("user_checks", {
            **owner, "check_id": body["check_id"], "home_project_hash": project_hash,
            "linked_project_hashes": body.get("linked_project_hashes", []), "status": body.get("status", "draft"),
            "current_revision_id": revision["revision_id"], "current_revision_number": 1,
            "encrypted_title": body["encrypted_title"], "encrypted_description": body.get("encrypted_description"),
            "key_wrappers": body["key_wrappers"], "created_at": now, "updated_at": now,
        })
        rev = await self._create("user_check_revisions", {
            **owner, "check_id": body["check_id"], "revision_number": 1, "base_revision_id": None,
            "revision_id": revision["revision_id"], "definition_hash": revision["definition_hash"],
            "requires_deterministic": revision["requires_deterministic"], "sources": revision["sources"],
            "encrypted_definition": revision["encrypted_definition"], "created_at": now,
        })
        return {"check": self._check_view(head), "revision": _decode(rev, ("sources",))}

    async def list_checks(
        self, user_id: str, *, team_id: str | None = None, project_hash: str | None = None,
        plan_id: str | None = None, limit: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {**self.owner_filters(user_id, team_id), "fields": CHECK_FIELDS,
                                  "sort": "check_id", "limit": limit}
        if project_hash:
            params["filter[home_project_hash][_eq]"] = project_hash
        if plan_id:
            links = await self._rows("user_plan_check_links", {
                **self.owner_filters(user_id, team_id), "filter[plan_id][_eq]": plan_id,
                "fields": "check_id", "limit": 500,
            })
            if not links:
                return {"checks": []}
            params["filter[check_id][_in]"] = ",".join(link["check_id"] for link in links)
        return {"checks": [self._check_view(row) for row in await self._rows("user_checks", params)]}

    async def _latest_run(self, check_id: str, revision_id: str) -> dict[str, Any] | None:
        rows = await self._rows("user_check_runs", {
            "filter[check_id][_eq]": check_id, "filter[check_revision_id][_eq]": revision_id,
            "fields": RUN_FIELDS, "sort": "-created_at", "limit": 1,
        })
        return rows[0] if rows else None

    async def _run_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = await self._rows("user_check_source_results", {
            "filter[run_id][_eq]": run_id, "fields": RESULT_FIELDS, "limit": 200,
        })
        return [{k: v for k, v in row.items() if k != "id"} for row in rows]

    async def get_check(self, check_id: str, user_id: str, *, team_id: str | None = None) -> dict[str, Any]:
        head = await self._get_check_row(check_id, user_id, team_id)
        revision = await self._get_revision(check_id, head["current_revision_id"])
        run = await self._latest_run(check_id, head["current_revision_id"])
        latest = None
        if run:
            latest = {**{k: v for k, v in run.items() if k != "id"}, "source_results": await self._run_results(run["run_id"])}
        return {"check": self._check_view(head), "revision": revision, "latest_run": latest}

    async def list_revisions(self, check_id: str, user_id: str, *, team_id: str | None = None,
                             limit: int = 50) -> dict[str, Any]:
        await self._get_check_row(check_id, user_id, team_id)
        rows = await self._rows("user_check_revisions", {
            "filter[check_id][_eq]": check_id, "fields": REVISION_FIELDS, "sort": "-revision_number", "limit": limit,
        })
        return {"revisions": [_decode(row, ("sources",)) for row in rows]}

    async def revise(self, check_id: str, user_id: str, body: dict[str, Any], *, team_id: str | None = None) -> dict[str, Any]:
        """Publish a new revision; 409 when base_revision_id is not the current head."""
        head = await self._get_check_row(check_id, user_id, team_id)
        validate_revision_sources(body["sources"], body["requires_deterministic"])
        if body["base_revision_id"] != head["current_revision_id"]:
            raise CheckError("revision_conflict", 409)
        number = int(head["current_revision_number"]) + 1
        now = int(time.time())
        rev = await self._create("user_check_revisions", {
            "hashed_user_id": head["hashed_user_id"], "hashed_team_id": head["hashed_team_id"],
            "check_id": check_id, "revision_id": body["revision_id"], "revision_number": number,
            "base_revision_id": body["base_revision_id"], "definition_hash": body["definition_hash"],
            "requires_deterministic": body["requires_deterministic"], "sources": body["sources"],
            "encrypted_definition": body["encrypted_definition"], "created_at": now,
        })
        patch: dict[str, Any] = {"current_revision_id": body["revision_id"], "current_revision_number": number,
                                 "updated_at": now}
        for name in ("encrypted_title", "encrypted_description", "status"):
            if body.get(name) is not None:
                patch[name] = body[name]
        updated = await self._update("user_checks", head["id"], patch)
        return {"check": self._check_view({**head, **patch, **(updated if isinstance(updated, dict) else {})}),
                "revision": _decode(rev, ("sources",))}

    # -- runs and results
    async def start_run(self, check_id: str, user_id: str, body: dict[str, Any], *, team_id: str | None = None) -> dict[str, Any]:
        head = await self._get_check_row(check_id, user_id, team_id)
        if head["status"] == "archived":
            raise CheckError("check_archived", 409)
        run = await self._create("user_check_runs", {
            "hashed_user_id": head["hashed_user_id"], "hashed_team_id": head["hashed_team_id"],
            "run_id": str(uuid.uuid4()), "check_id": check_id, "check_revision_id": head["current_revision_id"],
            "subject_revision": body.get("subject_revision"), "status": "queued",
            "created_at": int(time.time()), "finished_at": None, "encrypted_summary": body.get("encrypted_summary"),
        })
        return {"run": {k: v for k, v in run.items() if k != "id"}}

    async def list_runs(self, check_id: str, user_id: str, *, team_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        await self._get_check_row(check_id, user_id, team_id)
        rows = await self._rows("user_check_runs", {
            "filter[check_id][_eq]": check_id, "fields": RUN_FIELDS, "sort": "-created_at", "limit": limit,
        })
        runs = []
        for row in rows:
            runs.append({**{k: v for k, v in row.items() if k != "id"}, "source_results": await self._run_results(row["run_id"])})
        return {"runs": runs}

    async def _recompute(self, run: dict[str, Any]) -> dict[str, Any]:
        """Recompute the run aggregate from the stored results and persist it."""
        revision = await self._get_revision(run["check_id"], run["check_revision_id"])
        results = await self._run_results(run["run_id"])
        status = aggregate_run_status(revision["sources"], results)
        patch = {"status": status, "finished_at": int(time.time()) if status in TERMINAL_RUN_STATUSES else None}
        await self._update("user_check_runs", run["id"], patch)
        return {**{k: v for k, v in run.items() if k != "id"}, **patch, "source_results": results}

    async def _store_result(self, run: dict[str, Any], binding: dict[str, Any], fields: dict[str, Any]) -> None:
        existing = await self._rows("user_check_source_results", {
            "filter[run_id][_eq]": run["run_id"], "filter[source_binding_id][_eq]": binding["source_binding_id"],
            "fields": "id", "limit": 1,
        })
        data = {**fields, "updated_at": int(time.time())}
        if existing:
            await self._update("user_check_source_results", existing[0]["id"], data)
        else:
            await self._create("user_check_source_results", {
                "run_id": run["run_id"], "check_id": run["check_id"],
                "source_binding_id": binding["source_binding_id"], "source_kind": binding["source_kind"], **data,
            })

    async def record_result(self, run_id: str, binding_id: str, user_id: str, body: dict[str, Any],
                            *, team_id: str | None = None) -> dict[str, Any]:
        """Store one machine source result (not human confirmation) and recompute the run."""
        run = await self._get_run_row(run_id, user_id, team_id)
        if run["status"] == "cancelled":
            raise CheckError("run_closed", 409)
        revision = await self._get_revision(run["check_id"], run["check_revision_id"])
        binding = validate_result_kind(revision["sources"], binding_id, body["source_kind"])
        if body["status"] not in RESULT_STATUSES:
            raise CheckError("CHECK_SOURCE_INVALID", 422)
        if binding["source_kind"] == "human_confirmation" and body["status"] not in {"pending", "running"}:
            raise CheckError("CHECK_HUMAN_CONFIRMATION_REQUIRED", 422)
        await self._store_result(run, binding, {
            "status": body["status"], "test_result_embed_id": body.get("test_result_embed_id"),
            "ai_score": body.get("ai_score"), "ai_threshold": body.get("ai_threshold"),
            "encrypted_result": body.get("encrypted_result"),
        })
        return {"run": await self._recompute(run)}

    async def require_binding(self, run_id: str, binding_id: str, source_kind: str, user_id: str,
                              *, team_id: str | None = None) -> dict[str, Any]:
        """Raise CheckError unless the run's revision has a binding of this kind (and the run is open)."""
        run = await self._get_run_row(run_id, user_id, team_id)
        if run["status"] == "cancelled":
            raise CheckError("run_closed", 409)
        revision = await self._get_revision(run["check_id"], run["check_revision_id"])
        return validate_result_kind(revision["sources"], binding_id, source_kind)

    async def confirm(self, run_id: str, binding_id: str, user_id: str, body: dict[str, Any],
                      *, team_id: str | None = None) -> dict[str, Any]:
        """Record the human decision for a human_confirmation source and recompute the run."""
        run = await self._get_run_row(run_id, user_id, team_id)
        if run["status"] == "cancelled":
            raise CheckError("run_closed", 409)
        revision = await self._get_revision(run["check_id"], run["check_revision_id"])
        binding = validate_result_kind(revision["sources"], binding_id, "human_confirmation")
        await self._store_result(run, binding, {
            "status": HUMAN_DECISION_STATUS[body["decision"]], "human_decision": body["decision"],
            "confirmer_hash": hash_id(user_id), "confirmed_at": int(time.time()),
            "encrypted_result": body.get("encrypted_result"),
        })
        return {"run": await self._recompute(run)}

    # -- plan links
    async def link_plan(self, check_id: str, user_id: str, body: dict[str, Any], *, team_id: str | None = None) -> dict[str, Any]:
        head = await self._get_check_row(check_id, user_id, team_id)
        existing = await self._rows("user_plan_check_links", {
            **self.owner_filters(user_id, team_id), "filter[check_id][_eq]": check_id,
            "filter[plan_id][_eq]": body["plan_id"], "fields": "id", "limit": 1,
        })
        data = {"required": body["required"], "criterion_id": body.get("criterion_id")}
        if existing:
            await self._update("user_plan_check_links", existing[0]["id"], data)
        else:
            await self._create("user_plan_check_links", {
                "hashed_user_id": head["hashed_user_id"], "hashed_team_id": head["hashed_team_id"],
                "plan_id": body["plan_id"], "check_id": check_id, "created_at": int(time.time()), **data,
            })
        return {"link": {"plan_id": body["plan_id"], "check_id": check_id, **data}}

    async def unlink_plan(self, check_id: str, plan_id: str, user_id: str, *, team_id: str | None = None) -> dict[str, Any]:
        await self._get_check_row(check_id, user_id, team_id)
        rows = await self._rows("user_plan_check_links", {
            **self.owner_filters(user_id, team_id), "filter[check_id][_eq]": check_id,
            "filter[plan_id][_eq]": plan_id, "fields": "id", "limit": 1,
        })
        if not rows:
            raise CheckError("link_not_found", 404)
        if not await self.directus._delete_item("user_plan_check_links", rows[0]["id"]):
            raise CheckError("check_storage_unavailable", 503)
        return {"deleted": True}

    async def plan_required_checks_state(self, plan_ids: list[str], *, user_id: str | None = None,
                                         team_id: str | None = None) -> dict[str, int]:
        """Count required Checks of the Plans by gating bucket on their current revision."""
        state = {"required_total": 0, "passed": 0, "failing": 0, "running": 0,
                 "waiting_for_confirmation": 0, "missing_run": 0}
        if not plan_ids:
            return state
        params: dict[str, Any] = {"filter[plan_id][_in]": ",".join(plan_ids), "filter[required][_eq]": True,
                                  "fields": "check_id", "limit": 500}
        if user_id:
            params.update(self.owner_filters(user_id, team_id))
        links = await self._rows("user_plan_check_links", params)
        for check_id in sorted({link["check_id"] for link in links}):
            heads = await self._rows("user_checks", {
                "filter[check_id][_eq]": check_id, "fields": "check_id,current_revision_id,status", "limit": 1,
            })
            if not heads or heads[0].get("status") == "archived":
                continue
            run = await self._latest_run(check_id, heads[0]["current_revision_id"])
            state["required_total"] += 1
            state[classify_run_for_gating(run["status"] if run else None)] += 1
        return state
