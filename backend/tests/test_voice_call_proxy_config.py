"""Guard signed WebSocket query tokens in the adapted API access log."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


# contract-test: supporting surface=gui.web assertions=video-call.privacy
@pytest.mark.parametrize(("config", "host", "logfile"), [
    ("dev_server", "api.dev.openmates.org", "/var/log/caddy/api.dev.openmates.org.log"),
    ("prod_server", "api.openmates.org", "/var/log/caddy/api.openmates.org.log"),
])
def test_voice_call_api_access_log_removes_signed_query_token(
    config: str, host: str, logfile: str,
) -> None:
    caddy = shutil.which("caddy")
    if caddy is None:
        pytest.skip("caddy is not installed")
    env = os.environ.copy()
    env.setdefault("GANDI_BEARER_TOKEN", "openmates-caddyfile-syntax-check-token")
    result = subprocess.run(
        [caddy, "adapt", "--config", str(ROOT / "deployment" / config / "Caddyfile"), "--adapter", "caddyfile"],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )
    if "module not registered: dns.providers.gandi" in result.stderr:
        pytest.skip("installed caddy lacks the Gandi DNS module")
    assert result.returncode == 0, result.stderr

    adapted = json.loads(result.stdout)
    logger_names = [
        name
        for server in adapted["apps"]["http"]["servers"].values()
        for name in (server.get("logs") or {}).get("logger_names", {}).get(host, [])
    ]
    assert len(logger_names) == 1, f"Expected one API access logger for {host}"
    access_log = adapted["logging"]["logs"][logger_names[0]]
    assert access_log["writer"]["filename"] == logfile
    encoder = access_log["encoder"]
    assert encoder["format"] == "filter"
    assert encoder["wrap"]["format"] == "json"
    uri_filter = encoder["fields"]["request>uri"]
    assert uri_filter["filter"] == "query"
    assert {"type": "delete", "parameter": "token"} in uri_filter["actions"]
