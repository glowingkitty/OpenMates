"""Pure exact-selector guard tests; no package build, processes or browser."""

# contract-test-file: tooling
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from scripts import ci_environment
from scripts import ci_rust_wasm as package

# run_e2e uses the installed harness module's flat import spelling.
sys.modules.setdefault("ci_environment", ci_environment)
runner = importlib.import_module("scripts.ci_run_tests")


class PackageReached(Exception):
    pass


@pytest.mark.parametrize(
    "target", [package.BROWSER_SPEC, package.BROWSER_PASSWORD_SPEC]
)
def test_each_exact_unfiltered_spec_reaches_same_package_hook_before_processes(
    tmp_path, monkeypatch, target
):
    web = tmp_path / "web"
    (web / "tests").mkdir(parents=True)
    (web / "tests" / target).write_text("// inert path admission fixture, never run")
    monkeypatch.setattr(runner, "WEB", web)
    calls = []

    def prepare(root):
        calls.append(root)
        raise PackageReached()

    monkeypatch.setitem(
        sys.modules,
        "ci_rust_wasm",
        SimpleNamespace(prepare_browser_e2e_package=prepare),
    )
    monkeypatch.setitem(
        sys.modules,
        "ci_native_keyring",
        SimpleNamespace(SPEC="cli-rust-native-keyring.spec.ts"),
    )
    with patch.object(
        runner.subprocess, "Popen", side_effect=AssertionError("process forbidden")
    ):
        with pytest.raises(PackageReached):
            runner.run_e2e([target])
    assert calls == [runner.ROOT]


@pytest.mark.parametrize(
    "targets,options",
    [
        (
            [
                "rust-core-browser-session.spec.ts",
                "rust-core-browser-password-entry.spec.ts",
            ],
            {},
        ),
        (["rust-core-browser-password-entry.spec.ts", "ordinary.spec.ts"], {}),
        (["rust-core-browser-password-entry.spec.ts"], {"artifact": True}),
        (["rust-core-browser-password-entry.spec.ts"], {"component": True}),
        (
            ["rust-core-browser-password-entry.spec.ts"],
            {"case_title": "unapproved subset"},
        ),
    ],
)
def test_browser_package_profile_refuses_mixed_or_filtered_or_alternate_modes(
    tmp_path, monkeypatch, targets, options
):
    web = tmp_path / "web"
    (web / "tests").mkdir(parents=True)
    for target in targets:
        (web / "tests" / target).write_text("// inert path fixture")
    monkeypatch.setattr(runner, "WEB", web)
    with patch.object(
        runner.subprocess, "Popen", side_effect=AssertionError("process forbidden")
    ):
        with pytest.raises(ValueError):
            runner.run_e2e(targets, **options)
