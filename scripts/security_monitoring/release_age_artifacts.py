"""Safe npm tarball comparison for emergency fix-version integrity checks.

Tarballs are untrusted data: they are downloaded into a fresh temporary
directory, only read member by member with ``tarfile`` (nothing is extracted or
executed) and bounded in size. See
specifications/architecture/security-monitoring/specification.yml
(security-monitoring.release-age.security-priority).
"""

from __future__ import annotations

import io
import posixpath
import tarfile
import tempfile
import urllib.request
from pathlib import Path

MAX_TARBALL_BYTES = 50 * 1024 * 1024
MAX_MEMBER_READ = 2 * 1024 * 1024
MINIFIED_LINE_BYTES = 200 * 1024
BINARY_SUFFIXES = (".node", ".wasm", ".exe", ".dll", ".so", ".dylib", ".bin")
BINARY_MAGIC = (b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\x00asm")
JS_SUFFIXES = (".js", ".cjs", ".mjs")


class ArtifactError(RuntimeError):
    """The tarball could not be downloaded or parsed."""


def download_tarball(url: str, destination: Path) -> None:
    """Download a tarball with a hard size cap into ``destination``."""
    if not url.startswith("https://"):
        raise ArtifactError("tarball url must be https")
    request = urllib.request.Request(url, headers={"User-Agent": "openmates-release-age"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - https enforced above
        data = response.read(MAX_TARBALL_BYTES + 1)
    if len(data) > MAX_TARBALL_BYTES:
        raise ArtifactError("tarball exceeds size cap")
    destination.write_bytes(data)


def summarize_tarball(path: Path) -> dict[str, dict[str, object]]:
    """Return per-file facts (size, binary flag, minified flag) without extracting."""
    summary: dict[str, dict[str, object]] = {}
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                name = posixpath.normpath(member.name)
                if name.startswith(("/", "..")) or "/../" in name:
                    raise ArtifactError("unsafe tar member path")
                head = archive.extractfile(member)
                sample = head.read(MAX_MEMBER_READ) if head else b""
                binary = name.lower().endswith(BINARY_SUFFIXES) or sample.startswith(BINARY_MAGIC)
                minified = (
                    name.lower().endswith(JS_SUFFIXES)
                    and member.size > MINIFIED_LINE_BYTES
                    and max((len(line) for line in io.BytesIO(sample)), default=0) > MINIFIED_LINE_BYTES
                )
                summary[name] = {"size": member.size, "binary": binary, "minified": minified}
    except (tarfile.TarError, EOFError, OSError) as error:
        raise ArtifactError(f"cannot read tarball: {error}") from error
    return summary


def flag_new_content(previous: dict[str, dict[str, object]], current: dict[str, dict[str, object]]) -> list[str]:
    """Flag binary or minified single-line files that are new in ``current``."""
    flags: list[str] = []
    for name, facts in sorted(current.items()):
        before = previous.get(name)
        if facts["binary"] and not (before and before["binary"]):
            flags.append(f"new binary content: {name}")
        if facts["minified"] and not (before and before["minified"]):
            flags.append(f"new minified single-line JS over 200KB: {name}")
    return flags


def compare_npm_tarballs(previous_url: str, current_url: str) -> list[str]:
    """Download both tarballs into a fresh temp dir and return content flags."""
    with tempfile.TemporaryDirectory(prefix="release-age-") as directory:
        old_path = Path(directory) / "previous.tgz"
        new_path = Path(directory) / "current.tgz"
        download_tarball(previous_url, old_path)
        download_tarball(current_url, new_path)
        return flag_new_content(summarize_tarball(old_path), summarize_tarball(new_path))
