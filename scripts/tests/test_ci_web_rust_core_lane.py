"""Engineering test: the web-rust-core-* CI lane builds the Rust core package and an
opt-in web app in the same job, and never applies to other specs."""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/isolated-tests.yml"


def _job():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return next(job for job in workflow["jobs"].values() if "CI_LANE_WEB_RUST_CORE" in job.get("env", {}))


# contract-test: infrastructure
def test_lane_selector_is_scoped_to_web_rust_core_specs():
    selector = _job()["env"]["CI_LANE_WEB_RUST_CORE"]
    assert "inputs.mode == 'e2e'" in selector
    assert "startsWith(inputs.specs_json, '[\"web-rust-core-')" in selector
    assert "inputs.web_rust_core == 'true'" in selector


# contract-test: infrastructure
def test_package_build_precedes_web_build_and_enables_the_flag():
    steps = _job()["steps"]
    names = [step.get("name") for step in steps]
    package = names.index("Build opt-in web Rust core package")
    assert package < names.index("Generate UI build inputs once") < names.index("Build local web app")
    build = steps[package]
    assert build["if"] == "env.CI_LANE_WEB_RUST_CORE == 'true'"
    assert "build-rust-core-web.mjs" in build["run"]
    assert "VITE_OPENMATES_RUST_CORE=1" in build["run"]
    assert "OPENMATES_RUST_CORE_PKG=" in build["run"]
    # Prepared (flag-OFF) web artifacts are never reused for this lane.
    assert "env.CI_LANE_WEB_RUST_CORE == 'true'" in steps[names.index("Build local web app")]["if"]
