# contract-test: infrastructure
"""The hosted smoke selector must reach its separate workload and marker mode."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_modules(monkeypatch):
    scripts = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(scripts))
    for name, path in (("ci_environment", scripts / "ci_environment.py"),
                       ("capacity_target_selector_runner", scripts / "ci_run_tests.py")):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        if name == "ci_environment":
            environment = module
        else:
            runner = module

    return environment, runner


# contract-test: infrastructure
def test_target_smoke_selector_reaches_its_profile_and_not_full_target(monkeypatch):
    environment, runner = _load_modules(monkeypatch)
    smoke = runner.TARGET_SMOKE_SPEC
    assert smoke in environment.STORAGE_CAPACITY_SPECS
    assert smoke in environment.CAPACITY_WORKLOAD_SPECS
    assert smoke in runner.CAPACITY_WORKLOAD_SPECS
    assert runner.capacity_selector_environment(smoke) == {
        "E2E_STORAGE_CAPACITY": "1",
        "E2E_STORAGE_CAPACITY_TARGET": "0",
        "E2E_STORAGE_CAPACITY_TARGET_SMOKE": "1",
    }
    assert runner.capacity_selector_environment("storage-capacity-target.spec.ts") == {
        "E2E_STORAGE_CAPACITY": "1",
        "E2E_STORAGE_CAPACITY_TARGET": "1",
        "E2E_STORAGE_CAPACITY_TARGET_SMOKE": "0",
    }
    assert runner.capacity_selector_environment("unrelated.spec.ts") == {}


# contract-test: infrastructure
def test_descriptor_loader_uses_exact_subject_source_not_tooling_package(tmp_path, monkeypatch):
    _, runner = _load_modules(monkeypatch)
    subject = tmp_path / "subject"
    source = subject / "backend/shared/testing/capacity_target.py"
    source.parent.mkdir(parents=True)
    source.write_text("CACHE_KEY = 'subject-descriptor'\nMAX_TTL = 73\n", encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", subject)
    cached = ModuleType("backend.shared.testing.capacity_target")
    cached.CACHE_KEY = "wrong-cached-module"
    monkeypatch.setitem(sys.modules, "backend.shared.testing.capacity_target", cached)

    loaded = runner.load_subject_capacity_target()
    assert Path(loaded.__file__).resolve() == source.resolve()
    assert loaded.CACHE_KEY == "subject-descriptor"
    assert loaded.MAX_TTL == 73
    assert sys.modules["backend.shared.testing.capacity_target"] is cached

    source.unlink()
    source.symlink_to(tmp_path / "outside.py")
    try:
        runner.load_subject_capacity_target()
    except RuntimeError as exc:
        assert "subject source unavailable" in str(exc)
    else:
        raise AssertionError("Subject descriptor loader followed a symlink")
