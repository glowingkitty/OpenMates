# backend/tests/test_e2b_code_runner.py
#
# Regression tests for the restricted E2B code runner provider.
# These tests cover dependency command planning without creating a sandbox,
# keeping package installation behavior deterministic and safe to validate in
# the API test container.

from __future__ import annotations

from backend.shared.providers.e2b_code_runner import CodeRunDependencyInstall, CodeRunFile, _dependency_commands


def test_dependency_commands_install_selected_packages_without_manifests() -> None:
    commands = _dependency_commands(
        [CodeRunFile(path="main.py", language="python")],
        [
            CodeRunDependencyInstall(ecosystem="python", packages=("requests", "pandas==2.2.3")),
            CodeRunDependencyInstall(ecosystem="npm", packages=("axios",)),
        ],
    )

    assert commands == [
        ("Installing selected Python packages...", "python -m pip install pandas==2.2.3 requests"),
        ("Installing selected npm packages...", "npm install --ignore-scripts --no-audit --no-fund --package-lock=false axios"),
    ]


def test_dependency_commands_prefer_explicit_manifests() -> None:
    commands = _dependency_commands(
        [
            CodeRunFile(path="main.py", language="python"),
            CodeRunFile(path="requirements.txt", language=""),
            CodeRunFile(path="package.json", language=""),
        ],
        [
            CodeRunDependencyInstall(ecosystem="python", packages=("requests",)),
            CodeRunDependencyInstall(ecosystem="npm", packages=("axios",)),
        ],
    )

    assert commands == [
        ("Installing Python dependencies from requirements.txt...", "python -m pip install -r requirements.txt"),
        ("Installing JavaScript dependencies with npm install --ignore-scripts...", "npm install --ignore-scripts"),
    ]
