# contract-test-file: tooling
"""Offline supplier transport/archive attacks; no product calls or accounts."""

import hashlib
import importlib.util
import io
from pathlib import Path
import stat
import tarfile

import pytest


spec = importlib.util.spec_from_file_location(
    "ci_download_node_supplier",
    Path(__file__).parents[1] / "ci_download_node_supplier.py",
)
supplier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supplier)


def archive(
    *,
    arch="x64",
    mode=0o755,
    kind=tarfile.REGTYPE,
    name=None,
    body=b"\x7fELFsynthetic-node",
    duplicate=False,
    missing=False,
):
    prefix = f"node-{supplier.NODE_VERSION}-linux-{arch}"
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as package:
        entry = tarfile.TarInfo(name or f"{prefix}/bin/node")
        entry.mode, entry.type = mode, kind
        entry.linkname = "../../outside"
        entry.size = len(body) if kind == tarfile.REGTYPE else 0
        if not missing:
            for _ in range(2 if duplicate else 1):
                package.addfile(entry, io.BytesIO(body))
        # Official packages contain unrelated symlinks; none may be extracted.
        link = tarfile.TarInfo(f"{prefix}/bin/npm")
        link.type, link.linkname = (
            tarfile.SYMTYPE,
            "../lib/node_modules/npm/bin/npm-cli.js",
        )
        package.addfile(link)
    return output.getvalue()


def transport(data, *, arch="x64", checksum=None):
    filename = f"node-{supplier.NODE_VERSION}-linux-{arch}.tar.gz"
    sums = (
        checksum
        if checksum is not None
        else f"{hashlib.sha256(data).hexdigest()}  {filename}\n".encode()
    )
    requests = []

    def fetch(url, destination, limit):
        requests.append(url)
        assert url in {
            supplier.OFFICIAL_DIST + filename,
            supplier.OFFICIAL_DIST + "SHASUMS256.txt",
        }
        destination.write(sums if url.endswith("SHASUMS256.txt") else data)

    return fetch, requests


def private_cache(tmp_path):
    cache = tmp_path / "private"
    cache.mkdir(mode=0o700)
    return cache


@pytest.mark.parametrize("arch", ["x64", "arm64"])
def test_verified_archive_writes_only_one_private_regular_executable(tmp_path, arch):
    cache = private_cache(tmp_path)
    data = archive(arch=arch)
    fetch, requests = transport(data, arch=arch)
    result = supplier.download_supplier(cache, arch=arch, fetcher=fetch)
    binary = Path(result["binary"])
    assert binary == cache / "node" / supplier.NODE_VERSION[1:] / arch / "bin/node"
    assert binary.read_bytes() == b"\x7fELFsynthetic-node"
    assert stat.S_IMODE(binary.stat().st_mode) == 0o700 and binary.stat().st_nlink == 1
    assert [p for p in cache.rglob("*") if p.is_file() or p.is_symlink()] == [binary]
    assert result["archive_sha256"] == hashlib.sha256(data).hexdigest()
    assert requests[0].endswith("/SHASUMS256.txt") and len(requests) == 2


def test_archive_tamper_is_refused_before_any_executable_write(tmp_path):
    cache = private_cache(tmp_path)
    fetch, _ = transport(
        archive(),
        checksum=(
            "0" * 64 + "  node-" + supplier.NODE_VERSION + "-linux-x64.tar.gz\n"
        ).encode(),
    )
    with pytest.raises(ValueError, match="supplier_checksum$"):
        supplier.download_supplier(cache, arch="x64", fetcher=fetch)
    assert list(cache.iterdir()) == []


@pytest.mark.parametrize("mode", [0o777, 0o775, 0o6755, 0o4755, 0o644])
def test_archive_binary_unsafe_modes_remain_refused(tmp_path, mode):
    fetch, _ = transport(archive(mode=mode))
    with pytest.raises(ValueError, match="supplier_binary_policy"):
        supplier.download_supplier(private_cache(tmp_path), arch="x64", fetcher=fetch)


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE])
def test_archive_binary_must_be_regular_not_a_link_or_directory(tmp_path, kind):
    fetch, _ = transport(archive(kind=kind))
    with pytest.raises(ValueError, match="supplier_binary_policy"):
        supplier.download_supplier(private_cache(tmp_path), arch="x64", fetcher=fetch)


