"""Private usage overview rollups for Settings, CLI, and SDK clients.

Purpose: aggregate authoritative usage rows into encrypted day/week/month rollups.
Architecture: docs/specs/usage-overview-rollups/spec.yml.
Security: sensitive totals, token counts, models, providers, and regions stay encrypted at rest.
Tests: backend/tests/test_usage_overview_rollups.py and related usage overview tests.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal

from backend.core.api.app.utils.encryption import EncryptionService

Granularity = Literal["daily", "weekly", "monthly"]
ROLLUP_VERSION = 1
OVERVIEW_USAGE_FIELDS = ",".join(
    [
        "id",
        "type",
        "source",
        "created_at",
        "updated_at",
        "app_id",
        "skill_id",
        "tool_inference_iterations",
        "encrypted_model_used",
        "encrypted_credits_costs_total",
        "encrypted_input_tokens",
        "encrypted_output_tokens",
        "encrypted_user_input_tokens",
        "encrypted_system_prompt_tokens",
        "encrypted_server_provider",
        "encrypted_server_region",
    ]
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsagePeriod:
    granularity: Granularity
    period_key: str
    period_start: int
    period_end: int


def _utc_datetime(timestamp: int) -> datetime:
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)


def period_for_timestamp(timestamp: int, granularity: Granularity) -> UsagePeriod:
    dt = _utc_datetime(timestamp)
    if granularity == "daily":
        start = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        key = start.strftime("%Y-%m-%d")
    elif granularity == "weekly":
        iso = dt.isocalendar()
        start = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc) - timedelta(days=iso.weekday - 1)
        end = start + timedelta(days=7)
        key = f"{iso.year}-W{iso.week:02d}"
    elif granularity == "monthly":
        start = datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)
        if dt.month == 12:
            end = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(dt.year, dt.month + 1, 1, tzinfo=timezone.utc)
        key = start.strftime("%Y-%m")
    else:
        raise ValueError(f"Unsupported usage overview granularity: {granularity}")
    return UsagePeriod(granularity=granularity, period_key=key, period_start=int(start.timestamp()), period_end=int(end.timestamp()))


def recent_periods(granularity: Granularity, count: int, now: datetime | None = None) -> list[UsagePeriod]:
    if count < 1:
        raise ValueError("count must be positive")
    cursor = now or datetime.now(timezone.utc)
    periods: list[UsagePeriod] = []
    if granularity == "daily":
        start = datetime(cursor.year, cursor.month, cursor.day, tzinfo=timezone.utc)
        for index in range(count):
            periods.append(period_for_timestamp(int((start - timedelta(days=index)).timestamp()), granularity))
    elif granularity == "weekly":
        iso = cursor.isocalendar()
        start = datetime(cursor.year, cursor.month, cursor.day, tzinfo=timezone.utc) - timedelta(days=iso.weekday - 1)
        for index in range(count):
            periods.append(period_for_timestamp(int((start - timedelta(days=index * 7)).timestamp()), granularity))
    elif granularity == "monthly":
        year = cursor.year
        month = cursor.month
        for _ in range(count):
            periods.append(period_for_timestamp(int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp()), granularity))
            month -= 1
            if month == 0:
                month = 12
                year -= 1
    else:
        raise ValueError(f"Unsupported usage overview granularity: {granularity}")
    return periods


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.strip()))
        except ValueError:
            return 0
    return 0


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _new_totals() -> dict[str, int]:
    return {
        "credits": 0,
        "entries": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "user_input_tokens": 0,
        "system_prompt_tokens": 0,
        "tool_inference_iterations": 0,
        "entries_without_token_data": 0,
    }


def _add_to_bucket(buckets: dict[str, dict[str, Any]], key: str | None, fields: dict[str, Any], entry_totals: dict[str, int]) -> None:
    if not key:
        return
    bucket = buckets.setdefault(key, {**fields, **_new_totals()})
    for field, value in entry_totals.items():
        bucket[field] = _int_value(bucket.get(field)) + value


def aggregate_usage_entries(entries: Iterable[dict[str, Any]], period: UsagePeriod | None = None) -> dict[str, Any]:
    totals = _new_totals()
    token_entries = 0
    by_model: dict[str, dict[str, Any]] = {}
    by_app: dict[str, dict[str, Any]] = {}
    by_skill: dict[str, dict[str, Any]] = {}
    by_source: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}
    by_region: dict[str, dict[str, Any]] = {}
    source_timestamps: list[int] = []

    for entry in entries:
        created_at = _int_value(entry.get("created_at"))
        if period and (created_at < period.period_start or created_at >= period.period_end):
            continue

        credits = _int_value(entry.get("credits"))
        input_tokens = _int_value(entry.get("input_tokens") or entry.get("actual_input_tokens"))
        output_tokens = _int_value(entry.get("output_tokens") or entry.get("actual_output_tokens"))
        user_input_tokens = _int_value(entry.get("user_input_tokens"))
        system_prompt_tokens = _int_value(entry.get("system_prompt_tokens"))
        tool_iterations = _int_value(entry.get("tool_inference_iterations"))
        has_token_data = input_tokens > 0 or output_tokens > 0 or user_input_tokens > 0 or system_prompt_tokens > 0
        if has_token_data:
            token_entries += 1

        entry_totals = {
            "credits": credits,
            "entries": 1,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "user_input_tokens": user_input_tokens,
            "system_prompt_tokens": system_prompt_tokens,
            "tool_inference_iterations": tool_iterations,
            "entries_without_token_data": 0 if has_token_data else 1,
        }
        for field, value in entry_totals.items():
            totals[field] += value
        if created_at > 0:
            source_timestamps.append(created_at)

        app_id = _string_value(entry.get("app_id"))
        skill_id = _string_value(entry.get("skill_id"))
        source = _string_value(entry.get("source")) or "chat"
        model = _string_value(entry.get("model_used"))
        provider = _string_value(entry.get("server_provider"))
        region = _string_value(entry.get("server_region"))
        _add_to_bucket(by_model, model, {"model_used": model}, entry_totals)
        _add_to_bucket(by_app, app_id, {"app_id": app_id}, entry_totals)
        _add_to_bucket(by_skill, f"{app_id}/{skill_id}" if app_id and skill_id else None, {"app_id": app_id, "skill_id": skill_id}, entry_totals)
        _add_to_bucket(by_source, source, {"source": source}, entry_totals)
        _add_to_bucket(by_provider, provider, {"server_provider": provider}, entry_totals)
        _add_to_bucket(by_region, region, {"server_region": region}, entry_totals)

    entries_count = totals["entries"]
    return {
        "version": ROLLUP_VERSION,
        "totals": totals,
        "token_coverage": {
            "entries_with_token_data": token_entries,
            "entries_without_token_data": totals["entries_without_token_data"],
            "coverage_ratio": (token_entries / entries_count) if entries_count else 0,
        },
        "by_model": sorted(by_model.values(), key=lambda item: (-_int_value(item.get("total_tokens")), str(item.get("model_used") or ""))),
        "by_app": sorted(by_app.values(), key=lambda item: (-_int_value(item.get("credits")), str(item.get("app_id") or ""))),
        "by_skill": sorted(by_skill.values(), key=lambda item: (-_int_value(item.get("credits")), str(item.get("app_id") or ""), str(item.get("skill_id") or ""))),
        "by_source": sorted(by_source.values(), key=lambda item: (-_int_value(item.get("credits")), str(item.get("source") or ""))),
        "by_provider": sorted(by_provider.values(), key=lambda item: (-_int_value(item.get("credits")), str(item.get("server_provider") or ""))),
        "by_region": sorted(by_region.values(), key=lambda item: (-_int_value(item.get("credits")), str(item.get("server_region") or ""))),
        "source_min_created_at": min(source_timestamps) if source_timestamps else None,
        "source_max_created_at": max(source_timestamps) if source_timestamps else None,
    }


class UsageOverviewService:
    def __init__(self, directus_service: Any, encryption_service: EncryptionService):
        self.directus_service = directus_service
        self.encryption_service = encryption_service

    async def _encrypt_rollup(self, rollup: dict[str, Any], user_vault_key_id: str) -> str:
        encrypted, _meta = await self.encryption_service.encrypt_with_user_key(
            key_id=user_vault_key_id,
            plaintext=json.dumps(rollup, separators=(",", ":"), sort_keys=True),
        )
        if not encrypted:
            raise ValueError("Failed to encrypt usage rollup")
        return encrypted

    async def _decrypt_rollup(self, encrypted_rollup: str, user_vault_key_id: str) -> dict[str, Any]:
        decrypted = await self.encryption_service.decrypt_with_user_key(encrypted_rollup, user_vault_key_id)
        if not decrypted:
            return aggregate_usage_entries([])
        return json.loads(decrypted)

    async def _decrypt_overview_entries(self, entries: Iterable[dict[str, Any]], user_vault_key_id: str) -> list[dict[str, Any]]:
        encrypted_field_map = {
            "model_used": "encrypted_model_used",
            "credits": "encrypted_credits_costs_total",
            "input_tokens": "encrypted_input_tokens",
            "output_tokens": "encrypted_output_tokens",
            "user_input_tokens": "encrypted_user_input_tokens",
            "system_prompt_tokens": "encrypted_system_prompt_tokens",
            "server_provider": "encrypted_server_provider",
            "server_region": "encrypted_server_region",
        }
        processed_entries: list[dict[str, Any]] = []
        encrypted_values: list[str] = []
        encrypted_refs: list[tuple[int, str]] = []

        for entry in entries:
            processed_entries.append(
                {
                "id": entry.get("id"),
                "type": entry.get("type"),
                "source": entry.get("source", "chat"),
                "created_at": entry.get("created_at"),
                "updated_at": entry.get("updated_at"),
                "app_id": entry.get("app_id"),
                "skill_id": entry.get("skill_id"),
                "tool_inference_iterations": entry.get("tool_inference_iterations"),
                }
            )
            entry_index = len(processed_entries) - 1
            for field, encrypted_field in encrypted_field_map.items():
                encrypted_value = entry.get(encrypted_field)
                if encrypted_value:
                    encrypted_refs.append((entry_index, field))
                    encrypted_values.append(encrypted_value)
            # Tests and local fakes may pass already-decrypted rows.
            for field in ("credits", "input_tokens", "output_tokens", "user_input_tokens", "system_prompt_tokens", "model_used", "server_provider", "server_region"):
                if field not in processed_entries[entry_index] and entry.get(field) is not None:
                    processed_entries[entry_index][field] = entry.get(field)

        if encrypted_values:
            decrypted_values = await self.encryption_service.decrypt_many_with_user_key(encrypted_values, user_vault_key_id)
            for (entry_index, field), result in zip(encrypted_refs, decrypted_values):
                if result in (None, ""):
                    continue
                if field in {"credits", "input_tokens", "output_tokens", "user_input_tokens", "system_prompt_tokens"}:
                    processed_entries[entry_index][field] = _int_value(result)
                else:
                    processed_entries[entry_index][field] = result
        for processed_entry in processed_entries:
            if "credits" not in processed_entry:
                processed_entry["credits"] = 0
        return processed_entries

    async def rebuild_period_rollup(self, user_id_hash: str, user_vault_key_id: str, period: UsagePeriod) -> dict[str, Any]:
        params = {
            "filter": {
                "user_id_hash": {"_eq": user_id_hash},
                "created_at": {"_gte": period.period_start, "_lt": period.period_end},
            },
            "fields": OVERVIEW_USAGE_FIELDS,
            "sort": ["-created_at"],
            "limit": -1,
        }
        raw_entries = await self.directus_service.get_items("usage", params=params, no_cache=True)
        entries = await self._decrypt_overview_entries(raw_entries or [], user_vault_key_id)
        rollup = aggregate_usage_entries(entries, period)
        await self.store_period_rollup(user_id_hash, user_vault_key_id, period, rollup)
        return rollup

    async def rebuild_period_rollups(self, user_id_hash: str, user_vault_key_id: str, periods: list[UsagePeriod], existing_keys: set[str] | None = None) -> dict[str, dict[str, Any]]:
        if not periods:
            return {}
        params = {
            "filter": {
                "user_id_hash": {"_eq": user_id_hash},
                "created_at": {"_gte": periods[-1].period_start, "_lt": periods[0].period_end},
            },
            "fields": OVERVIEW_USAGE_FIELDS,
            "sort": ["-created_at"],
            "limit": -1,
        }
        raw_entries = await self.directus_service.get_items("usage", params=params, no_cache=True)
        entries = await self._decrypt_overview_entries(raw_entries or [], user_vault_key_id)
        existing_keys = existing_keys or set()
        rollups: dict[str, dict[str, Any]] = {}
        for period in periods:
            rollup = aggregate_usage_entries(entries, period)
            rollups[period.period_key] = rollup
            if _int_value((rollup.get("totals") or {}).get("entries")) > 0 or period.period_key in existing_keys:
                await self.store_period_rollup(user_id_hash, user_vault_key_id, period, rollup)
        return rollups

    async def store_period_rollup(self, user_id_hash: str, user_vault_key_id: str, period: UsagePeriod, rollup: dict[str, Any], stale_reason: str | None = None) -> None:
        now = int(datetime.now(timezone.utc).timestamp())
        encrypted_rollup = await self._encrypt_rollup(rollup, user_vault_key_id)
        payload = {
            "user_id_hash": user_id_hash,
            "granularity": period.granularity,
            "period_key": period.period_key,
            "period_start": period.period_start,
            "period_end": period.period_end,
            "rollup_version": ROLLUP_VERSION,
            "encrypted_rollup_json": encrypted_rollup,
            "entry_count": _int_value((rollup.get("totals") or {}).get("entries")),
            "source_min_created_at": rollup.get("source_min_created_at"),
            "source_max_created_at": rollup.get("source_max_created_at"),
            "computed_at": now,
            "stale_reason": stale_reason,
            "updated_at": now,
        }
        existing = await self.directus_service.get_items(
            "usage_period_rollups",
            params={
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    "granularity": {"_eq": period.granularity},
                    "period_key": {"_eq": period.period_key},
                },
                "fields": "id",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if existing:
            await self.directus_service.update_item("usage_period_rollups", existing[0]["id"], payload, admin_required=True)
            return
        payload["created_at"] = now
        await self.directus_service.create_item("usage_period_rollups", payload, admin_required=True)

    async def mark_entry_periods_stale(self, user_id_hash: str, timestamp: int, reason: str = "pending_reconciliation") -> None:
        # Best-effort only: if a rollup exists, mark it stale so readers know to rebuild.
        for granularity in ("daily", "weekly", "monthly"):
            period = period_for_timestamp(timestamp, granularity)  # type: ignore[arg-type]
            existing = await self.directus_service.get_items(
                "usage_period_rollups",
                params={
                    "filter": {
                        "user_id_hash": {"_eq": user_id_hash},
                        "granularity": {"_eq": granularity},
                        "period_key": {"_eq": period.period_key},
                    },
                    "fields": "id",
                    "limit": 1,
                },
                no_cache=True,
                admin_required=True,
            )
            if existing:
                await self.directus_service.update_item("usage_period_rollups", existing[0]["id"], {"stale_reason": reason}, admin_required=True)

    async def get_overview(self, user_id_hash: str, user_vault_key_id: str, granularity: Granularity = "daily", count: int = 30) -> dict[str, Any]:
        periods = recent_periods(granularity, count)
        if not periods:
            return {"granularity": granularity, "periods": [], "totals": _new_totals(), "freshness": {"is_stale": False}}
        params = {
            "filter": {
                "user_id_hash": {"_eq": user_id_hash},
                "granularity": {"_eq": granularity},
                "period_key": {"_in": [period.period_key for period in periods]},
            },
            "fields": "*",
            "limit": -1,
        }
        rows = await self.directus_service.get_items("usage_period_rollups", params=params, no_cache=True, admin_required=True)
        row_by_key = {row.get("period_key"): row for row in rows or []}
        periods_to_rebuild = [
            period
            for period in periods
            if not row_by_key.get(period.period_key)
            or not row_by_key[period.period_key].get("encrypted_rollup_json")
            or row_by_key[period.period_key].get("stale_reason")
        ]
        rebuilt_rollups = await self.rebuild_period_rollups(
            user_id_hash,
            user_vault_key_id,
            periods_to_rebuild,
            existing_keys={period.period_key for period in periods_to_rebuild if row_by_key.get(period.period_key)},
        )
        response_periods: list[dict[str, Any]] = []
        combined_totals = _new_totals()
        combined_with_token_data = 0
        stale_periods: list[str] = []
        now = int(datetime.now(timezone.utc).timestamp())

        for period in periods:
            row = row_by_key.get(period.period_key)
            rollup: dict[str, Any]
            rebuilt = False
            if row and row.get("encrypted_rollup_json") and not row.get("stale_reason"):
                rollup = await self._decrypt_rollup(row["encrypted_rollup_json"], user_vault_key_id)
            else:
                rollup = rebuilt_rollups.get(period.period_key) or aggregate_usage_entries([], period)
                rebuilt = True
                if row and row.get("stale_reason"):
                    stale_periods.append(period.period_key)
            period_payload = {
                "period_key": period.period_key,
                "period_start": period.period_start,
                "period_end": period.period_end,
                "rebuilt": rebuilt,
                **rollup,
            }
            response_periods.append(period_payload)
            rollup_totals = rollup.get("totals") or {}
            for field in combined_totals:
                combined_totals[field] += _int_value(rollup_totals.get(field))
            token_coverage = rollup.get("token_coverage") or {}
            combined_with_token_data += _int_value(token_coverage.get("entries_with_token_data"))

        source_max = max([_int_value((period.get("source_max_created_at"))) for period in response_periods] or [0])
        return {
            "granularity": granularity,
            "periods": response_periods,
            "totals": combined_totals,
            "token_coverage": {
                "entries_with_token_data": combined_with_token_data,
                "entries_without_token_data": combined_totals["entries_without_token_data"],
                "coverage_ratio": (combined_with_token_data / combined_totals["entries"]) if combined_totals["entries"] else 0,
            },
            "range": {"from": periods[-1].period_start, "to": periods[0].period_end},
            "generated_at": now,
            "freshness": {
                "is_stale": bool(stale_periods),
                "stale_periods": stale_periods,
                "source_max_created_at": source_max or None,
                "staleness_seconds": max(now - source_max, 0) if source_max else None,
            },
        }
