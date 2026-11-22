"""Unit tests for scripts/ci_web_rust_core_key.py."""
# contract-test-file: tooling
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_web_rust_core_key as key  # noqa: E402


def make_repo(root: Path) -> None:
    (root / "frontend/apps/web_app/scripts").mkdir(parents=True)
    (root / key.BUILD_SCRIPT).write_text("build")
    (root / "Cargo.lock").write_text("lock")
    (root / "Cargo.toml").write_text('[workspace]\nmembers=[]\n[patch.crates-io]\nfoo = { path = "vendor/foo" }\n')
    for name, deps in (
        ("packages/openmates-browser-bindings", 'a = { path = "../core" }'),
        ("packages/core", ""),
        ("vendor/foo", ""),
        ("packages/unrelated", ""),
    ):
        crate = root / name
        (crate / "src").mkdir(parents=True)
        (crate / "Cargo.toml").write_text(f"[package]\nname='x'\n[dependencies]\n{deps}\n")
        (crate / "src/lib.rs").write_text(name)


def test_deterministic_and_content_sensitive(tmp_path):
    make_repo(tmp_path)
    first = key.compute_key(tmp_path)
    assert first == key.compute_key(tmp_path) and len(first) == 64
    (tmp_path / "packages/core/src/lib.rs").write_text("changed")
    assert key.compute_key(tmp_path) != first


def test_path_dependencies_and_patches_included_unrelated_excluded(tmp_path):
    make_repo(tmp_path)
    names = {p.relative_to(tmp_path).as_posix() for p in key.input_files(tmp_path)}
    assert "packages/core/src/lib.rs" in names and "vendor/foo/src/lib.rs" in names
    assert "packages/unrelated/src/lib.rs" not in names
    base = key.compute_key(tmp_path)
    (tmp_path / "packages/unrelated/src/lib.rs").write_text("other")
    assert key.compute_key(tmp_path) == base


def test_target_dir_ignored(tmp_path):
    make_repo(tmp_path)
    base = key.compute_key(tmp_path)
    (tmp_path / "packages/core/target").mkdir()
    (tmp_path / "packages/core/target/junk").write_text("x")
    assert key.compute_key(tmp_path) == base


def test_real_repo_key_includes_third_party():
    root = Path(__file__).resolve().parents[2]
    names = {p.relative_to(root).as_posix() for p in key.input_files(root)}
    assert any(n.startswith("packages/openmates-rust/") for n in names)
    assert any(n.startswith("packages/third_party/opaque-ke/") for n in names)
    assert len(key.compute_key(root)) == 64
