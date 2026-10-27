#!/usr/bin/env python3
"""Acquire one official Node executable before candidate code; stdlib only."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import tarfile
import tempfile
import urllib.request

NODE_VERSION = "v24.22.1"
OFFICIAL_DIST = f"https://nodejs.org/dist/{NODE_VERSION}/"
MAX_ARCHIVE = 128 * 1024**2
MAX_BINARY = 256 * 1024**2
MAX_UNPACKED = 512 * 1024**2


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("supplier_redirect")


def fetch(url: str, destination, limit: int) -> None:
    require(url.startswith(OFFICIAL_DIST), "supplier_url")
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(url, timeout=30) as response:
        require(response.geturl() == url, "supplier_redirect")
        total = 0
        while chunk := response.read(min(1024 * 1024, limit + 1 - total)):
            total += len(chunk)
            require(total <= limit, "supplier_download_size")
            destination.write(chunk)


def download_supplier(cache: Path, *, arch: str | None = None, fetcher=fetch) -> dict:
    require(platform.system() == "Linux", "supplier_platform")
    arch = arch or {"x86_64": "x64", "aarch64": "arm64"}.get(platform.machine())
    require(arch in {"x64", "arm64"}, "supplier_arch")
    cache = Path(cache)
    require(cache.is_absolute() and cache.resolve() == cache, "supplier_cache_path")
    before = cache.lstat()
    require(
        stat.S_ISDIR(before.st_mode)
        and before.st_uid == os.geteuid()
        and stat.S_IMODE(before.st_mode) == 0o700,
        "supplier_cache_policy",
    )
    cache_fd = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory_fds = [cache_fd]
    children = []

    def directory_identity(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)

    def guard_cache():
        require(
            directory_identity(before)
            == directory_identity(os.fstat(cache_fd))
            == directory_identity(cache.lstat()),
            "supplier_cache_changed",
        )
        for parent_fd, name, child_fd, expected in children:
            require(
                directory_identity(expected)
                == directory_identity(os.fstat(child_fd))
                == directory_identity(
                    os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                ),
                "supplier_directory_changed",
            )

    def mkdir_chain(parts):
        parent_fd = cache_fd
        for name in parts:
            guard_cache()
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            child_fd = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
            directory_fds.append(child_fd)
            info = os.fstat(child_fd)
            require(
                info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                "supplier_directory_policy",
            )
            children.append((parent_fd, name, child_fd, info))
            guard_cache()
            parent_fd = child_fd
        return parent_fd

    try:
        guard_cache()
        require(not os.listdir(cache_fd), "supplier_cache_not_empty")
        filename = f"node-{NODE_VERSION}-linux-{arch}.tar.gz"
        prefix = filename.removesuffix(".tar.gz")
        with (
            tempfile.TemporaryFile(dir=f"/proc/self/fd/{cache_fd}") as checksums,
            tempfile.TemporaryFile(dir=f"/proc/self/fd/{cache_fd}") as archive,
        ):
            fetcher(OFFICIAL_DIST + "SHASUMS256.txt", checksums, 64 * 1024)
            require(0 < checksums.tell() <= 64 * 1024, "supplier_download_size")
            checksums.seek(0)
            rows = [
                re.fullmatch(r"([0-9a-f]{64})[ \t]+" + re.escape(filename), line)
                for line in checksums.read(64 * 1024 + 1).decode("ascii").splitlines()
            ]
            matches = [row.group(1) for row in rows if row]
            require(len(matches) == 1, "supplier_checksum_entry")
            fetcher(OFFICIAL_DIST + filename, archive, MAX_ARCHIVE)
            require(0 < archive.tell() <= MAX_ARCHIVE, "supplier_download_size")
            archive.seek(0)
            require(
                hashlib.file_digest(archive, "sha256").hexdigest() == matches[0],
                "supplier_checksum",
            )
            archive.seek(0)
            binary = None
            with tarfile.open(fileobj=archive, mode="r|gz") as package:
                for member in package:
                    parts = PurePosixPath(member.name).parts
                    require(
                        parts
                        and parts[0] == prefix
                        and ".." not in parts
                        and "\\" not in member.name
                        and not member.name.startswith("/"),
                        "supplier_archive_path",
                    )
                    require(
                        member.offset_data + member.size <= MAX_UNPACKED,
                        "supplier_unpacked_size",
                    )
                    if member.name != f"{prefix}/bin/node":
                        continue
                    require(binary is None, "supplier_binary_duplicate")
                    require(
                        member.isfile()
                        and member.mode == 0o755
                        and 0 < member.size <= MAX_BINARY,
                        "supplier_binary_policy",
                    )
                    binary = cache / "node" / NODE_VERSION[1:] / arch / "bin" / "node"
                    parent_fd = mkdir_chain(["node", NODE_VERSION[1:], arch, "bin"])
                    guard_cache()
                    fd = os.open(
                        "node",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o700,
                        dir_fd=parent_fd,
                    )
                    with (
                        os.fdopen(fd, "wb") as output,
                        package.extractfile(member) as source,
                    ):
                        magic = source.read(4)
                        require(magic == b"\x7fELF", "supplier_binary_elf")
                        guard_cache()
                        output.write(magic)
                        copied = len(magic)
                        while chunk := source.read(1024 * 1024):
                            copied += len(chunk)
                            require(copied <= member.size, "supplier_binary_size")
                            guard_cache()
                            output.write(chunk)
                        require(copied == member.size, "supplier_binary_size")
                        output.flush()
                        os.fchmod(output.fileno(), 0o700)
                        os.fsync(output.fileno())
            require(binary is not None, "supplier_binary_missing")
        guard_cache()
        for directory_fd in reversed(directory_fds):
            os.fsync(directory_fd)
        after = cache.lstat()
        require(
            (before.st_dev, before.st_ino, before.st_mode, before.st_uid)
            == (after.st_dev, after.st_ino, after.st_mode, after.st_uid),
            "supplier_cache_changed",
        )
        return {
            "binary": str(binary),
            "node_version": NODE_VERSION,
            "architecture": arch,
            "archive_sha256": matches[0],
        }
    finally:
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def main() -> None:
    try:
        result = download_supplier(Path(os.environ["OPENMATES_CI_NODE_SUPPLIER_CACHE"]))
        with open(os.environ["GITHUB_ENV"], "a") as output:
            output.write(f"OPENMATES_CI_NODE_SUPPLIER={result.pop('binary')}\n")
        print(json.dumps({"status": "downloaded", **result}))
    except Exception as error:
        reason = (
            str(error)
            if isinstance(error, ValueError) and re.fullmatch(r"[a-z_]+", str(error))
            else "supplier_io"
        )
        print(json.dumps({"status": "refused", "predicate": reason}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
