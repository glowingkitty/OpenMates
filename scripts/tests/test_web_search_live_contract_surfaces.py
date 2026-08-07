#!/usr/bin/env python3
"""Opt-in live Web Search contract surface proof.

This pytest wrapper maps the live SDK/CLI parity smoke runner to contract
assertions without making ordinary unit-test runs hit the dev API. Set
OPENMATES_LIVE_SMOKE=1 and use a logged-in CLI session before running.
Architecture: contracts/features/app-skills/web-search/contract.yml
"""

from __future__ import annotations

import os
import subprocess

import pytest


@pytest.fixture(scope="module")
def web_search_live_contract_smoke() -> str:
    if os.getenv("OPENMATES_LIVE_SMOKE") != "1":
        pytest.skip("Set OPENMATES_LIVE_SMOKE=1 to run live Web Search contract proof")

    result = subprocess.run(
        [
            "python3",
            "scripts/sdk_cli_parity_live_smoke.py",
            "--api-url",
            os.getenv("OPENMATES_API_URL", "https://api.dev.openmates.org"),
            "--name",
            "web-search-contract-live-smoke",
            "--web-search-only",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


# contract-test: direct surface=rest_api assertions=web-search.request.validated,web-search.request.ids-correlated,web-search.response.sanitized,web-search.results.bounded,web-search.no-results.explicit,web-search.provider-error.visible,web-search.secrets.never-exposed,web-search.surface-parity
def test_web_search_rest_api_live_contract_parity(web_search_live_contract_smoke: str) -> None:
    assert '"rest"' in web_search_live_contract_smoke


# contract-test: direct surface=cli assertions=web-search.request.validated,web-search.request.ids-correlated,web-search.response.sanitized,web-search.results.bounded,web-search.no-results.explicit,web-search.provider-error.visible,web-search.secrets.never-exposed,web-search.surface-parity
def test_web_search_cli_live_contract_parity(web_search_live_contract_smoke: str) -> None:
    assert '"cli"' in web_search_live_contract_smoke


# contract-test: direct surface=sdks.npm assertions=web-search.request.validated,web-search.request.ids-correlated,web-search.response.sanitized,web-search.results.bounded,web-search.no-results.explicit,web-search.provider-error.visible,web-search.secrets.never-exposed,web-search.surface-parity
def test_web_search_npm_sdk_live_contract_parity(web_search_live_contract_smoke: str) -> None:
    assert '"npm"' in web_search_live_contract_smoke


# contract-test: direct surface=sdks.pip assertions=web-search.request.validated,web-search.request.ids-correlated,web-search.response.sanitized,web-search.results.bounded,web-search.no-results.explicit,web-search.provider-error.visible,web-search.secrets.never-exposed,web-search.surface-parity
def test_web_search_pip_sdk_live_contract_parity(web_search_live_contract_smoke: str) -> None:
    assert '"python"' in web_search_live_contract_smoke
