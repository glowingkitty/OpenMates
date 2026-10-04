"""Bound SQL reads for explicitly requested complete encrypted collections."""

from typing import Any


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
    while True:
        page_params = {**params, "sort": "id", "limit": 20}
        if after_id is not None:
            page_params["filter[id][_gt]"] = after_id
        rows = await directus.get_items(
            collection, params=page_params, no_cache=True, admin_required=admin_required, raise_on_error=True,
        )
        if not isinstance(rows, list) or len(rows) > 20:
            raise RuntimeError("Complete scoped record page unavailable")
        if not rows:
            return result
        previous = after_id
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                raise RuntimeError("Complete scoped record identity unavailable")
            if previous is not None and row["id"] <= previous:
                raise RuntimeError("Complete scoped record cursor did not advance")
            previous = row["id"]
        result.extend(rows)
        after_id = previous
        if len(rows) < 20:
            return result
