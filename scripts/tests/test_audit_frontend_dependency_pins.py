#!/usr/bin/env python3
"""Regression tests for frontend dependency pin auditing.

The audit protects the TipTap/ProseMirror editor bundle and SvelteKit asset
emission from dependency drift that previously broke chat input and font loads.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from audit_frontend_dependency_pins import audit_lockfile  # noqa: E402


def make_lockfile(package_entries: str) -> str:
    return f"""
lockfileVersion: '9.0'

packages:
{package_entries}

snapshots:
"""


def test_audit_accepts_expected_frontend_pins() -> None:
    lockfile = make_lockfile(
        """
  '@sveltejs/kit@2.60.1':
    resolution: {{integrity: sha512-ok}}

  '@tiptap/core@3.26.0':
    resolution: {{integrity: sha512-ok}}

  '@tiptap/pm@3.26.0':
    resolution: {{integrity: sha512-ok}}

  '@tiptap/starter-kit@3.26.0':
    resolution: {{integrity: sha512-ok}}

  prosemirror-model@1.25.7:
    resolution: {{integrity: sha512-ok}}

  prosemirror-view@1.41.8:
    resolution: {{integrity: sha512-ok}}
"""
    )

    assert audit_lockfile(lockfile) == []


def test_audit_rejects_duplicate_prosemirror_model_versions() -> None:
    lockfile = make_lockfile(
        """
  '@sveltejs/kit@2.60.1':
    resolution: {{integrity: sha512-ok}}

  '@tiptap/core@3.26.0':
    resolution: {{integrity: sha512-ok}}

  prosemirror-model@1.25.7:
    resolution: {{integrity: sha512-ok}}

  prosemirror-model@1.25.8:
    resolution: {{integrity: sha512-bad}}

  prosemirror-view@1.41.8:
    resolution: {{integrity: sha512-ok}}
"""
    )

    issues = audit_lockfile(lockfile)

    assert any(issue.package == "prosemirror-model" for issue in issues)


def test_audit_rejects_tiptap_train_drift() -> None:
    lockfile = make_lockfile(
        """
  '@sveltejs/kit@2.60.1':
    resolution: {{integrity: sha512-ok}}

  '@tiptap/core@3.26.1':
    resolution: {{integrity: sha512-bad}}

  prosemirror-model@1.25.7:
    resolution: {{integrity: sha512-ok}}

  prosemirror-view@1.41.8:
    resolution: {{integrity: sha512-ok}}
"""
    )

    issues = audit_lockfile(lockfile)

    assert any(issue.package == "@tiptap/core" for issue in issues)


def test_audit_rejects_sveltekit_asset_regression_version() -> None:
    lockfile = make_lockfile(
        """
  '@sveltejs/kit@2.65.0':
    resolution: {{integrity: sha512-bad}}

  '@tiptap/core@3.26.0':
    resolution: {{integrity: sha512-ok}}

  prosemirror-model@1.25.7:
    resolution: {{integrity: sha512-ok}}

  prosemirror-view@1.41.8:
    resolution: {{integrity: sha512-ok}}
"""
    )

    issues = audit_lockfile(lockfile)

    assert any(issue.package == "@sveltejs/kit" for issue in issues)
