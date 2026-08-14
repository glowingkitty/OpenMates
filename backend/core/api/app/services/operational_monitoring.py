"""
Privacy-safe operational snapshot collection and compact report rendering.

The service accepts aggregate operational metadata only. It validates the
24-hour window and recursively rejects private fields before rendering or
serializing reports for operator email and Discord delivery.
"""

from __future__ import annotations

import json
import logging
import math
import asyncio
from io import BytesIO
from datetime import datetime, timedelta
from hashlib import sha256
from html import escape
from typing import Any, Iterable, Mapping

import httpx


VALID_ENVIRONMENTS = {"development", "production", "self_host"}
VALID_DELIVERY_CHANNELS = {"email", "discord"}
VALID_DELIVERY_STATES = {"queued", "accepted", "failed", "unavailable"}
FORBIDDEN_PRIVATE_FIELD_FRAGMENTS = {
    "api_key", "cipher", "content", "destination", "email", "encrypted",
    "exception", "file", "payment", "prompt", "recipient", "secret", "stack",
    "token", "trace", "user", "webhook",
}
RESOURCE_KEYS = {"cpu_percent", "memory_percent", "disk_used_percent", "disk_free_bytes"}
ACTIVITY_KEYS = {"chats", "messages", "embeds", "usage_entries"}
PROCESSING_KEYS = {"started", "completed", "failed", "stuck"}
FRESHNESS_KEYS = {"resource_metrics", "application_metrics", "report_scheduler"}
BILLING_KEYS = {"status", "started", "completed", "failed"}
ISSUE_KEYS = {"fingerprint", "severity", "active", "count", "last_seen"}
SELF_HOST_FORBIDDEN_TERMS = ("billing", "payment", "stripe", "invoice", "subscription", "purchase")
SEVERITY_ORDER = {"critical": 3, "warning": 2, "digest": 1}
REPORT_WIDTH = 1200
REPORT_HEIGHT = 680
MAX_GRAPH_POINTS = 96
MAX_ISSUES = 3
DELIVERY_MAX_ATTEMPTS = 3
DELIVERY_RETRY_BASE_SECONDS = 0.25
logger = logging.getLogger(__name__)


def _validate_environment(environment: str) -> None:
    if environment not in VALID_ENVIRONMENTS:
        raise ValueError(f"Unsupported operational environment: {environment}")


def resolve_operational_environment(deployment_mode: str, server_environment: str) -> str:
    normalized_mode = deployment_mode.strip().lower()
    if normalized_mode == "self_host":
        return "self_host"
    if normalized_mode != "official_cloud":
        raise RuntimeError("operational_environment_not_configured")
    return "production" if server_environment.strip().lower() == "production" else "development"


def resolve_operational_discord_webhook(environment: str, environ: Mapping[str, str]) -> str | None:
    _validate_environment(environment)
    if environment == "production":
        return environ.get("DISCORD_WEBHOOK_OPERATIONAL_MONITORING_PRODUCTION") or environ.get("DISCORD_WEBHOOK_PROD_SMOKE")
    if environment == "development":
        return (
            environ.get("DISCORD_WEBHOOK_OPERATIONAL_MONITORING_DEVELOPMENT")
            or environ.get("DISCORD_WEBHOOK_DEV_NIGHTLY")
            or environ.get("DISCORD_WEBHOOK_DEV_SMOKE")
        )
    return environ.get("DISCORD_WEBHOOK_OPERATIONAL_MONITORING_SELF_HOST") or environ.get("OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL")


