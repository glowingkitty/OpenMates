"""Lost-update protection for legacy ``sessions.json`` load/modify/save writers.

Many sessions.py commands still ``_load_sessions()`` without a lock, modify the
dict and later ``_save_sessions(data)``. A concurrent writer that committed in
between was silently overwritten. Observed failure: two ``lane_start.py`` runs
in parallel; one process's ``_run_workspace_transition`` wrote its session's
``lifecycle`` record via ``_mutate_sessions`` while the other process held an
older snapshot, whose save then dropped that ``lifecycle`` field, and
``finish`` crashed with ``KeyError: 'lifecycle'`` (a retry succeeded).

``merge_concurrent_state`` runs inside ``_save_sessions``'s file lock against
the on-disk state and keeps what a stale snapshot cannot know about:

* top-level coordination keys owned by lock-holding writers;
* each session's ``lifecycle`` record, which only ``_mutate_sessions``
  transactions write, so the on-disk copy is always the newest;
* sessions created on disk after this snapshot was loaded (a session the
  snapshot loaded and then removed stays removed).
"""

from __future__ import annotations

from collections import OrderedDict

LOCK_OWNED_KEYS = ("locks", "infrastructure", "edit_leases", "deploy_queue")
MAX_TRACKED_SNAPSHOTS = 256

# id(snapshot) -> (snapshot, session ids present when it was loaded). Holding the
# snapshot keeps its id from being reused while tracked.
_loaded: OrderedDict[int, tuple[dict, frozenset[str]]] = OrderedDict()


def remember_loaded(data: dict) -> dict:
    """Record which sessions a freshly loaded snapshot contained; return it."""
    sessions = data.get("sessions") if isinstance(data, dict) else None
    _loaded[id(data)] = (data, frozenset(sessions) if isinstance(sessions, dict) else frozenset())
    _loaded.move_to_end(id(data))
    while len(_loaded) > MAX_TRACKED_SNAPSHOTS:
        _loaded.popitem(last=False)
    return data


def merge_concurrent_state(data: dict, current: dict) -> None:
    """Fold concurrent on-disk writes into ``data`` before it replaces ``current``."""
    for key in LOCK_OWNED_KEYS:
        if key in current:
            data[key] = current[key]
    on_disk = current.get("sessions")
    if not isinstance(on_disk, dict):
        return
    sessions = data.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        return
    entry = _loaded.get(id(data))
    loaded_ids = entry[1] if entry and entry[0] is data else None
    for session_id, disk_session in on_disk.items():
        if not isinstance(disk_session, dict):
            continue
        mine = sessions.get(session_id)
        if mine is None:
            if loaded_ids is not None and session_id not in loaded_ids:
                sessions[session_id] = disk_session
            continue
        if isinstance(mine, dict) and "lifecycle" in disk_session:
            mine["lifecycle"] = disk_session["lifecycle"]
