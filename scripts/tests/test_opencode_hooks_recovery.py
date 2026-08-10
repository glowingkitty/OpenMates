#!/usr/bin/env python3
"""OpenCode hook recovery contracts.

These tests execute the project hook's exported test helpers through Node.
They protect the merged-worktree recovery path that lets an integrated
OpenCode chat run sessions.py start/spawn-chat instead of getting trapped in
the routing guard loop.
Run: python3 -m pytest scripts/tests/test_opencode_hooks_recovery.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


# contract-test-file: tooling


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_hook_assertion(script: str) -> None:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_routing_failure_allows_session_recovery_commands() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { routingFailureForTest } = OpenMatesHooks.test;
        for (const command of [
          'python3 scripts/sessions.py start --mode testing --task "recover"',
          'python3 scripts/sessions.py spawn-chat --help',
          'python3 scripts/sessions.py worktree repair --opencode-session ses_parent',
          'python3 scripts/sessions.py end --session 178c --force',
        ]) {
          assert.equal(
            routingFailureForTest({ tool: 'bash', sessionID: 'ses_parent', command }).decision,
            'allow_recovery',
            command,
          );
        }
        """
    )


def test_merged_worktree_recovery_message_names_force_end() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { routingDecisionForTest } = OpenMatesHooks.test;
        const result = routingDecisionForTest({
          session: { worktree: { status: 'merged', merged_commit: 'b2b533062cc16' } },
        });

        assert.equal(result.decision, 'merged_worktree');
        assert.match(result.message, /end --force/);
        """
    )
