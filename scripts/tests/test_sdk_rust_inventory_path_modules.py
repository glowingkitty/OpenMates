# contract-test-file: tooling
"""Rust SDK inventory must see public `#[path]` submodules under their real path.

Regression: `web_connected_accounts::tokens` lives in
`web_connected_accounts_tokens.rs`; the inventory namespaced it by file name,
dropped it, and the strict sdk-conformance matrix check failed.
"""
from pathlib import Path

from scripts import sessions
from scripts.sdk_rust_inventory import discover


def write_crate(root: Path) -> None:
    src = root / "packages/openmates-rust/src"
    src.mkdir(parents=True)
    (src / "lib.rs").write_text("pub mod accounts;\npub mod client;\n")
    (src / "accounts.rs").write_text(
        '#[path = "accounts_tokens.rs"]\npub mod tokens;\n'
        '#[path = "accounts_private.rs"]\nmod private;\n'
        "pub fn plan() {}\n"
    )
    (src / "accounts_tokens.rs").write_text("pub fn merge() {}\n")
    (src / "accounts_private.rs").write_text("pub fn hidden() {}\n")
    (src / "client.rs").write_text('#[path = "client/view_impl.rs"]\npub mod view;\n')
    (src / "client").mkdir()
    (src / "client/view_impl.rs").write_text("pub fn render() {}\n")


def test_public_path_module_is_inventoried_under_its_module_path(tmp_path):
    write_crate(tmp_path)
    names = discover(tmp_path)
    assert "accounts.tokens.merge" in names
    assert "accounts_tokens.merge" not in names
    assert "accounts.plan" in names
    # Private path modules are not recovered as public API.
    assert not any(name.endswith(".hidden") for name in names)
    # Files already under a public root keep their established names.
    assert "client.view_impl.render" in names
    assert "client.view.render" not in names


def test_deploy_guard_only_triggers_on_app_metadata_or_generators():
    assert sessions._should_check_generated_sdk_app_skills(["backend/apps/pdf/app.yml"])
    assert sessions._should_check_generated_sdk_app_skills(["scripts/generate_rust_sdk_apps.py"])
    assert not sessions._should_check_generated_sdk_app_skills(["backend/apps/pdf/skills/read.py"])
