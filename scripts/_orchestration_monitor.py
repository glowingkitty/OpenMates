# test-file: scripts/tests/test_orchestration_monitor.py
"""Durable checkpoint scheduling over the existing session continuation queue.

Only worker IDs and UTC timestamps are persisted; assignments stay in Tasks.
Pure state operations run under sessions.py's existing atomic metadata lock.
Delivery is handled by the OpenCode hook, never a detached polling service.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def instant(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError) as exc:
        raise RuntimeError('Monitor timestamps must be ISO 8601 with a timezone') from exc
    if result.tzinfo is None:
        raise RuntimeError('Monitor timestamps require a timezone')
    return result.astimezone(timezone.utc)


def stamp(value: datetime) -> str:
    return value.isoformat().replace('+00:00', 'Z')


def active(owner: dict, now: str) -> bool:
    monitor = owner.get('orchestration_monitor') or {}
    return bool(monitor.get('status') == 'active' and not monitor.get('restart_manifest') and monitor.get('workers')
                and instant(monitor['until']) > instant(now))


def register(owner: dict, worker: str, started_at: str, until: str, now: str) -> dict:
    started, expiry, current = instant(started_at), instant(until), instant(now)
    if not worker.startswith('ses_') or len(worker) > 100:
        raise RuntimeError('Monitor worker must be an OpenCode session ID')
    if started > current or expiry <= current or expiry > current + timedelta(days=1):
        raise RuntimeError('Use an actual launch time and a shutdown deadline within 24 hours')
    monitor = owner.setdefault('orchestration_monitor', {})
    if monitor.get('status') != 'active' or instant(monitor['until']) <= current:
        monitor.clear()
        monitor.update(status='active', workers={})
    monitor.pop('restart_manifest', None)
    monitor['until'] = stamp(expiry)
    existing = monitor['workers'].get(worker)
    if not existing or existing['started_at'] != stamp(started):
        monitor['workers'][worker] = {'started_at': stamp(started), 'next_due': stamp(started + timedelta(minutes=5))}
    return monitor


def stop(owner: dict, reason: str = 'explicit_stop') -> None:
    monitor = owner.get('orchestration_monitor')
    if monitor:
        monitor['status'] = 'stopped'
        monitor['reason'] = reason
    record = owner.get('continuation') or {}
    if record.get('operation_type') == 'monitor_ready' and record.get('status') in {'ready', 'delivering'}:
        record['status'] = 'cancelled'


def prepare(owner: dict, now: str) -> dict | None:
    monitor = owner.get('orchestration_monitor') or {}
    if monitor.get('status') == 'active' and instant(monitor['until']) <= instant(now):
        stop(owner, 'shutdown_deadline')
    if not active(owner, now):
        return None
    previous = owner.get('continuation') or {}
    if previous.get('status') in {'ready', 'delivering'}:
        return None
    due = {wid: item['next_due'] for wid, item in monitor['workers'].items()
           if instant(item['next_due']) <= instant(now)}
    if not due:
        return None
    # A failed delivery is visible and is not silently retried every heartbeat.
    key = '|'.join(f'{wid}:{due[wid]}' for wid in sorted(due))
    if previous.get('operation_key') == key and previous.get('status') == 'failed':
        return None
    record = dict(operation_type='monitor_ready', operation_key=key,
                  next_action='Scheduled orchestration checkpoint. Read the daily-meeting-and-orchestration skill and inspect these workers: '
                  + ', '.join(sorted(due)) + '. Compare evidence with approved assignments; leave healthy work uninterrupted. '
                  'Record meaningful findings in Tasks. Keep monitoring unaffected workers when one needs user input. '
                  'Remove completed or deliberately paused workers with sessions.py monitor remove. '
                  'The schedule is durable: no sleep polling or new approval is needed for the next checkpoint. '
                  'When all work is done, stop monitoring, summarize remaining tasks by today\'s focus, and ask what to work on next.',
                  monitor_workers=due, status='ready', attempts=0, created_at=now, updated_at=now)
    owner['continuation'] = record
    return record


def acknowledge(owner: dict, record: dict, now: str) -> None:
    """Coalesce overdue checkpoints, retaining each worker's original cadence."""
    workers = (owner.get('orchestration_monitor') or {}).get('workers', {})
    current = instant(now)
    for wid, due in record.get('monitor_workers', {}).items():
        item = workers.get(wid)
        if not item or item['next_due'] != due:
            continue
        started = instant(item['started_at'])
        elapsed = (current - started).total_seconds()
        minutes = next((n for n in (5, 10, 15, 20) if n * 60 > elapsed), None)
        if minutes is None:
            minutes = 20 + (int((elapsed - 1200) // 1200) + 1) * 20
        item['next_due'] = stamp(started + timedelta(minutes=minutes))
