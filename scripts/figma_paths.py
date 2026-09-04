#!/usr/bin/env python3
"""Resolve private Figma state across managed OpenMates worktrees.

Figma credentials and the generated design index belong to the root checkout,
not to ephemeral agent worktrees. This helper keeps every Figma command pointed
at that shared control-plane state without copying or exposing credentials.
"""

from __future__ import annotations

from pathlib import Path


MANAGED_WORKTREE_DIRECTORIES = frozenset({".openmates-agent-worktrees", ".agent-worktrees"})


def resolve_control_plane_root(checkout_root: Path) -> Path:
    """Return the root checkout that owns shared private tooling state."""
    if checkout_root.parent.name in MANAGED_WORKTREE_DIRECTORIES:
        return checkout_root.parent.parent
    return checkout_root
