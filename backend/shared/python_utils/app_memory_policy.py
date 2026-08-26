"""Shared ownership policy for persisted app memories.

App memories remain a generic encrypted-data feature, but the AI app no longer
owns memory categories. Persistence, cache, and inference boundaries use this
module so legacy clients cannot recreate or load removed AI-memory records.
"""

REMOVED_APP_MEMORY_APP_IDS = frozenset({"ai"})
REMOVED_APP_MEMORY_ERROR = "AI memories are no longer supported"


def is_removed_app_memory(app_id: object) -> bool:
    """Return whether an app is forbidden from owning memory records."""
    return str(app_id or "").strip().lower() in REMOVED_APP_MEMORY_APP_IDS


def is_removed_app_memory_key(key: object) -> bool:
    """Recognize removed app keys in server (colon) or client (hyphen) form."""
    value = str(key or "").strip()
    app_id = value.split(":", 1)[0].split("-", 1)[0]
    return is_removed_app_memory(app_id)
