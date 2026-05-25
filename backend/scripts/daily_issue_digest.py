#!/usr/bin/env python3
# backend/scripts/daily_issue_digest.py
"""
Generate the daily OpenMates issue digest on demand.

This CLI reuses the Celery task implementation so manual runs and scheduled
runs produce the same JSON, Markdown, OpenCode prompt, and admin email output.
It is safe to run from the host or from inside the API container.
"""

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("OPENMATES_REPO_ROOT", str(REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.core.api.app.tasks.email_tasks.daily_issue_digest_task import (  # noqa: E402
    _async_send_daily_issue_digest,
)


def main() -> int:
    ok = asyncio.run(_async_send_daily_issue_digest())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
