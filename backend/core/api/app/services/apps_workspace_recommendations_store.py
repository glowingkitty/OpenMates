"""Private Apps disk store: ciphertext only, atomic publication, no result cache.

The shared directory MUST be excluded from backup/snapshot policies. Unlinking
expired ciphertext cannot erase preexisting host snapshots or physical blocks.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, AsyncIterator


class AppsRecommendationsStore:
    def __init__(self, directory: str | Path | None = None) -> None:
        configured = directory or os.environ.get("APPS_RECOMMENDATIONS_DIR")
        if not configured:
            raise RuntimeError("APPS_RECOMMENDATIONS_DIR is required")
        self.root = Path(configured)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        if os.geteuid() == 0 and self.root.name == "public":
            owner = self.root.parent.stat()
            os.chown(self.root, owner.st_uid, owner.st_gid)

    @staticmethod
    def scope(user_id: str, app_id: str, team_id: str | None) -> str:
        return hashlib.sha256(json.dumps([user_id, app_id, team_id]).encode()).hexdigest()

    def path(self, scope: str, kind: str) -> Path:
        if len(scope) != 64 or any(c not in "0123456789abcdef" for c in scope):
            raise ValueError("Invalid Apps scope")
        if kind not in {"meta", "batch", "lock", "activity"}:
            raise ValueError("Invalid Apps store kind")
        return self.root / f"{scope}.{kind}"

    def read(self, scope: str, kind: str) -> dict[str, Any] | None:
        try:
            return json.loads(self.path(scope, kind).read_text())
        except FileNotFoundError:
            return None

    def write(self, scope: str, kind: str, data: dict[str, Any]) -> None:
        """Same-filesystem fsync + replace; never leave a backup of old batches."""
        descriptor, name = tempfile.mkstemp(prefix=".publish-", dir=self.root)
        try:
            if os.geteuid() == 0:
                owner = self.root.stat()
                os.fchown(descriptor, owner.st_uid, owner.st_gid)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(data, stream, separators=(",", ":"), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path(scope, kind))
            directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            Path(name).unlink(missing_ok=True)

    def delete(self, scope: str, kind: str) -> None:
        self.path(scope, kind).unlink(missing_ok=True)
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @asynccontextmanager
    async def locked(self, scope: str) -> AsyncIterator[None]:
        # Nonblocking acquisition avoids deadlocking this event loop while the
        # current owner awaits Vault. Locks have a stable inode, never replaced.
        descriptor = os.open(self.path(scope, "lock"), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.geteuid() == 0:
                owner = self.root.stat()
                os.fchown(descriptor, owner.st_uid, owner.st_gid)
            for _ in range(1000):
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.01)
            else:
                raise RuntimeError("Apps library is busy")
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def scopes(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.meta"))

    def expire_batch(self, scope: str, now: int) -> bool:
        batch = self.read(scope, "batch")
        if batch and int(batch.get("expires_at", 0)) <= now:
            self.delete(scope, "batch")
            return True
        return False

    async def cleanup(self, now: int | None = None) -> int:
        now = int(time.time()) if now is None else now
        deleted = 0
        for scope in self.scopes():
            async with self.locked(scope):
                deleted += int(self.expire_batch(scope, now))
        # Interrupted publications contain ciphertext only. Never retain them
        # indefinitely after a worker dies before os.replace.
        for path in self.root.glob(".publish-*"):
            try:
                if path.stat().st_mtime < now - 300:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
        return deleted

    async def mark_activity(self, user_id: str, now: int | None = None) -> None:
        scope = self.scope(user_id, "activity", None)
        async with self.locked(scope):
            self.write(scope, "activity", {"last_active_at": int(time.time()) if now is None else now})
