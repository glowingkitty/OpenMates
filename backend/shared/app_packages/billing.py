"""Credit rule for request groups served only by installed app package providers.

Invariant (feature.instance-app-packages: no-installed-provider-charges): a
successful request group is not charged only when it has results and every
provider that contributed results is an installed provider according to the
server's own registry. Each result must carry a ``provider_id`` that the
registry lists, and the group's ``providers`` list must contain only such ids.
Any other field in skill output (for example a "free" or "exempt" flag) is
ignored. Built-in-only and mixed groups are charged exactly as before, and a
result whose group count differs from the request count exempts nothing.

A skill served through the generic ``skill.requests@1`` contract has no built-in
provider at all (the loader only accepts such a target while it ships with none),
so when the registry lists only generic-contract providers for it, none of its
request groups is charged, including groups where every provider failed.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from backend.shared.app_packages.generic_contract import GENERIC_CONTRACTS
from backend.shared.app_packages.loader import get_installed_providers, is_installed_provider


def served_only_by_installed_providers(app_id: str, skill_id: str) -> bool:
    """True when the registry serves this skill only through generic-contract providers."""
    providers = get_installed_providers(app_id, skill_id)
    return bool(providers) and all(provider.contract in GENERIC_CONTRACTS for provider in providers)


def is_installed_only_group(app_id: str, skill_id: str, group: Any) -> bool:
    if not isinstance(group, dict):
        return False
    if served_only_by_installed_providers(app_id, skill_id):
        return True
    results = group.get("results")
    providers = group.get("providers")
    if not isinstance(results, list) or not results or not isinstance(providers, list) or not providers:
        return False
    if not all(is_installed_provider(app_id, skill_id, provider_id) for provider_id in providers):
        return False
    return all(
        isinstance(result, dict) and result.get("provider_id") in providers
        and is_installed_provider(app_id, skill_id, result.get("provider_id"))
        for result in results
    )


def count_installed_only_groups(app_id: str, skill_id: str, groups: Optional[Iterable[Any]]) -> int:
    return sum(1 for group in groups or [] if is_installed_only_group(app_id, skill_id, group))


def result_groups(result: Any) -> list:
    """Extract grouped request results from a skill response (optionally wrapped in ``data``)."""
    if not isinstance(result, dict):
        return []
    data = result.get("data", result)
    groups = data.get("results") if isinstance(data, dict) else None
    return groups if isinstance(groups, list) else []


def installed_only_group_indices(app_id: str, skill_id: str, result: Any) -> set[int]:
    """Indices of result groups served only by installed providers."""
    return {
        index
        for index, group in enumerate(result_groups(result))
        if is_installed_only_group(app_id, skill_id, group)
    }

def chargeable_request_indices(app_id: str, skill_id: str, request_count: int, result: Any) -> list[int]:
    """Request indices that are charged: every request except installed-only groups.

    Usage rows and per-request credit splits must reference these indices so a
    charged built-in group keeps its own index when an earlier group is exempt.
    A group is only exempt when the result has exactly one group per request.
    """
    if served_only_by_installed_providers(app_id, skill_id):
        # No built-in provider exists for this skill: nothing is chargeable.
        return []
    groups = result_groups(result)
    if len(groups) != request_count:
        # Groups cannot be matched to requests one-to-one: charge every request.
        return list(range(request_count))
    exempt = installed_only_group_indices(app_id, skill_id, result)
    return [index for index in range(request_count) if index not in exempt]

def chargeable_request_units(app_id: str, skill_id: str, request_count: int, result: Any) -> int:
    """Subtract installed-only groups from the request count used for charging."""
    return len(chargeable_request_indices(app_id, skill_id, request_count, result))

def all_groups_installed_only(app_id: str, skill_id: str, request_count: int, result: Any) -> bool:
    """True only when there is at least one request and every request group is installed-only."""
    return request_count > 0 and not chargeable_request_indices(app_id, skill_id, request_count, result)


def even_request_charge_items(
    app_id: str, skill_id: str, input_data: Any, result: Any, credits_charged: int,
) -> list[tuple[int, int]]:
    """Split credits evenly over charged request indices (remainder on the last).

    Installed-provider-only groups are skipped, so each usage row keeps the
    index of the request it actually charges. Without such groups this is the
    original ``range(request_count)`` split used by the REST and workflow paths.
    """
    requests = input_data.get("requests") if isinstance(input_data, dict) else None
    request_count = len(requests) if isinstance(requests, list) else 1
    indices = chargeable_request_indices(app_id, skill_id, request_count, result)
    units = len(indices)
    per_request_credits = credits_charged // units if units > 0 else credits_charged
    credits_remainder = credits_charged - (per_request_credits * units)
    return [
        (index, per_request_credits + (credits_remainder if position == units - 1 else 0))
        for position, index in enumerate(indices)
    ]
