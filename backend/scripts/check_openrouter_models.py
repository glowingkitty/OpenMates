#!/usr/bin/env python3
# backend/scripts/check_openrouter_models.py
#
# Cron-friendly OpenRouter model watcher for the dev server.
# Fetches the public OpenRouter model catalog, finds models created within a
# recent lookback window, and emails the server owner/admin when new model IDs
# appear. Notification state is kept in test-results so repeated cron runs do
# not resend the same model.

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("OPENMATES_REPO_ROOT", str(REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_LOOKBACK_MINUTES = 60
DEFAULT_FORCE_LATEST_COUNT = 5
REQUEST_TIMEOUT_SECONDS = 30
STATE_DIR = Path(os.getenv("OPENROUTER_MODEL_WATCH_STATE_DIR", REPO_ROOT / "test-results" / "model-watch"))
STATE_FILE = STATE_DIR / "openrouter_notified.json"
LATEST_JSON = STATE_DIR / "openrouter_latest.json"
LATEST_MD = STATE_DIR / "openrouter_latest.md"


logger = logging.getLogger("openrouter_model_watch")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _load_env_file() -> None:
    """Load simple KEY=VALUE entries from .env for cron/manual host runs."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _fetch_openrouter_models() -> list[dict[str, Any]]:
    request = Request(
        OPENROUTER_MODELS_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "OpenMates model watcher/1.0",
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"OpenRouter returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc.reason}") from exc

    models = payload.get("data")
    if not isinstance(models, list):
        raise RuntimeError("OpenRouter response did not contain a data array")
    return [model for model in models if isinstance(model, dict)]


def _model_created_at(model: dict[str, Any]) -> datetime | None:
    created = model.get("created")
    if not isinstance(created, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(created, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"notified_model_ids": {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("State file is invalid JSON; starting with empty state")
        return {"notified_model_ids": {}}
    if not isinstance(data, dict):
        return {"notified_model_ids": {}}
    data.setdefault("notified_model_ids", {})
    if not isinstance(data["notified_model_ids"], dict):
        data["notified_model_ids"] = {}
    return data


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(STATE_FILE)


def _select_recent_unnotified_models(
    models: list[dict[str, Any]],
    lookback_minutes: int,
    notified_model_ids: dict[str, Any],
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=lookback_minutes)
    selected = []
    for model in models:
        model_id = model.get("id")
        if not isinstance(model_id, str) or model_id in notified_model_ids:
            continue
        created_at = _model_created_at(model)
        if created_at and cutoff <= created_at <= now + timedelta(minutes=5):
            selected.append(model)

    return sorted(selected, key=lambda item: item.get("created") or 0, reverse=True)


def _select_latest_models(models: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    return sorted(models, key=lambda item: item.get("created") or 0, reverse=True)[:count]


def _format_usd_per_million(raw_price: Any) -> str:
    try:
        price = float(raw_price)
    except (TypeError, ValueError):
        return "unknown"
    return f"${price * 1_000_000:.3f}/1M"


def _summarize_model(model: dict[str, Any]) -> dict[str, Any]:
    architecture = model.get("architecture") if isinstance(model.get("architecture"), dict) else {}
    pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
    top_provider = model.get("top_provider") if isinstance(model.get("top_provider"), dict) else {}
    created_at = _model_created_at(model)

    supported_parameters = model.get("supported_parameters")
    if not isinstance(supported_parameters, list):
        supported_parameters = []

    input_modalities = architecture.get("input_modalities")
    output_modalities = architecture.get("output_modalities")

    return {
        "id": str(model.get("id") or "unknown"),
        "canonical_slug": str(model.get("canonical_slug") or ""),
        "name": str(model.get("name") or model.get("id") or "unknown"),
        "created_at": created_at.isoformat() if created_at else "unknown",
        "description": str(model.get("description") or "")[:500],
        "context_length": model.get("context_length") or top_provider.get("context_length") or "unknown",
        "max_completion_tokens": top_provider.get("max_completion_tokens") or "unknown",
        "input_modalities": input_modalities if isinstance(input_modalities, list) else [],
        "output_modalities": output_modalities if isinstance(output_modalities, list) else [],
        "prompt_price": _format_usd_per_million(pricing.get("prompt")),
        "completion_price": _format_usd_per_million(pricing.get("completion")),
        "cache_read_price": _format_usd_per_million(pricing.get("input_cache_read")),
        "cache_write_price": _format_usd_per_million(pricing.get("input_cache_write")),
        "supported_parameters": ", ".join(str(param) for param in supported_parameters[:18]),
        "details_url": f"https://openrouter.ai/{model.get('id', '')}",
        "endpoint_details_path": (model.get("links") or {}).get("details") if isinstance(model.get("links"), dict) else "",
    }


def _write_artifacts(models: list[dict[str, Any]], test_mode: bool) -> list[dict[str, Any]]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    summaries = [_summarize_model(model) for model in models]
    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "test_mode": test_mode,
        "models": summaries,
    }
    LATEST_JSON.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    lines = [
        "# OpenRouter Model Watch",
        "",
        f"Generated: {artifact['generated_at']}",
        f"Test mode: {test_mode}",
        "",
    ]
    if not summaries:
        lines.append("No new models found.")
    for model in summaries:
        lines.extend([
            f"## {model['name']}",
            "",
            f"- ID: `{model['id']}`",
            f"- Created: {model['created_at']}",
            f"- Context: {model['context_length']}",
            f"- Max completion: {model['max_completion_tokens']}",
            f"- Modalities: {', '.join(model['input_modalities']) or 'unknown'} -> {', '.join(model['output_modalities']) or 'unknown'}",
            f"- Pricing: prompt {model['prompt_price']}, completion {model['completion_price']}",
            f"- Details: {model['details_url']}",
            "",
            model["description"],
            "",
        ])
    LATEST_MD.write_text("\n".join(lines), encoding="utf-8")
    return summaries


async def _send_email(summaries: list[dict[str, Any]], test_mode: bool, lookback_minutes: int) -> bool:
    recipient = os.getenv("SERVER_OWNER_EMAIL") or os.getenv("ADMIN_NOTIFY_EMAIL")
    if not recipient:
        logger.error("SERVER_OWNER_EMAIL/ADMIN_NOTIFY_EMAIL is not configured")
        return False

    from backend.core.api.app.services.email_template import EmailTemplateService
    from backend.core.api.app.utils.newsletter_utils import hash_email
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets = SecretsManager()
    await secrets.initialize()
    email_service = EmailTemplateService(secrets)
    subject_prefix = "[Test] " if test_mode else ""
    subject = f"{subject_prefix}New OpenRouter models available ({len(summaries)})"
    context_models = []
    for model in summaries:
        escaped_model = {key: escape(str(value)) for key, value in model.items()}
        escaped_model["input_modalities"] = [escape(str(value)) for value in model["input_modalities"]]
        escaped_model["output_modalities"] = [escape(str(value)) for value in model["output_modalities"]]
        context_models.append(escaped_model)

    ok = await email_service.send_email(
        template="openrouter_model_watch",
        recipient_email=recipient,
        subject=subject,
        context={
            "darkmode": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lookback_minutes": lookback_minutes,
            "model_count": len(summaries),
            "models": context_models,
            "artifact_path": str(LATEST_MD),
            "test_mode": test_mode,
        },
        lang="en",
    )
    if ok:
        logger.info("Sent OpenRouter model watch email to %s", hash_email(recipient)[:8])
    return bool(ok)


async def _run(args: argparse.Namespace) -> int:
    _load_env_file()
    models = _fetch_openrouter_models()
    logger.info("Fetched %s OpenRouter models", len(models))

    state = _load_state()
    notified_model_ids = state["notified_model_ids"]
    test_mode = args.test_email

    if test_mode:
        selected = _select_latest_models(models, args.force_latest)
    else:
        selected = _select_recent_unnotified_models(models, args.lookback_minutes, notified_model_ids)

    summaries = _write_artifacts(selected, test_mode=test_mode)
    if not selected:
        logger.info("No new OpenRouter models found in the last %s minutes", args.lookback_minutes)
        return 0

    logger.info("Selected %s model(s) for notification", len(selected))
    if args.dry_run:
        for summary in summaries:
            logger.info("DRY RUN: %s (%s)", summary["id"], summary["created_at"])
        return 0

    sent = await _send_email(summaries, test_mode=test_mode, lookback_minutes=args.lookback_minutes)
    if not sent:
        return 1

    if not test_mode:
        now_iso = datetime.now(timezone.utc).isoformat()
        for model in selected:
            model_id = str(model.get("id"))
            notified_model_ids[model_id] = {
                "created": model.get("created"),
                "notified_at": now_iso,
            }
        state["last_successful_check_at"] = now_iso
        _save_state(state)

    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check OpenRouter for newly added models and notify admins.")
    parser.add_argument("--lookback-minutes", type=int, default=DEFAULT_LOOKBACK_MINUTES)
    parser.add_argument("--dry-run", action="store_true", help="Print selected models without sending email or updating state.")
    parser.add_argument("--test-email", action="store_true", help="Send the latest models as a test email without updating notification state.")
    parser.add_argument("--force-latest", type=int, default=DEFAULT_FORCE_LATEST_COUNT, help="Number of latest models to include with --test-email.")
    return parser.parse_args()


def main() -> int:
    _configure_logging()
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
