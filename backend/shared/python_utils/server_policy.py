"""Hard-coded hosting-region policy for AI model servers.

Rules enforced in code (not only in provider YAML):
1. Servers hosted in or operated from China (CN/HK/MO) are never used.
2. With the default "eu" preference, EU servers are always tried before any
   non-EU server (US, global, ...); the relative order of non-EU servers is kept.
   The first server of that order is the effective default.
3. With the user's "global" ("Fastest, global") preference, the model's
   ``fastest_server`` (if declared) is tried first, then the remaining servers
   in the "eu" order. Blocked servers stay excluded in both modes.

A server entry in ``backend/providers/*.yml`` carries ``region`` (EU/US/global
or a cloud region id) and, where the hosting jurisdiction is known, an ISO
3166-1 alpha-2 ``country``. For OpenRouter, the upstream hosts are filtered with
``provider.ignore`` so a request can never be routed to a blocked operator.
"""

from typing import Any, Dict, List, Mapping, Optional

REGION_PREFERENCES = ("eu", "global")

BLOCKED_COUNTRIES = frozenset({"CN", "HK", "MO"})

EU_COUNTRIES = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES",
    "SE", "NO", "IS", "LI", "CH",
})

# Cloud region ids that appear as ``region`` in provider YAML.
_REGION_ID_COUNTRY = {"eu-central-1": "DE"}

# OpenRouter upstream operators that are Chinese companies or host in CN/HK/MO.
# Derived from https://openrouter.ai/api/v1/providers (headquarters/datacenters)
# plus known Chinese operators that register a Singapore headquarters. Re-check
# with backend/scripts/check_openrouter_upstream_regions.py.
OPENROUTER_BLOCKED_PROVIDERS = (
    "alibaba", "baidu", "bytedance", "deepseek", "minimax", "moonshotai",
    "nex-agi", "siliconflow", "stepfun", "streamlake", "tencent", "xiaomi",
    "z-ai", "zhipu",
)


def server_country(server: Mapping[str, Any]) -> Optional[str]:
    """Return the server's ISO country code, if declared or implied."""
    country = server.get("country")
    if isinstance(country, str) and len(country) == 2:
        return country.upper()
    region = str(server.get("region") or "").strip()
    if region.lower() in _REGION_ID_COUNTRY:
        return _REGION_ID_COUNTRY[region.lower()]
    return None


def is_server_blocked(server: Mapping[str, Any]) -> bool:
    """True when the server is hosted in or operated from a blocked country."""
    region = str(server.get("region") or "").strip().upper()
    return server_country(server) in BLOCKED_COUNTRIES or region in BLOCKED_COUNTRIES


def server_region_rank(server: Mapping[str, Any]) -> int:
    """0 = EU, 1 = anything else (US, global, ...)."""
    country = server_country(server)
    region = str(server.get("region") or "").strip().lower()
    return 0 if region == "eu" or (country is not None and country in EU_COUNTRIES) else 1


def normalize_region_preference(preference: Optional[str]) -> str:
    """Return a valid preference; anything unknown means the privacy-first "eu"."""
    return preference if preference in REGION_PREFERENCES else "eu"


def order_servers(
    servers: List[Mapping[str, Any]],
    preference: Optional[str] = "eu",
    fastest_server_id: Optional[str] = None,
) -> List[Mapping[str, Any]]:
    """Drop blocked servers; order EU first, or fastest first for "global"."""
    allowed = [s for s in servers if isinstance(s, Mapping) and not is_server_blocked(s)]
    ordered = sorted(allowed, key=server_region_rank)
    if normalize_region_preference(preference) == "global" and fastest_server_id:
        ordered.sort(key=lambda s: s.get("id") != fastest_server_id)
    return ordered


def effective_default_server_id(
    model_config: Mapping[str, Any], preference: Optional[str] = "eu",
) -> Optional[str]:
    """Best allowed server id for a catalog model, regardless of YAML default."""
    ordered = order_servers(
        list(model_config.get("servers") or []), preference, model_config.get("fastest_server"),
    )
    return ordered[0].get("id") if ordered else None


def apply_openrouter_provider_policy(overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return OpenRouter ``provider`` preferences that can never reach blocked hosts."""
    provider: Dict[str, Any] = dict(overrides or {})
    for key in ("only", "order"):
        requested = {str(p).lower() for p in provider.get(key) or []}
        blocked = requested & set(OPENROUTER_BLOCKED_PROVIDERS)
        if blocked:
            raise ValueError(f"OpenRouter provider.{key} names blocked host(s): {sorted(blocked)}")
    ignore = [str(p) for p in provider.get("ignore") or []]
    provider["ignore"] = list(dict.fromkeys([*ignore, *OPENROUTER_BLOCKED_PROVIDERS]))
    return provider
