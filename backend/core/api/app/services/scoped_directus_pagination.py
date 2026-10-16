"""Bound SQL reads for explicitly requested complete encrypted collections."""

from typing import Any
from copy import deepcopy
import json

MAX_COMPLETE_CURSOR_BYTES = 256 * 1024


async def read_complete_scoped_records(
    directus: Any, collection: str, *, params: dict[str, Any], admin_required: bool = False,
) -> list[dict[str, Any]]:
    """Preserve legacy complete responses while reading twenty stable rows at a time.

    Callers supply an already authorized scope. Interactive startup paths use
    their byte-bounded window readers instead of this complete-response helper.
    Read failures and invalid cursors must not turn into a successful partial export.
    """
    result: list[dict[str, Any]] = []
    after_id: str | None = None
    seen_ids: list[str] = []
    cursor_bytes = 2
    short_page = False
    while True:
        page_params = {**params, "sort": "id", "limit": 20}
        if seen_ids:
            # Directus disallows _gt for UUID fields. Excluding every observed
            # identity avoids offset skips when preceding rows are deleted.
            if "filter" in params:
                scope = deepcopy(params["filter"])
                if isinstance(scope, str):
                    scope = json.loads(scope)
                if not isinstance(scope, dict):
                    raise RuntimeError("Complete scoped record filter unavailable")
                page_params["filter"] = {"_and": [scope, {"id": {"_nin": list(seen_ids)}}]}
            else:
                excluded = params.get("filter[id][_nin]", [])
                if isinstance(excluded, str):
                    excluded = excluded.split(",")
                if not isinstance(excluded, list):
                    raise RuntimeError("Complete scoped record filter unavailable")
                page_params["filter[id][_nin]"] = [*excluded, *seen_ids]
        rows = await directus.get_items(
            collection, params=page_params, no_cache=True, admin_required=admin_required, raise_on_error=True,
        )
        if not isinstance(rows, list) or len(rows) > 20:
            raise RuntimeError("Complete scoped record page unavailable")
        if not rows:
            return result
        if short_page:
            raise RuntimeError("Complete scoped record changed at terminal page")
        previous = after_id
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                    or not row["id"] or len(row["id"]) > 128
                    or row["id"].strip() != row["id"] or "," in row["id"]
                    or any(ord(character) < 32 for character in row["id"])):
                raise RuntimeError("Complete scoped record identity unavailable")
            if previous is not None and row["id"] <= previous:
                raise RuntimeError("Complete scoped record cursor did not advance")
            previous = row["id"]
            cursor_bytes += len(json.dumps(row["id"], ensure_ascii=False).encode("utf-8")) + 1
            if cursor_bytes > MAX_COMPLETE_CURSOR_BYTES:
                raise RuntimeError("Complete scoped record cursor exceeds bounded request size")
        result.extend(rows)
        after_id = previous
        seen_ids.extend(row["id"] for row in rows)
        short_page = len(rows) < 20
