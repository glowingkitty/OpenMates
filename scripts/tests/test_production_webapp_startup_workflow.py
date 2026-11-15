# contract-test-file: tooling
"""The post-deploy production web app check must run for real Vercel production deploys.

Vercel reports the web app's production environment as
"Production – open-mates-webapp". When the workflow matched only "Production",
every production deploy skipped the browser check without any alert.
"""
from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/production-webapp-startup.yml"


def _job_condition() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["browser-startup"]["if"]


def test_runs_on_vercel_webapp_production_environment() -> None:
    condition = _job_condition()
    assert "github.event.deployment.environment == 'Production – open-mates-webapp'" in condition


def test_still_limited_to_web_app_urls() -> None:
    condition = _job_condition()
    assert "startsWith(github.event.deployment_status.environment_url, 'https://open-mates-webapp-')" in condition
    assert "github.event.deployment_status.state == 'success'" in condition
