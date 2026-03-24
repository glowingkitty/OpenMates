#!/usr/bin/env python3
"""
scripts/_opencode_utils.py — DEPRECATED backwards-compatibility shim.

All callers should import from _claude_utils instead:
    from _claude_utils import run_claude_session

This shim will be removed once all external references are confirmed updated.
Migrated 2026-03-24.
"""

import warnings as _warnings

from _claude_utils import run_claude_session

_warnings.warn(
    "_opencode_utils is deprecated — use _claude_utils.run_claude_session instead",
    DeprecationWarning,
    stacklevel=2,
)


def run_opencode_session(*args, **kwargs):
    """Deprecated wrapper — calls run_claude_session."""
    _warnings.warn(
        "run_opencode_session is deprecated — use run_claude_session from _claude_utils",
        DeprecationWarning,
        stacklevel=2,
    )
    return run_claude_session(*args, **kwargs)
