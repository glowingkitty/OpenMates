"""
backend/shared/python_utils/notification_spool.py

Hands every Discord notification the backend sends to the host's private
notification log. Each notification becomes one small JSON file in the spool
directory (``NOTIFICATION_SPOOL_DIR``); the host-side ``scripts/notification_log.py``
ingests, redacts and stores them. Without the variable (production, self-host)
nothing is written. Spooling never raises into the sender.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

SPOOL_ENV = "NOTIFICATION_SPOOL_DIR"


def spool_notification(
    source: str,
    text: str,
    *,
    embeds: Iterable[dict[str, Any]] | None = None,
    files: Iterable[tuple[str, bytes]] | None = None,
) -> None:
    """Write one notification (text, embed text and attachments) to the spool after Discord accepts it."""
    directory = os.environ.get(SPOOL_ENV)
    if not directory:
        return
    parts = [text or ""]
    for embed in embeds or []:
        parts.extend(str(embed.get(key) or "") for key in ("title", "description"))
        parts.extend(f"{f.get('name', '')}: {f.get('value', '')}" for f in embed.get("fields") or [])
        if footer := embed.get("footer"):
            parts.append(str(footer.get("text") or ""))
    entry = {
        "ts": time.time(),
        "source": source,
        "text": "\n".join(part for part in parts if part),
        "files": [{"name": name, "b64": base64.b64encode(content).decode("ascii")} for name, content in files or []],
    }
    try:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"{int(entry['ts'] * 1000)}-{secrets.token_hex(3)}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(entry), encoding="utf-8")
        temporary.rename(target)
    except OSError as exc:
        logger.error("Notification spool write failed: %s", exc)
