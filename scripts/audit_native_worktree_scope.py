#!/usr/bin/env python3
"""Audit native-worktree scope and preserved deploy safety contracts.

This deterministic check keeps presence implementation outside the binding
change, verifies the disposable integration markers, and ensures the previous
worktree deploy safety outcomes remain part of the executable specification.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


REQUIRED_SNIPPETS: dict[str, tuple[str, ...]] = {
    "scripts/sessions.py": (
        'INTEGRATION_WORKTREE_PREFIX = "integration-"',
        '"HEAD:refs/heads/dev"',
        'validate_worktree_binding_mode(session) == "native"',
        '"disposable_integration"',
    ),
    ".opencode/plugins/openmates-hooks.js": (
        "bindNativeWorktree",
        "nativeBindingDecision",
        "OPENMATES_NATIVE_WORKTREE_MODE",
    ),
    "docs/specs/opencode-native-worktree-binding/spec.yml": (
        "id: agent-worktree-deploy",
        "verification_ids: [T-REGRESSION-WORKTREE",
        "Implementing docs/specs/agent-presence-coordination/spec.yml",
    ),
    "docs/specs/agent-presence-coordination/spec.yml": (
        "id: opencode-native-worktree-binding",
        "relationship: blocked_by",
        "approved_by_user: false",
    ),
}


FORBIDDEN_PRESENCE_SNIPPETS = (
    "presence registry",
    "session.status",
    "presence heartbeat",
)


def main() -> int:
    failures: list[str] = []
    for relative_path, snippets in REQUIRED_SNIPPETS.items():
        path = PROJECT_ROOT / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"{relative_path}: cannot read file: {exc}")
            continue
        for snippet in snippets:
            if snippet not in text:
                failures.append(f"{relative_path}: missing {snippet!r}")

    implementation_text = "\n".join(
        (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in ("scripts/sessions.py", ".opencode/plugins/openmates-hooks.js")
    ).lower()
    for snippet in FORBIDDEN_PRESENCE_SNIPPETS:
        if snippet in implementation_text:
            failures.append(f"implementation unexpectedly contains deferred presence marker {snippet!r}")

    if failures:
        print("FAIL native worktree scope audit")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("PASS native worktree scope audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
