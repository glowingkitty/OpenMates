#!/usr/bin/env python3
"""Coordinate OpenCode file ownership in the shared repository worktree.

The coordinator grants canonical file sets atomically, queues conflicting
requests, renews live ownership, and fences stale owners with generations.
State updates use a short OS file lock; product leases always have a bounded TTL.
The CLI returns JSON so the OpenCode plugin can block or resume exact sessions.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import time
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = REPO_ROOT / ".opencode" / "file-leases.json"
DEFAULT_TTL_SECONDS = 300
DEFAULT_QUEUE_TTL_SECONDS = 86_400
DEFAULT_CLAIM_TTL_SECONDS = 30


class LeaseCoordinator:
    """Persist and mutate file leases under one short-lived state-file lock."""

    def __init__(self, state_path: Path = DEFAULT_STATE_PATH):
        self.state_path = state_path
        self.lock_path = state_path.with_suffix(f"{state_path.suffix}.lock")

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "version": 1,
            "next_generation": 1,
            "next_request": 1,
            "leases": {},
            "queue": [],
            "notifications": [],
        }

    @staticmethod
    def _files(files: list[str]) -> list[str]:
        normalized: set[str] = set()
        for raw_file in files:
            path = Path(raw_file)
            if path.is_absolute():
                try:
                    path = path.resolve().relative_to(REPO_ROOT)
                except ValueError as exc:
                    raise ValueError(f"File is outside the repository: {raw_file}") from exc
            if ".." in path.parts:
                raise ValueError(f"File path cannot traverse outside the repository: {raw_file}")
            normalized.add(path.as_posix().removeprefix("./"))
        if not normalized:
            raise ValueError("At least one file is required")
        return sorted(normalized)

    def _mutate(self, callback: Callable[[dict[str, Any]], Any]) -> Any:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                if self.state_path.exists():
                    state = json.loads(self.state_path.read_text(encoding="utf-8"))
                else:
                    state = self._empty_state()
                result = callback(state)
                temporary_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
                temporary_path.write_text(f"{json.dumps(state, indent=2, sort_keys=True)}\n", encoding="utf-8")
                os.replace(temporary_path, self.state_path)
                return result
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _expire(state: dict[str, Any], now: float) -> list[str]:
        expired_sessions = sorted(
            {
                lease["session_id"]
                for lease in state["leases"].values()
                if lease["expires_at"] <= now
            }
        )
        state["leases"] = {
            path: lease
            for path, lease in state["leases"].items()
            if lease["expires_at"] > now
        }
        return expired_sessions

    @staticmethod
    def _expire_waiters(state: dict[str, Any], now: float) -> list[str]:
        expired_waiters = sorted(
            {
                request["session_id"]
                for request in state["queue"]
                if request.get("expires_at", request["queued_at"] + DEFAULT_QUEUE_TTL_SECONDS) <= now
            }
        )
        state["queue"] = [
            request
            for request in state["queue"]
            if request.get("expires_at", request["queued_at"] + DEFAULT_QUEUE_TTL_SECONDS) > now
        ]
        return expired_waiters

    @staticmethod
    def _grant(state: dict[str, Any], session_id: str, files: list[str], now: float, ttl_seconds: int) -> dict[str, Any]:
        generation = state["next_generation"]
        state["next_generation"] += 1
        for path in files:
            state["leases"][path] = {
                "session_id": session_id,
                "generation": generation,
                "expires_at": now + ttl_seconds,
            }
        return {"session_id": session_id, "files": files, "generation": generation}

    @classmethod
    def _grant_waiters(cls, state: dict[str, Any], now: float, ttl_seconds: int) -> list[dict[str, Any]]:
        newly_granted: list[dict[str, Any]] = []
        waiting: list[dict[str, Any]] = []
        reserved_by_earlier_waiters: set[str] = set()
        for request in state["queue"]:
            conflicts = any(
                path in state["leases"]
                and state["leases"][path]["session_id"] != request["session_id"]
                for path in request["files"]
            )
            bypasses_earlier_waiter = bool(reserved_by_earlier_waiters.intersection(request["files"]))
            if not conflicts and not bypasses_earlier_waiter:
                grant = cls._grant(state, request["session_id"], request["files"], now, ttl_seconds)
                newly_granted.append(grant)
                state.setdefault("notifications", []).append(grant)
            else:
                waiting.append(request)
                reserved_by_earlier_waiters.update(request["files"])
        state["queue"] = waiting
        return newly_granted

    def acquire(
        self,
        session_id: str,
        files: list[str],
        *,
        now: float | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        queue_ttl_seconds: int = DEFAULT_QUEUE_TTL_SECONDS,
    ) -> dict[str, Any]:
        requested_files = self._files(files)
        current_time = time.time() if now is None else now

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            self._expire(state, current_time)
            self._expire_waiters(state, current_time)
            self._grant_waiters(state, current_time, ttl_seconds)

            for position, request in enumerate(state["queue"], start=1):
                if request["session_id"] == session_id and request["files"] == requested_files:
                    request["expires_at"] = current_time + queue_ttl_seconds
                    return {"status": "waiting", "position": position, "files": requested_files}

            reserved_by_waiters = {path for request in state["queue"] for path in request["files"]}
            owners = {
                state["leases"][path]["session_id"]
                for path in requested_files
                if path in state["leases"]
            }
            if not reserved_by_waiters.intersection(requested_files) and (not owners or owners == {session_id}):
                grant = self._grant(state, session_id, requested_files, current_time, ttl_seconds)
                return {"status": "granted", **grant}

            request_id = state["next_request"]
            state["next_request"] += 1
            state["queue"].append(
                {
                    "id": request_id,
                    "session_id": session_id,
                    "files": requested_files,
                    "queued_at": current_time,
                    "expires_at": current_time + queue_ttl_seconds,
                }
            )
            return {"status": "waiting", "position": len(state["queue"]), "files": requested_files}

        return self._mutate(mutate)

    def heartbeat(
        self,
        session_id: str,
        *,
        now: float | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        queue_ttl_seconds: int = DEFAULT_QUEUE_TTL_SECONDS,
    ) -> dict[str, Any]:
        current_time = time.time() if now is None else now

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            expired_sessions = self._expire(state, current_time)
            expired_waiters = self._expire_waiters(state, current_time)
            renewed = sorted(
                path for path, lease in state["leases"].items() if lease["session_id"] == session_id
            )
            for path in renewed:
                state["leases"][path]["expires_at"] = current_time + ttl_seconds
            for request in state["queue"]:
                if request["session_id"] == session_id:
                    request["expires_at"] = current_time + queue_ttl_seconds
            newly_granted = self._grant_waiters(state, current_time, ttl_seconds)
            return {
                "renewed": renewed,
                "expired_sessions": expired_sessions,
                "expired_waiters": expired_waiters,
                "newly_granted": newly_granted,
                "pending_notifications": list(state.get("notifications", [])),
            }

        return self._mutate(mutate)

    def release(
        self,
        session_id: str,
        files: list[str] | None = None,
        *,
        now: float | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> dict[str, Any]:
        requested_files = self._files(files) if files else None
        current_time = time.time() if now is None else now

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            expired_sessions = self._expire(state, current_time)
            expired_waiters = self._expire_waiters(state, current_time)
            released = sorted(
                path
                for path, lease in state["leases"].items()
                if lease["session_id"] == session_id and (requested_files is None or path in requested_files)
            )
            for path in released:
                del state["leases"][path]
            state["queue"] = [request for request in state["queue"] if request["session_id"] != session_id]
            newly_granted = self._grant_waiters(state, current_time, ttl_seconds)
            return {
                "released": released,
                "expired_sessions": expired_sessions,
                "expired_waiters": expired_waiters,
                "newly_granted": newly_granted,
                "pending_notifications": list(state.get("notifications", [])),
            }

        return self._mutate(mutate)

    def sweep(
        self,
        *,
        now: float | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> dict[str, Any]:
        current_time = time.time() if now is None else now

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            expired_sessions = self._expire(state, current_time)
            expired_waiters = self._expire_waiters(state, current_time)
            newly_granted = self._grant_waiters(state, current_time, ttl_seconds)
            return {
                "expired_sessions": expired_sessions,
                "expired_waiters": expired_waiters,
                "newly_granted": newly_granted,
                "pending_notifications": list(state.get("notifications", [])),
            }

        return self._mutate(mutate)

    def claim_notifications(
        self,
        claimant_id: str,
        *,
        now: float | None = None,
        claim_ttl_seconds: int = DEFAULT_CLAIM_TTL_SECONDS,
    ) -> dict[str, Any]:
        current_time = time.time() if now is None else now

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            claimed: list[dict[str, Any]] = []
            for notification in state.get("notifications", []):
                if notification.get("claim_expires_at", 0) > current_time:
                    continue
                notification["claimed_by"] = claimant_id
                notification["claim_expires_at"] = current_time + claim_ttl_seconds
                claimed.append(dict(notification))
            return {"notifications": claimed}

        return self._mutate(mutate)

    def acknowledge(self, session_id: str, generation: int) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            before = len(state.get("notifications", []))
            state["notifications"] = [
                notification
                for notification in state.get("notifications", [])
                if not (
                    notification["session_id"] == session_id
                    and notification["generation"] == generation
                )
            ]
            return {"acknowledged": len(state["notifications"]) < before}

        return self._mutate(mutate)

    def authorize(
        self,
        session_id: str,
        files: list[str],
        generation: int,
        *,
        now: float | None = None,
    ) -> bool:
        requested_files = self._files(files)
        current_time = time.time() if now is None else now

        def mutate(state: dict[str, Any]) -> bool:
            self._expire(state, current_time)
            return all(
                path in state["leases"]
                and state["leases"][path]["session_id"] == session_id
                and state["leases"][path]["generation"] == generation
                for path in requested_files
            )

        return self._mutate(mutate)

    def status(self, *, now: float | None = None) -> dict[str, Any]:
        current_time = time.time() if now is None else now

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            self._expire(state, current_time)
            self._expire_waiters(state, current_time)
            return {
                "leases": dict(state["leases"]),
                "queue": list(state["queue"]),
                "pending_notifications": list(state.get("notifications", [])),
            }

        return self._mutate(mutate)


def main() -> int:
    parser = argparse.ArgumentParser(description="Coordinate OpenCode file leases")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--queue-ttl", type=int, default=DEFAULT_QUEUE_TTL_SECONDS)
    parser.add_argument("--claim-ttl", type=int, default=DEFAULT_CLAIM_TTL_SECONDS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("acquire", "authorize"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--session", required=True)
        command_parser.add_argument("--files", nargs="+", required=True)
        if command == "authorize":
            command_parser.add_argument("--generation", type=int, required=True)

    heartbeat_parser = subparsers.add_parser("heartbeat")
    heartbeat_parser.add_argument("--session", required=True)
    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--session", required=True)
    release_parser.add_argument("--files", nargs="+")
    acknowledge_parser = subparsers.add_parser("acknowledge")
    acknowledge_parser.add_argument("--session", required=True)
    acknowledge_parser.add_argument("--generation", type=int, required=True)
    claim_parser = subparsers.add_parser("claim")
    claim_parser.add_argument("--session", required=True)
    subparsers.add_parser("sweep")
    subparsers.add_parser("status")

    args = parser.parse_args()
    coordinator = LeaseCoordinator(args.state)
    if args.command == "acquire":
        result = coordinator.acquire(
            args.session,
            args.files,
            ttl_seconds=args.ttl,
            queue_ttl_seconds=args.queue_ttl,
        )
    elif args.command == "authorize":
        authorized = coordinator.authorize(args.session, args.files, args.generation)
        result = {"authorized": authorized}
    elif args.command == "heartbeat":
        result = coordinator.heartbeat(
            args.session,
            ttl_seconds=args.ttl,
            queue_ttl_seconds=args.queue_ttl,
        )
    elif args.command == "release":
        result = coordinator.release(args.session, args.files, ttl_seconds=args.ttl)
    elif args.command == "acknowledge":
        result = coordinator.acknowledge(args.session, args.generation)
    elif args.command == "claim":
        result = coordinator.claim_notifications(
            args.session,
            claim_ttl_seconds=args.claim_ttl,
        )
    elif args.command == "sweep":
        result = coordinator.sweep(ttl_seconds=args.ttl)
    else:
        result = coordinator.status()

    print(json.dumps(result, sort_keys=True))
    if args.command == "acquire" and result["status"] == "waiting":
        return 2
    if args.command == "authorize" and not result["authorized"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
