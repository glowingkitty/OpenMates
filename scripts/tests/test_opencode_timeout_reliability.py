#!/usr/bin/env python3
# contract-test-file: tooling
"""Regression tests for OpenCode provider-timeout failure visibility.

The test executes the exported hook reducer through Node without starting an
OpenCode server or reading chat content. It protects the explicit failure state
used when the pinned runtime reports an empty ``finish=unknown`` completion.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_openai_stream_has_bounded_chunk_timeout() -> None:
    config = json.loads((PROJECT_ROOT / "opencode.json").read_text(encoding="utf-8"))
    options = config["provider"]["openai"]["options"]

    assert options["headerTimeout"] == 300_000
    assert options["chunkTimeout"] == 120_000


def test_presence_marks_unknown_assistant_completion_as_failed() -> None:
    script = """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { initialPresenceForTest, reducePresenceEventForTest } = OpenMatesHooks.test;
        const current = {
          ...initialPresenceForTest('ses_parent'),
          execution: 'busy',
          turn: 'streaming',
          turn_id: 'msg_assistant',
        };
        const result = reducePresenceEventForTest(current, {
          type: 'message.updated',
          properties: {
            sessionID: 'ses_parent',
            info: {
              id: 'msg_assistant',
              parentID: 'msg_user',
              role: 'assistant',
              finish: 'unknown',
              time: { completed: 1234 },
            },
          },
        });

        assert.equal(result.execution, 'error');
        assert.equal(result.turn, 'failed');
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
