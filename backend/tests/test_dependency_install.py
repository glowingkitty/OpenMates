# backend/tests/test_dependency_install.py
"""E2B test runs of a Node project install its dependencies before the server starts."""
from backend.apps.code.skills.dependency_install import installs_packages, with_dependency_install
from backend.shared.python_schemas.code_test_run import TestCommand, TestRunSpec

FILES = ["web-app/package.json", "web-app/vite.config.js", "web-app/tests/recipe.spec.js"]


def _spec(setup=None, cwd="web-app"):
    return TestRunSpec.model_validate({
        "kind": "browser",
        "setup_commands": setup or [],
        "server": {"command": {"argv": ["npm", "run", "dev"], "cwd": cwd},
                   "ready_url": "http://localhost:5173"},
        "test_command": {"argv": ["npx", "playwright", "test"], "cwd": cwd},
    })


# contract-test: supporting surface=rest_api assertions=projects.agentic.test-run-installs-dependencies
def test_server_without_install_gets_npm_install_first():
    spec = with_dependency_install(_spec(), FILES)
    assert [(c.argv[:2], c.cwd) for c in spec.setup_commands] == [(["npm", "install"], "web-app")]


# contract-test: supporting surface=rest_api assertions=projects.agentic.test-run-installs-dependencies
def test_existing_install_or_missing_manifest_is_left_alone():
    own = [{"argv": ["bash", "-lc", "npm ci && npx playwright install"], "cwd": "web-app"}]
    assert len(with_dependency_install(_spec(own), FILES).setup_commands) == 1
    assert with_dependency_install(_spec(cwd="."), FILES).setup_commands == []


# contract-test: supporting surface=rest_api assertions=projects.agentic.test-run-installs-dependencies
def test_install_detection_covers_common_package_managers():
    assert installs_packages(TestCommand(argv=["pnpm", "i"]))
    assert installs_packages(TestCommand(argv=["yarn"]))
    assert not installs_packages(TestCommand(argv=["npm", "run", "build"]))
