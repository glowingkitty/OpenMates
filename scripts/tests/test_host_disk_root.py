# contract-test-file: tooling
"""Tests for the weekly root disk cleanup (scripts/host_disk_root.py)."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import host_disk_root as tool  # noqa: E402 - repo-local module, path set just above

NOW = 2_000_000_000.0
OLD = NOW - 10 * 86400
NEW = NOW - 2 * 86400


def _layer(root: Path, name: str, mtime: float, short: str = "") -> Path:
    folder = root / "overlay2" / name
    (folder / "diff").mkdir(parents=True)
    (folder / "diff" / "file").write_bytes(b"x" * 8192)
    if short:
        (folder / "link").write_text(short)
        links = root / "overlay2" / "l"
        links.mkdir(exist_ok=True)
        (links / short).symlink_to(f"../{name}/diff")
    for path in (folder / "diff" / "file", folder / "diff", folder / "link", folder):
        if path.exists():
            os.utime(path, (mtime, mtime), follow_symlinks=False)
    return folder


def _docker_root(tmp_path: Path) -> Path:
    root = tmp_path / "docker"
    (root / "overlay2" / "l").mkdir(parents=True)
    (root / "containers").mkdir()
    return root


def _name(char: str, suffix: str = "") -> str:
    return char * 64 + suffix


def test_layerdb_references_reads_image_and_container_layers(tmp_path):
    root = _docker_root(tmp_path)
    image = root / "image/overlay2/layerdb/sha256/abc"
    mount = root / "image/overlay2/layerdb/mounts/def"
    image.mkdir(parents=True)
    mount.mkdir(parents=True)
    (image / "cache-id").write_text(_name("a") + "\n")
    (mount / "mount-id").write_text(_name("b"))
    (mount / "init-id").write_text(_name("b", "-init"))
    assert tool.layerdb_references(root) == {_name("a"), _name("b"), _name("b", "-init")}


def test_missing_layerdb_refuses(tmp_path):
    with pytest.raises(RuntimeError, match="layer database"):
        tool.layerdb_references(_docker_root(tmp_path))


def test_only_old_unreferenced_layers_are_orphans(tmp_path):
    root = _docker_root(tmp_path)
    _layer(root, _name("a"), OLD)            # referenced
    _layer(root, _name("b"), OLD)            # orphan
    _layer(root, _name("c"), NEW)            # unreferenced but too recent
    _layer(root, "not-a-layer-name", OLD)    # unknown name: never touched
    orphans, total = tool.orphan_layers(root, {_name("a")}, NOW)
    assert [item["name"] for item in orphans] == [_name("b")]
    assert total == 4


class _Done:
    returncode = 0
    stdout = "Vacuuming done"
    stderr = ""


def test_apply_removes_orphan_its_short_link_and_truncates_big_logs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(tool.subprocess, "run", lambda args, **_: calls.append(args) or _Done())
    monkeypatch.setattr(tool, "LOG_CAP_BYTES", 1024)
    root = _docker_root(tmp_path)
    _layer(root, _name("a"), OLD, short="KEEP")
    _layer(root, _name("b"), OLD, short="GONE")
    log = root / "containers/one/one-json.log"
    log.parent.mkdir()
    log.write_bytes(b"x" * 4096)
    report = tool.run(True, root, NOW, references={_name("a")})
    assert report["removed_layers"] == 1 and report["removed_bytes"] > 0
    assert log.stat().st_size == 0
    assert calls == [["journalctl", "--vacuum-size=1G"]]
    assert (root / "overlay2" / _name("a")).is_dir()
    assert (root / "overlay2/l/KEEP").is_symlink()
    assert not (root / "overlay2" / _name("b")).exists()
    assert not os.path.lexists(root / "overlay2/l/GONE")


def test_report_mode_deletes_nothing(tmp_path):
    root = _docker_root(tmp_path)
    _layer(root, _name("a"), OLD)
    _layer(root, _name("b"), OLD)
    report = tool.run(False, root, NOW, references={_name("a")})
    assert report["orphans"] == 1 and report["removed_layers"] == 0
    assert (root / "overlay2" / _name("b")).is_dir()


def test_refuses_when_almost_everything_looks_unreferenced(tmp_path):
    root = _docker_root(tmp_path)
    for char in "abcdefghijk":
        _layer(root, _name(char), OLD)
    with pytest.raises(RuntimeError, match="refusing"):
        tool.run(True, root, NOW, references={_name("a")})


def test_refuses_without_any_reference(tmp_path):
    root = _docker_root(tmp_path)
    _layer(root, _name("a"), OLD)
    with pytest.raises(RuntimeError, match="No referenced"):
        tool.run(True, root, NOW, references=set())


def test_oversized_logs_are_listed(tmp_path):
    root = _docker_root(tmp_path)
    small = root / "containers/one/one-json.log"
    large = root / "containers/two/two-json.log"
    small.parent.mkdir()
    large.parent.mkdir()
    small.write_bytes(b"x" * 10)
    large.write_bytes(b"x" * 2048)
    assert [item["path"] for item in tool.oversized_logs(root, cap=1024, total_cap=10**9)] == [str(large)]


def test_largest_logs_go_until_all_fit_in_the_total_budget(tmp_path):
    root = _docker_root(tmp_path)
    for name, size in (("a", 600), ("b", 500), ("c", 300), ("d", 100)):
        (root / "containers" / name).mkdir()
        (root / "containers" / name / f"{name}-json.log").write_bytes(b"x" * size)
    chosen = tool.oversized_logs(root, cap=10**6, total_cap=500)  # 1500 -> 900 -> 400
    assert [Path(item["path"]).name for item in chosen] == ["a-json.log", "b-json.log"]


def test_buildkit_references_keep_named_layers(tmp_path):
    root = _docker_root(tmp_path)
    (root / "buildkit").mkdir()
    short = "q42d10pzwbmywyi6iwjv8ziyd"
    (root / "buildkit/snapshots.db").write_bytes(b"\x00" + _name("c").encode() + b"\x00" + short.encode())
    (root / "buildkit/content/blobs").mkdir(parents=True)
    (root / "buildkit/content/blobs/x").write_bytes(_name("d").encode())
    assert tool.buildkit_references(root, {_name("c"), _name("d"), short}) == {_name("c"), short}


def test_current_short_layer_names_are_recognised(tmp_path):
    root = _docker_root(tmp_path)
    _layer(root, "zfwtjzrdhghgyg105bcdxkl9k", OLD)
    _layer(root, "qs6godrgxu0myhtindtt4fvbq", OLD)
    _layer(root, "qs6godrgxu0myhtindtt4fvbq-init", OLD)
    orphans, _ = tool.orphan_layers(root, {"zfwtjzrdhghgyg105bcdxkl9k"}, NOW)
    assert sorted(item["name"] for item in orphans) == ["qs6godrgxu0myhtindtt4fvbq", "qs6godrgxu0myhtindtt4fvbq-init"]


def test_lower_chain_of_kept_layers_is_kept(tmp_path):
    root = _docker_root(tmp_path)
    _layer(root, _name("a"), OLD, short="AAA")
    _layer(root, _name("b"), OLD, short="BBB")
    top = _layer(root, _name("c"), OLD, short="CCC")
    (top / "lower").write_text("l/BBB")
    (root / "overlay2" / _name("b") / "lower").write_text("l/AAA")
    assert tool.with_lower_layers(root, {_name("c")}) == {_name("a"), _name("b"), _name("c")}
