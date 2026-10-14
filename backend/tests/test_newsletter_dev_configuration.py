"""Resolve the dev-only public newsletter destination without real env/secrets."""
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERRIDE = ROOT / "backend/core/docker-compose.override.yml"


# contract-test: supporting surface=rest_api assertions=newsletter.surface.standalone-confirmation
@pytest.mark.parametrize("configured", [None, "https://preview.example"])
def test_dev_api_and_mail_worker_share_explicit_website_destination(tmp_path, configured):
    services = yaml.safe_load(OVERRIDE.read_text())["services"]
    fixture = {"services": {name: {"image": "example.invalid/unused:proof",
        "environment": {"NEWSLETTER_PUBLIC_WEBSITE_ORIGIN": services[name]["environment"]["NEWSLETTER_PUBLIC_WEBSITE_ORIGIN"]}}
        for name in ["api", "task-worker", "core-worker"]}}
    config = tmp_path / "compose.yml"
    config.write_text(yaml.safe_dump(fixture))
    environment = {key: value for key, value in os.environ.items() if key != "NEWSLETTER_PUBLIC_WEBSITE_ORIGIN"}
    if configured:
        environment["NEWSLETTER_PUBLIC_WEBSITE_ORIGIN"] = configured
    result = subprocess.run(["docker", "compose", "-p", "newsletter-config-proof", "-f", str(config), "config", "--format", "json"],
                            env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, "Synthetic newsletter Compose configuration failed."
    resolved = json.loads(result.stdout)["services"]
    for name in fixture["services"]:
        assert resolved[name]["environment"]["NEWSLETTER_PUBLIC_WEBSITE_ORIGIN"] == (configured or "https://landing.dev.openmates.org")
