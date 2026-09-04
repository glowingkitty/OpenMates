"""Authenticated private API for canonical engineering test records.

Routes expose only the seven allowlisted test-control record types. Every write
is authorized by operation class, and bulk imports are committed atomically by
the PostgreSQL repository with no Directus or product-database fallback.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.engineering_control_plane.auth import Identity, request_identity, require_scope
from backend.engineering_control_plane.config import Settings
from backend.engineering_control_plane.coordination import DispatchSpec, SessionEventType
from backend.engineering_control_plane.coordination_repository import (
    CoordinationConflict,
    PostgresCoordinationRepository,
)
from backend.engineering_control_plane.records import (
    PostgresRecordRepository,
    SCHEMAS,
    UnknownRecordType,
)


router = APIRouter(prefix="/v1")
COORDINATION_COLLECTIONS = frozenset({"test_claims", "test_debug_campaigns", "test_debug_groups"})
MAX_UNRENEWED_LEASE_TTL_SECONDS = 30 * 60


class RecordWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: dict[str, Any]


class BulkImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collections: dict[str, list[dict[str, Any]]]
    replace_current_state: bool = False


class LeaseAcquireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_key: str = Field(min_length=1, max_length=255)
    owner_key: str = Field(min_length=1, max_length=512)
    resources: list[str] = Field(min_length=1, max_length=64)
    ttl_seconds: int = Field(default=900, ge=30, le=86_400)
    mode: str = Field(default="exclusive", pattern="^(shared|exclusive)$")


class LeaseTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_owner_key: str = Field(min_length=1, max_length=512)
    new_owner_key: str = Field(min_length=1, max_length=512)


class RuntimeOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(min_length=1, max_length=255)
    operation_type: str = Field(min_length=1, max_length=80)
    resources: list[str] = Field(min_length=1, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeOperationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=512)
    commit: str = Field(min_length=1, max_length=255)
    tests: list[str] = Field(min_length=1, max_length=10_000)
    profile: str = Field(min_length=1, max_length=128)
    account: str = Field(min_length=1, max_length=255)
    mocks: dict[str, str] = Field(default_factory=dict)
    required_services: list[str] = Field(default_factory=list, max_length=64)


class DispatchCanaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1, max_length=255)
    healthy: bool
    failure_class: str | None = Field(default=None, max_length=255)


class DispatchUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=80)
    reason: str | None = Field(default=None, max_length=512)


class EventPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=80)
    target_type: str = Field(min_length=1, max_length=80)
    target_key: str = Field(min_length=1, max_length=512)
    subject_key: str = Field(min_length=1, max_length=512)
    payload: dict[str, Any] = Field(default_factory=dict)


class EventAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: str = Field(min_length=1, max_length=512)


def get_repository() -> PostgresRecordRepository:
    return PostgresRecordRepository(Settings.from_environment().database_url)


def get_coordination_repository() -> PostgresCoordinationRepository:
    return PostgresCoordinationRepository(Settings.from_environment().database_url)


def _scope_for_collection(collection: str) -> str:
    return "coordinate" if collection in COORDINATION_COLLECTIONS else "ingest"


@router.get("/records/{collection}")
def list_records(
    collection: str,
    filters_json: str = Query(default="{}", max_length=16_384),
    sort: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=-1, ge=-1, le=100_000),
    identity: Identity = Depends(request_identity),
    repository: PostgresRecordRepository = Depends(get_repository),
) -> dict[str, Any]:
    require_scope(identity, "read")
    try:
        filters = json.loads(filters_json)
        if not isinstance(filters, dict):
            raise ValueError("filters must be an object")
        records = repository.list_records(collection, filters=filters, sort=sort, limit=limit)
    except (json.JSONDecodeError, ValueError, UnknownRecordType) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"records": records}


@router.put("/records/{collection}")
def upsert_record(
    collection: str,
    request: RecordWriteRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresRecordRepository = Depends(get_repository),
) -> dict[str, Any]:
    require_scope(identity, _scope_for_collection(collection))
    try:
        return {"record": repository.upsert_record(collection, request.record)}
    except (ValueError, UnknownRecordType) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import")
def import_records(
    request: BulkImportRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresRecordRepository = Depends(get_repository),
) -> dict[str, Any]:
    for collection in request.collections:
        if collection not in SCHEMAS:
            raise HTTPException(status_code=400, detail=f"unsupported record type: {collection}")
        require_scope(identity, _scope_for_collection(collection))
    try:
        counts = repository.import_records(
            request.collections,
            replace_current_state=request.replace_current_state,
        )
    except (ValueError, UnknownRecordType) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"counts": counts}


@router.post("/coordination/leases")
def acquire_lease(
    request: LeaseAcquireRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    try:
        lease = repository.acquire_lease(
            lease_key=request.lease_key,
            owner_key=request.owner_key,
            resources=request.resources,
            # Leases are renewable heartbeats, not reservations for an entire
            # agent turn. Accept older clients' longer requests but cap the
            # stored expiry so a dead owner cannot block the queue for hours.
            ttl_seconds=min(request.ttl_seconds, MAX_UNRENEWED_LEASE_TTL_SECONDS),
            mode=request.mode,
        )
    except CoordinationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"lease": lease}


@router.get("/coordination/leases/{lease_key}")
def get_lease(
    lease_key: str,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    lease = repository.get_lease(lease_key)
    if lease is None:
        raise HTTPException(status_code=404, detail=f"lease not found: {lease_key}")
    return {"lease": lease}


@router.delete("/coordination/leases/{lease_key}")
def release_lease(
    lease_key: str,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, bool]:
    require_scope(identity, "coordinate")
    return {"released": repository.release_lease(lease_key)}


@router.post("/coordination/leases/{lease_key}/transfer")
def transfer_lease(
    lease_key: str,
    request: LeaseTransferRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    try:
        lease = repository.transfer_lease(
            lease_key,
            expected_owner_key=request.expected_owner_key,
            new_owner_key=request.new_owner_key,
        )
    except CoordinationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"lease": lease}


@router.get("/coordination/leases/{lease_key}/owned")
def lease_owned(
    lease_key: str,
    owner_key: str = Query(min_length=1, max_length=512),
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, bool]:
    require_scope(identity, "coordinate")
    return {"owned": repository.lease_owned_by(lease_key, owner_key)}


@router.post("/coordination/runtime-operations")
def request_runtime_operation(
    request: RuntimeOperationRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    try:
        operation = repository.request_runtime_operation(
            operation_key=request.operation_key,
            requested_by=identity.identity_key,
            operation_type=request.operation_type,
            resources=request.resources,
            metadata=request.metadata,
        )
    except CoordinationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"operation": operation}


@router.patch("/coordination/runtime-operations/{operation_key}")
def update_runtime_operation(
    operation_key: str,
    request: RuntimeOperationUpdateRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    try:
        operation = repository.update_runtime_operation(
            operation_key,
            status=request.status,
            metadata_updates=request.metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"runtime operation not found: {operation_key}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"operation": operation}


@router.get("/coordination/runtime-operations")
def list_runtime_operations(
    operation_type: str | None = Query(default=None, max_length=80),
    status: list[str] | None = Query(default=None, max_length=80),
    limit: int = Query(default=20, ge=1, le=100),
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    return {
        "operations": repository.list_runtime_operations(
            operation_type=operation_type,
            statuses=status or None,
            limit=limit,
        )
    }


@router.get("/coordination/runtime-operations/{operation_key}/blocking-leases")
def blocking_leases(
    operation_key: str,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    try:
        return repository.runtime_operation_blockers(operation_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"runtime operation not found: {operation_key}") from exc


@router.get("/coordination/runtime-epoch")
def runtime_epoch(
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, int]:
    require_scope(identity, "read")
    return {"runtime_epoch": repository.runtime_epoch()}


@router.post("/coordination/dispatches")
def request_dispatch(
    request: DispatchRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    try:
        spec = DispatchSpec.create(
            repository=request.repository,
            commit=request.commit,
            tests=request.tests,
            profile=request.profile,
            account=request.account,
            mocks=request.mocks,
            required_services=request.required_services,
            runtime_epoch=repository.runtime_epoch(),
        )
        dispatch, reused = repository.request_dispatch(spec, requested_by=identity.identity_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"dispatch": dispatch, "reused": reused}


@router.put("/coordination/dispatches/{dispatch_key}/canaries")
def record_dispatch_canary(
    dispatch_key: str,
    request: DispatchCanaryRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    try:
        dispatch = repository.record_canary(
            dispatch_key,
            request.service,
            healthy=request.healthy,
            failure_class=request.failure_class,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"dispatch not found: {dispatch_key}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"dispatch": dispatch}


@router.patch("/coordination/dispatches/{dispatch_key}")
def update_dispatch(
    dispatch_key: str,
    request: DispatchUpdateRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    try:
        dispatch = repository.update_dispatch(dispatch_key, status=request.status, reason=request.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"dispatch not found: {dispatch_key}") from exc
    except CoordinationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"dispatch": dispatch}


@router.post("/coordination/events")
def publish_event(
    request: EventPublishRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "coordinate")
    try:
        event = repository.publish_event(
            event_type=SessionEventType(request.event_type),
            target_type=request.target_type,
            target_key=request.target_key,
            subject_key=request.subject_key,
            payload=request.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"event": event}


@router.get("/coordination/events")
def read_events(
    target_type: str = Query(min_length=1, max_length=80),
    target_key: str = Query(min_length=1, max_length=512),
    after_cursor: int = Query(default=0, ge=0),
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, Any]:
    require_scope(identity, "read")
    return {"events": repository.read_events(target_type, target_key, after_cursor=after_cursor)}


@router.post("/coordination/events/{event_key}/acknowledgements")
def acknowledge_event(
    event_key: str,
    request: EventAcknowledgeRequest,
    identity: Identity = Depends(request_identity),
    repository: PostgresCoordinationRepository = Depends(get_coordination_repository),
) -> dict[str, bool]:
    require_scope(identity, "coordinate")
    try:
        acknowledged = repository.acknowledge_event(event_key, recipient=request.recipient)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"event not found: {event_key}") from exc
    return {"acknowledged": acknowledged}