def _validate_private_fields(value: Any, path: str = "snapshot") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in FORBIDDEN_PRIVATE_FIELD_FRAGMENTS):
                raise ValueError(f"forbidden private field at {path}.{key}")
            _validate_private_fields(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_private_fields(item, f"{path}[{index}]")


def _parse_timestamp(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    return 0.0


def rank_prioritized_issues(issues: Iterable[dict[str, Any]], limit: int = MAX_ISSUES) -> list[dict[str, Any]]:
    safe_issues = [dict(issue) for issue in issues]
    _validate_private_fields(safe_issues, "issues")
    for issue in safe_issues:
        unexpected = set(issue) - ISSUE_KEYS
        if unexpected:
            raise ValueError(f"unsupported operational issue fields: {sorted(unexpected)}")
    safe_issues.sort(
        key=lambda issue: (
            SEVERITY_ORDER.get(str(issue.get("severity", "digest")), 0),
            bool(issue.get("active")),
            int(issue.get("count", 0) or 0),
            _parse_timestamp(issue.get("last_seen")),
        ),
        reverse=True,
    )
    return safe_issues[: max(0, min(limit, MAX_ISSUES))]


def build_operational_snapshot(
    *,
    environment: str,
    window_start: datetime,
    window_end: datetime,
    resource_series: dict[str, list[list[float]]],
    activity_counts: dict[str, int],
    processing_transactions: dict[str, int],
    telemetry_freshness: dict[str, str],
    issues: Iterable[dict[str, Any]],
    billing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_environment(environment)
    if abs((window_end - window_start) - timedelta(hours=24)) > timedelta(seconds=1):
        raise ValueError("Operational snapshots require an exact 24-hour window")
    if environment == "self_host" and billing is not None:
        raise ValueError("self-host operational snapshots cannot include billing")
    schemas = (
        ("resource_series", resource_series, RESOURCE_KEYS),
        ("activity_counts", activity_counts, ACTIVITY_KEYS),
        ("processing_transactions", processing_transactions, PROCESSING_KEYS),
        ("telemetry_freshness", telemetry_freshness, FRESHNESS_KEYS),
    )
    for label, values, allowed in schemas:
        unexpected = set(values) - allowed
        if unexpected:
            raise ValueError(f"unsupported {label} fields: {sorted(unexpected)}")
    if billing is not None and set(billing) - BILLING_KEYS:
        raise ValueError(f"unsupported billing fields: {sorted(set(billing) - BILLING_KEYS)}")

    snapshot: dict[str, Any] = {
        "environment": environment,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_hours": 24,
        "generated_at": window_end.isoformat(),
        "telemetry_freshness": dict(telemetry_freshness),
        "resource_series": resource_series,
        "activity_counts": {key: int(value or 0) for key, value in activity_counts.items()},
        "processing_transactions": {key: int(value or 0) for key, value in processing_transactions.items()},
        "prioritized_issues": rank_prioritized_issues(issues),
    }
    if environment != "self_host":
        snapshot["billing"] = billing or {"status": "unavailable", "started": 0, "completed": 0, "failed": 0}
    _validate_private_fields(snapshot)
    if environment == "self_host":
        serialized = json.dumps(snapshot, sort_keys=True).lower()
        if any(term in serialized for term in SELF_HOST_FORBIDDEN_TERMS):
            raise ValueError("self-host operational snapshot contains a forbidden cloud-only term")
    return snapshot


def serialize_operational_snapshot(snapshot: dict[str, Any]) -> str:
    _validate_private_fields(snapshot)
    serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    if snapshot.get("environment") == "self_host" and any(term in serialized.lower() for term in SELF_HOST_FORBIDDEN_TERMS):
        raise ValueError("self-host operational snapshot contains a forbidden cloud-only term")
    return serialized


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    return sha256(serialize_operational_snapshot(snapshot).encode("utf-8")).hexdigest()


def report_subject(environment: str, *, test: bool = False) -> str:
    _validate_environment(environment)
    labels = {"development": "DEV", "production": "PROD", "self_host": "SELF-HOST"}
    test_label = " TEST" if test else ""
    return f"[OpenMates {labels[environment]}{test_label}] Daily operational report"


def _sample_points(points: list[list[float]]) -> list[list[float]]:
    if len(points) <= MAX_GRAPH_POINTS:
        return points
    step = math.ceil(len(points) / MAX_GRAPH_POINTS)
    return points[::step][:MAX_GRAPH_POINTS]


def _series_path(points: list[list[float]], *, left: float, top: float, width: float, height: float) -> str:
    finite = [(float(ts), float(value)) for ts, value in _sample_points(points) if math.isfinite(float(value))]
    if not finite:
        return ""
    min_ts, max_ts = finite[0][0], finite[-1][0]
    span = max(max_ts - min_ts, 1.0)
    commands = []
    for index, (timestamp, value) in enumerate(finite):
        x = left + ((timestamp - min_ts) / span) * width
        y = top + height - (max(0.0, min(100.0, value)) / 100.0) * height
        commands.append(f"{'M' if index == 0 else 'L'} {x:.1f} {y:.1f}")
    return " ".join(commands)


def _latest(series: dict[str, list[list[float]]], key: str) -> float | None:
    points = series.get(key) or []
    if not points:
        return None
    value = float(points[-1][1])
    return value if math.isfinite(value) else None


def _format_metric(value: float | None, suffix: str = "%") -> str:
    return "no data" if value is None else f"{value:.1f}{suffix}"


def _format_bytes(value: float | None) -> str:
    return "no data" if value is None else f"{value / (1024 ** 3):.1f} GB"


def render_operational_report_svg(snapshot: dict[str, Any]) -> str:
    _validate_private_fields(snapshot)
    environment = str(snapshot["environment"])
    series = snapshot["resource_series"]
    graph = {key: _series_path(series.get(key, []), left=72, top=128, width=1056, height=210) for key in (
        "cpu_percent", "memory_percent", "disk_used_percent"
    )}
    activity = snapshot["activity_counts"]
    processing = snapshot["processing_transactions"]
    issues = snapshot["prioritized_issues"]
    issue_lines = []
    for index, issue in enumerate(issues):
        fingerprint = escape(str(issue.get("fingerprint", "unknown"))[:90])
        issue_lines.append(
            f'<text x="72" y="{568 + index * 24}" fill="#e7e7ec" font-size="16">'
            f'{escape(str(issue.get("severity", "digest")).upper())}: {fingerprint} ({int(issue.get("count", 0) or 0)}x)</text>'
        )
    if not issue_lines:
        issue_lines.append('<text x="72" y="568" fill="#70d69b" font-size="16">No prioritized issues.</text>')

    cloud_only = ""
    if environment != "self_host":
        cloud = snapshot.get("billing") or {}
        cloud_only = (
            f'<text x="792" y="462" fill="#aeb0ba" font-size="14">Cloud billing</text>'
            f'<text x="792" y="488" fill="#ffffff" font-size="20">{escape(str(cloud.get("status", "unavailable")))}</text>'
            f'<text x="792" y="514" fill="#aeb0ba" font-size="14">Started {int(cloud.get("started", 0) or 0)} · Completed {int(cloud.get("completed", 0) or 0)} · Failed {int(cloud.get("failed", 0) or 0)}</text>'
        )

    paths = "".join(
        f'<path d="{graph[key]}" fill="none" stroke="{color}" stroke-width="3" />'
        for key, color in (("cpu_percent", "#6aa9ff"), ("memory_percent", "#b68cff"), ("disk_used_percent", "#ffb86b"))
        if graph[key]
    )
    title = escape(report_subject(environment).replace("Daily operational report", "24-hour operational snapshot"))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{REPORT_WIDTH}" height="{REPORT_HEIGHT}" viewBox="0 0 {REPORT_WIDTH} {REPORT_HEIGHT}">'
        '<rect width="1200" height="680" rx="24" fill="#11131a" />'
        f'<text x="72" y="62" fill="#ffffff" font-size="28" font-family="Arial" font-weight="700">{title}</text>'
        f'<text x="72" y="92" fill="#aeb0ba" font-size="14" font-family="Arial">{escape(snapshot["window_start"])} to {escape(snapshot["window_end"])}</text>'
        '<rect x="72" y="128" width="1056" height="210" rx="12" fill="#191c26" />'
        '<path d="M 72 233 L 1128 233" stroke="#303440" stroke-width="1" />'
        + paths
        + '<text x="82" y="154" fill="#6aa9ff" font-size="14">CPU</text>'
        + '<text x="142" y="154" fill="#b68cff" font-size="14">Memory</text>'
        + '<text x="226" y="154" fill="#ffb86b" font-size="14">Disk</text>'
        + f'<text x="72" y="382" fill="#ffffff" font-size="20">CPU {_format_metric(_latest(series, "cpu_percent"))} · Memory {_format_metric(_latest(series, "memory_percent"))} · Disk {_format_metric(_latest(series, "disk_used_percent"))} · Free {_format_bytes(_latest(series, "disk_free_bytes"))}</text>'
        + '<text x="72" y="426" fill="#aeb0ba" font-size="14">Activity</text>'
        + f'<text x="72" y="454" fill="#ffffff" font-size="20">Chats {activity.get("chats", 0)} · Messages {activity.get("messages", 0)} · Embeds {activity.get("embeds", 0)} · Usage {activity.get("usage_entries", 0)}</text>'
        + '<text x="72" y="492" fill="#aeb0ba" font-size="14">Processing</text>'
        + f'<text x="72" y="520" fill="#ffffff" font-size="18">Started {processing.get("started", 0)} · Completed {processing.get("completed", 0)} · Failed {processing.get("failed", 0)} · Stuck {processing.get("stuck", 0)}</text>'
        + cloud_only
        + '<text x="72" y="548" fill="#aeb0ba" font-size="14">Prioritized issues</text>'
        + "".join(issue_lines)
        + '</svg>'
    )


def render_operational_report_png(snapshot: dict[str, Any]) -> bytes:
    try:
        import cairosvg

        return cairosvg.svg2png(bytestring=render_operational_report_svg(snapshot).encode("utf-8"), output_width=REPORT_WIDTH, output_height=REPORT_HEIGHT)
    except ModuleNotFoundError:
        # Repository-only test environments omit CairoSVG; production images
        # include it. Pillow preserves deterministic PNG verification locally.
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (REPORT_WIDTH, REPORT_HEIGHT), "#11131a")
        draw = ImageDraw.Draw(image)
        draw.text((72, 48), report_subject(str(snapshot["environment"])), fill="white")
        draw.text((72, 82), f'{snapshot["window_start"]} to {snapshot["window_end"]}', fill="#aeb0ba")
        draw.rectangle((72, 128, 1128, 338), fill="#191c26")
        colors = {"cpu_percent": "#6aa9ff", "memory_percent": "#b68cff", "disk_used_percent": "#ffb86b"}
        for key, color in colors.items():
            points = _sample_points(snapshot["resource_series"].get(key, []))
            if len(points) < 2:
                continue
            first, last = float(points[0][0]), float(points[-1][0])
            span = max(last - first, 1.0)
            coordinates = [
                (72 + ((float(timestamp) - first) / span) * 1056, 338 - max(0.0, min(100.0, float(value))) * 2.1)
                for timestamp, value in points
                if math.isfinite(float(value))
            ]
            if len(coordinates) >= 2:
                draw.line(coordinates, fill=color, width=3)
        draw.text((72, 370), "CPU  Memory  Disk", fill="white")
        draw.text((72, 420), f'Activity: {snapshot["activity_counts"]}', fill="white")
        draw.text((72, 460), f'Processing: {snapshot["processing_transactions"]}', fill="white")
        draw.text((72, 520), f'Issues: {len(snapshot["prioritized_issues"])}', fill="#aeb0ba")
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()


def create_delivery_receipt(
    *,
    environment: str,
    report_id: str,
    report_sha256: str,
    channel: str,
    state: str,
    attempt_count: int,
    occurred_at: datetime,
    sanitized_failure_class: str | None = None,
) -> dict[str, Any]:
    _validate_environment(environment)
    if channel not in VALID_DELIVERY_CHANNELS:
        raise ValueError(f"Unsupported delivery channel: {channel}")
    if state not in VALID_DELIVERY_STATES:
        raise ValueError(f"Unsupported delivery state: {state}")
    return {
        "environment": environment,
        "report_id": report_id,
        "report_sha256": report_sha256,
        "channel": channel,
        "state": state,
        "attempt_count": int(attempt_count),
        "occurred_at": occurred_at.isoformat(),
        "sanitized_failure_class": sanitized_failure_class,
    }


def summarize_delivery_state(receipts: list[dict[str, Any]]) -> str:
    states = {receipt.get("state") for receipt in receipts}
    if states == {"accepted"}:
        return "accepted"
    if "accepted" in states:
        return "partial_failure"
    if states:
        return "failed"
    return "unavailable"


async def deliver_with_retries(send, *, failure_class: str) -> tuple[bool, int, str | None]:
    for attempt in range(1, DELIVERY_MAX_ATTEMPTS + 1):
        try:
            if await send():
                return True, attempt, None
        except Exception:
            pass
        if attempt < DELIVERY_MAX_ATTEMPTS:
            await asyncio.sleep(DELIVERY_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
    return False, DELIVERY_MAX_ATTEMPTS, failure_class


async def query_prometheus_range(
    query: str,
    *,
    start: datetime,
    end: datetime,
    step_seconds: int = 900,
    base_url: str = "http://prometheus:9090",
) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/api/v1/query_range",
            params={"query": query, "start": start.timestamp(), "end": end.timestamp(), "step": step_seconds},
        )
        response.raise_for_status()
    results = response.json().get("data", {}).get("result", [])
    if not results:
        return []
    points: dict[float, list[float]] = {}
    for result in results:
        for timestamp, raw_value in result.get("values", []):
            value = float(raw_value)
            if math.isfinite(value):
                points.setdefault(float(timestamp), []).append(value)
    return [[timestamp, sum(values) / len(values)] for timestamp, values in sorted(points.items())]


async def collect_resource_series(
    *,
    start: datetime,
    end: datetime,
    prometheus_url: str = "http://prometheus:9090",
) -> dict[str, list[list[float]]]:
    queries = {
        "cpu_percent": '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
        "memory_percent": '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100',
        "disk_used_percent": '(1 - (node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs"} / node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs"})) * 100',
        "disk_free_bytes": 'node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs"}',
    }
    results = await asyncio.gather(*(
        query_prometheus_range(query, start=start, end=end, base_url=prometheus_url)
        for query in queries.values()
    ), return_exceptions=True)
    failed_queries = [key for key, result in zip(queries, results, strict=True) if isinstance(result, Exception)]
    if failed_queries:
        logger.warning("Operational resource collection failed for metrics: %s", ",".join(failed_queries))
        raise RuntimeError("resource_metrics_unavailable")
    return {key: result for key, result in zip(queries, results, strict=True)}


async def _directus_count(
    directus_service: Any,
    collection: str,
    *,
    timestamp_field: str,
    start: datetime,
    end: datetime,
    timestamp_format: str = "iso",
    extra_filter: dict[str, Any] | None = None,
) -> int:
    if timestamp_format == "iso":
        start_value: str | int = start.isoformat()
        end_value: str | int = end.isoformat()
    elif timestamp_format == "unix_seconds":
        start_value = int(start.timestamp())
        end_value = int(end.timestamp())
    else:
        raise ValueError(f"unsupported timestamp format: {timestamp_format}")
    filters: list[dict[str, Any]] = [
        {timestamp_field: {"_gte": start_value}},
        {timestamp_field: {"_lt": end_value}},
    ]
    if extra_filter:
        filters.append(extra_filter)
    token = await directus_service.ensure_auth_token(admin_required=True)
    response = await directus_service._make_api_request(
        "GET",
        f"{directus_service.base_url}/items/{collection}",
        params={"limit": 1, "meta": "filter_count", "filter": json.dumps({"_and": filters})},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return int(response.json().get("meta", {}).get("filter_count", 0) or 0)


async def collect_activity_and_transactions(
    directus_service: Any,
    *,
    environment: str,
    start: datetime,
    end: datetime,
) -> tuple[dict[str, int], dict[str, int], dict[str, Any] | None]:
    _validate_environment(environment)
    activity_requests = [
        _directus_count(directus_service, "chats", timestamp_field="created_at", start=start, end=end),
        _directus_count(directus_service, "messages", timestamp_field="created_at", start=start, end=end),
        _directus_count(directus_service, "embeds", timestamp_field="created_at", start=start, end=end),
        _directus_count(
            directus_service,
            "usage",
            timestamp_field="created_at",
            timestamp_format="unix_seconds",
            start=start,
            end=end,
        ),
    ]
    chats, messages, embeds, usage_entries = await asyncio.gather(*activity_requests)
    processing_started, processing_completed, processing_failed, processing_stuck = await asyncio.gather(
        _directus_count(
            directus_service,
            "chat_completion_recovery_jobs",
            timestamp_field="created_at",
            start=start,
            end=end,
        ),
        _directus_count(
            directus_service,
            "chat_completion_recovery_jobs",
            timestamp_field="completed_at",
            start=start,
            end=end,
        ),
        _directus_count(
            directus_service,
            "chat_completion_recovery_jobs",
            timestamp_field="invalidated_at",
            start=start,
            end=end,
        ),
        _directus_count(
            directus_service,
            "chat_completion_recovery_jobs",
            timestamp_field="created_at",
            start=start,
            end=end,
            extra_filter={"_and": [
                {"state": {"_nin": ["completed", "invalidated"]}},
                {"created_at": {"_lt": (end - timedelta(minutes=15)).isoformat()}},
            ]},
        ),
    )
    activity = {"chats": chats, "messages": messages, "embeds": embeds, "usage_entries": usage_entries}
    processing = {
        "started": processing_started,
        "completed": processing_completed,
        "failed": processing_failed,
        "stuck": processing_stuck,
    }

    cloud = None
    if environment != "self_host":
        started, completed, billing_failed = await asyncio.gather(
            _directus_count(directus_service, "billing_charge_identities", timestamp_field="created_at", start=start, end=end),
            _directus_count(directus_service, "billing_charge_identities", timestamp_field="committed_at", start=start, end=end),
            _directus_count(
                directus_service,
                "billing_charge_identities",
                timestamp_field="created_at",
                start=start,
                end=end,
                extra_filter={"state": {"_eq": "failed"}},
            ),
        )
        cloud = {
            "status": "healthy" if billing_failed == 0 else "degraded",
            "started": started,
            "completed": completed,
            "failed": billing_failed,
        }
    return activity, processing, cloud


async def collect_active_alerts(prometheus_url: str = "http://prometheus:9090") -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{prometheus_url.rstrip('/')}/api/v1/alerts")
        response.raise_for_status()
    alerts = []
    for alert in response.json().get("data", {}).get("alerts", []):
        if alert.get("state") not in {"firing", "pending"}:
            continue
        labels = alert.get("labels") or {}
        alert_name = str(labels.get("alertname", "UnknownAlert"))[:80]
        service = str(labels.get("name") or labels.get("job") or "server")[:60]
        alerts.append({
            "fingerprint": f"{alert_name}:{service}",
            "severity": labels.get("severity", "warning"),
            "active": alert.get("state") == "firing",
            "count": 1,
            "last_seen": alert.get("activeAt") or datetime.now().astimezone().isoformat(),
        })
    return alerts
