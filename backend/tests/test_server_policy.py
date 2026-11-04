"""Hosting-region policy: no CN/HK/MO hosts, EU before non-EU, countries declared."""

# contract-test-file: infrastructure

import glob
from pathlib import Path

import pytest
import yaml

from backend.shared.python_utils.server_policy import (
    BLOCKED_COUNTRIES,
    OPENROUTER_BLOCKED_PROVIDERS,
    apply_openrouter_provider_policy,
    effective_default_server_id,
    is_server_blocked,
    order_servers,
    server_region_rank,
)

PROVIDER_FILES = sorted(glob.glob(str(Path(__file__).parents[1] / "providers/*.yml")))


def _catalog_models():
    for path in PROVIDER_FILES:
        provider = yaml.safe_load(Path(path).read_text())
        for model in provider.get("models") or []:
            if model.get("servers"):
                yield provider["provider_id"], model


def test_order_servers_drops_blocked_and_puts_eu_first():
    servers = [
        {"id": "us", "region": "US", "country": "US"},
        {"id": "cn", "region": "global", "country": "CN"},
        {"id": "hk", "region": "HK"},
        {"id": "de", "region": "eu-central-1"},
        {"id": "fr", "region": "global", "country": "FR"},
        {"id": "glob", "region": "global"},
    ]
    assert [s["id"] for s in order_servers(servers)] == ["de", "fr", "us", "glob"]
    assert effective_default_server_id({"default_server": "us", "servers": servers}) == "de"
    assert server_region_rank({"region": "EU"}) == 0
    assert is_server_blocked({"region": "global", "country": "cn"})


def test_openrouter_policy_always_ignores_blocked_hosts():
    provider = apply_openrouter_provider_policy({"only": ["baseten"], "ignore": ["x"]})
    assert provider["only"] == ["baseten"]
    assert provider["ignore"][0] == "x"
    assert set(OPENROUTER_BLOCKED_PROVIDERS) <= set(provider["ignore"])
    assert set(apply_openrouter_provider_policy(None)["ignore"]) == set(OPENROUTER_BLOCKED_PROVIDERS)
    with pytest.raises(ValueError):
        apply_openrouter_provider_policy({"order": ["DeepSeek"]})


@pytest.mark.parametrize("provider_id,model", list(_catalog_models()), ids=lambda v: v if isinstance(v, str) else v["id"])
def test_catalog_servers_follow_policy(provider_id, model):
    servers = model["servers"]
    for server in servers:
        assert server.get("country"), f"{provider_id}/{model['id']}/{server['id']}: missing country"
        assert len(server["country"]) == 2
        assert server["country"].upper() not in BLOCKED_COUNTRIES
        assert not is_server_blocked(server)
    assert [s["id"] for s in servers] == [s["id"] for s in order_servers(servers)], "servers must be EU-first"
    assert model["default_server"] == effective_default_server_id(model), "default_server must be the best allowed host"
