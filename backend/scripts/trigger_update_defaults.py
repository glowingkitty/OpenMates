#!/usr/bin/env python3
"""
Manually trigger the daily inspiration defaults selection task.

This dispatches the same Celery task that runs daily at 06:30 UTC via Beat:
  1. Reads all pool entries grouped by language
  2. Scores them: interaction_count / (age_in_hours + 1)
  3. Picks top 3 per language (English fallback if fewer than 3)
  4. Writes results to daily_inspiration_defaults table
  5. Cleans up old defaults
  6. Invalidates the public Redis cache

Use this script when:
- You've manually added entries to the pool and want to see them in defaults
- You need to force a refresh without waiting for the scheduled 06:30 UTC run
- You're testing the full pipeline after deploying pool changes

Usage:
    docker exec -it task-worker python /app/backend/scripts/trigger_update_defaults.py
    docker exec -it task-worker python /app/backend/scripts/trigger_update_defaults.py --wait
    docker exec -it task-worker python /app/backend/scripts/trigger_update_defaults.py --inline

Options:
    --wait      Dispatch the Celery task and poll for completion (default: fire-and-forget)
    --inline    Run the selection logic directly in this process (no Celery dispatch)
"""

import argparse
import asyncio
import json
import logging
import sys

# Add the /app directory to the Python path so backend imports resolve inside Docker
sys.path.insert(0, '/app')

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
script_logger = logging.getLogger('trigger_update_defaults')
script_logger.setLevel(logging.INFO)

for _noisy in ('httpx', 'httpcore'):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def dispatch_celery_task(wait: bool = False) -> None:
    """
    Dispatch the daily_inspiration.select_defaults Celery task.

    Args:
        wait: If True, wait for the task result (blocking). Otherwise fire-and-forget.
    """
    from backend.core.api.app.tasks.celery_config import app as celery_app

    script_logger.info("Dispatching daily_inspiration.select_defaults Celery task...")

    result = celery_app.send_task(
        name="daily_inspiration.select_defaults",
        queue="persistence",
    )

    script_logger.info(f"Task dispatched: task_id={result.id}")

    if wait:
        script_logger.info("Waiting for task completion (this may take 10-30 seconds)...")
        try:
            task_result = result.get(timeout=120)
            script_logger.info(f"Task completed: {json.dumps(task_result, indent=2, default=str)}")
        except Exception as e:
            script_logger.error(f"Task failed or timed out: {e}", exc_info=True)
            sys.exit(1)
    else:
        script_logger.info(
            "Task dispatched (fire-and-forget). Check task-worker logs for results:\n"
            "  docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail=30 task-worker"
        )


async def run_inline() -> None:
    """
    Run the defaults selection logic directly in this process (no Celery).

    Useful for debugging or when the Celery worker is not running.
    """
    # Enable backend logging so we can see the selection progress
    logging.getLogger('backend').setLevel(logging.INFO)

    from backend.core.api.app.services.directus.directus import DirectusService
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.utils.encryption import EncryptionService

    script_logger.info("Running defaults selection inline (no Celery)...")

    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service,
    )

    try:
        from backend.core.api.app.tasks.default_inspiration_tasks import _select_defaults_async

        # Create a minimal mock task object that provides the services
        class MockTask:
            """Minimal mock of BaseServiceTask for inline execution."""
            _directus_service = directus_service
            _cache_service = cache_service

            async def initialize_services(self) -> None:
                """No-op: services are already initialized."""
                pass

        mock_task = MockTask()
        result = await _select_defaults_async(mock_task)

        script_logger.info(f"Defaults selection completed: {json.dumps(result, indent=2, default=str)}")

    finally:
        try:
            await directus_service.close()
        except Exception:
            pass


def main() -> None:
    """Parse CLI arguments and run the appropriate mode."""
    parser = argparse.ArgumentParser(
        description="Manually trigger the daily inspiration defaults selection task",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  docker exec -it task-worker python /app/backend/scripts/trigger_update_defaults.py\n"
            "  docker exec -it task-worker python /app/backend/scripts/trigger_update_defaults.py --wait\n"
            "  docker exec -it task-worker python /app/backend/scripts/trigger_update_defaults.py --inline\n"
        ),
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for the Celery task to complete (blocking)",
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="Run the selection logic directly (no Celery dispatch)",
    )

    args = parser.parse_args()

    if args.inline:
        asyncio.run(run_inline())
    else:
        dispatch_celery_task(wait=args.wait)


if __name__ == "__main__":
    main()
