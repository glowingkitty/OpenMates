#!/usr/bin/env python3
"""Natural-language Project names for real-account and verifier runs.

Runs that create Projects use names a person would give a Project ("Kitchen
renovation"), never timestamps or hex ids: those names are visible in the
account, read badly in recordings and trip number-based checks such as the
composer's sensitive-data preview. A random two-word nickname keeps names
apart without digits. Twin of `frontend/apps/web_app/tests/helpers/project-names.ts`;
rule in `.claude/rules/testing.md` ("Project names").
"""

from __future__ import annotations

import secrets

ADJECTIVES = (
    "amber", "bright", "calm", "cedar", "clear", "coastal", "copper", "crisp", "eastern", "evening",
    "gentle", "golden", "green", "hidden", "island", "lively", "lunar", "maple", "meadow", "misty",
    "morning", "northern", "olive", "quiet", "river", "rustic", "silver", "snowy", "sunny", "velvet",
)
NOUNS = (
    "harbor", "garden", "valley", "orchard", "lantern", "bridge", "cabin", "canyon", "forest", "meadow",
    "library", "market", "studio", "workshop", "terrace", "lighthouse", "pond", "trail", "village", "kitchen",
    "balcony", "atelier", "courtyard", "greenhouse", "harvest", "journey", "notebook", "compass", "island", "summit",
)


def natural_nickname() -> str:
    """A random two-word nickname such as "quiet harbor"."""
    return f"{secrets.choice(ADJECTIVES)} {secrets.choice(NOUNS)}"


def natural_project_name(topic: str) -> str:
    """`natural_project_name("Kitchen renovation")` -> "Kitchen renovation: quiet harbor"."""
    return f"{topic}: {natural_nickname()}"