@pytest.mark.parametrize(
    "name",
    [
        "/absolute/bin/node",
        "../../escape",
        "wrong-root/bin/node",
        f"node-{supplier.NODE_VERSION}-linux-x64/../escape",
    ],
)
def test_archive_paths_cannot_escape_the_expected_package(tmp_path, name):
    fetch, _ = transport(archive(name=name))
    with pytest.raises(ValueError, match="supplier_archive_path"):
        supplier.download_supplier(private_cache(tmp_path), arch="x64", fetcher=fetch)
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"duplicate": True}, "supplier_binary_duplicate"),
        ({"missing": True}, "supplier_binary_missing"),
        ({"body": b"not-ELF"}, "supplier_binary_elf"),
    ],
)
def test_duplicate_missing_or_non_elf_binary_is_refused(tmp_path, options, reason):
    fetch, _ = transport(archive(**options))
    with pytest.raises(ValueError, match=reason):
        supplier.download_supplier(private_cache(tmp_path), arch="x64", fetcher=fetch)


@pytest.mark.parametrize("checksum", [b"", b"0 invalid\n", b"a" * 65537])
def test_missing_malformed_or_oversized_checksums_are_refused(tmp_path, checksum):
    fetch, _ = transport(archive(), checksum=checksum)
    with pytest.raises(
        ValueError, match="supplier_checksum_entry|supplier_download_size"
    ):
        supplier.download_supplier(private_cache(tmp_path), arch="x64", fetcher=fetch)


def test_duplicate_checksum_entry_is_refused(tmp_path):
    data = archive()
    line = f"{hashlib.sha256(data).hexdigest()}  node-{supplier.NODE_VERSION}-linux-x64.tar.gz\n".encode()
    fetch, _ = transport(data, checksum=line * 2)
    with pytest.raises(ValueError, match="supplier_checksum_entry"):
        supplier.download_supplier(private_cache(tmp_path), arch="x64", fetcher=fetch)


@pytest.mark.parametrize(
    "limit,reason",
    [
        ("MAX_ARCHIVE", "supplier_download_size"),
        ("MAX_BINARY", "supplier_binary_policy"),
        ("MAX_UNPACKED", "supplier_unpacked_size"),
    ],
)
def test_download_member_and_unpacked_size_bounds(tmp_path, monkeypatch, limit, reason):
    monkeypatch.setattr(supplier, limit, 4)
    fetch, _ = transport(archive())
    with pytest.raises(ValueError, match=reason):
        supplier.download_supplier(private_cache(tmp_path), arch="x64", fetcher=fetch)


@pytest.mark.parametrize("attack", ["mode", "symlink", "nonempty", "relative"])
def test_supplier_cache_must_be_fresh_canonical_and_private(tmp_path, attack):
    cache = private_cache(tmp_path)
    if attack == "mode":
        cache.chmod(0o777)
    elif attack == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(cache, target_is_directory=True)
        cache = alias
    elif attack == "relative":
        cache = Path("relative-cache")
    else:
        (cache / "existing").write_text("retain")
    with pytest.raises(ValueError, match="supplier_cache_"):
        supplier.download_supplier(
            cache, arch="x64", fetcher=lambda *a: pytest.fail("no download")
        )


def test_transport_enforces_fixed_source_no_redirects_and_stream_limit(monkeypatch):
    url = supplier.OFFICIAL_DIST + "SHASUMS256.txt"
    response = io.BytesIO(b"123456789")
    response.geturl = lambda: url

    class Opener:
        def open(self, requested, timeout):
            assert requested == url and timeout == 30
            return response

    monkeypatch.setattr(supplier.urllib.request, "build_opener", lambda *args: Opener())
    destination = io.BytesIO()
    with pytest.raises(ValueError, match="supplier_download_size"):
        supplier.fetch(url, destination, 8)
    assert len(destination.getvalue()) <= 8
    with pytest.raises(ValueError, match="supplier_url"):
        supplier.fetch("https://other.example/node.tar.gz", io.BytesIO(), 8)
    with pytest.raises(ValueError, match="supplier_redirect"):
        supplier.NoRedirect().redirect_request(
            None, None, 302, "", {}, "http://nodejs.org/file"
        )
