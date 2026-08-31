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
          'python3 scripts/sessions.py chat read ses_worker',
          'python3 scripts/sessions.py chat search ses_worker "worktree"',
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


def test_routing_failure_rejects_chained_chat_recovery_commands() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { routingFailureForTest } = OpenMatesHooks.test;
        for (const command of [
          'python3 scripts/sessions.py chat read ses_worker; python3 scripts/tests.py campaign finish-worker --group g --lease l',
          'python3 scripts/sessions.py chat search ses_worker "worktree" > /tmp/out',
          'python3 scripts/sessions.py chat export ses_worker',
        ]) {
          assert.equal(
            routingFailureForTest({ tool: 'bash', sessionID: 'ses_parent', command }).decision,
            'block',
            command,
          );
        }
        """
    )


def test_worker_edit_gate_blocks_python_rejections() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { workerEditGateDecisionForTest } = OpenMatesHooks.test;
        const calls = [];
        const blocked = workerEditGateDecisionForTest({
          sessionID: 'ses_worker',
          files: ['frontend/test-1.test.ts'],
          run: (command, args, options) => {
            calls.push({ command, args, options });
            return { status: 1, stderr: 'Worker edit blocked', stdout: '' };
          },
        });
        assert.equal(blocked.decision, 'block');
        assert.equal(calls[0].command, 'python3');
        assert.deepEqual(calls[0].args.slice(0, 5), ['scripts/tests.py', 'campaign', 'edit-gate', '--session', 'ses_worker']);
        assert.deepEqual(calls[0].args.slice(-2), ['--file', 'frontend/test-1.test.ts']);
        assert.equal(calls[0].options.timeout, 10000);

        const allowed = workerEditGateDecisionForTest({
          sessionID: 'ses_worker',
          files: ['frontend/test-1.test.ts'],
          run: () => ({ status: 0, stderr: '', stdout: '{"ok": true}' }),
        });
        assert.equal(allowed.decision, 'allow');
        """
    )


def test_worker_bash_gate_allows_scoped_cms_recovery_without_worker_state() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { workerBashGateDecisionForTest } = OpenMatesHooks.test;

        for (const command of [
          'openmates server status',
          'openmates server restart --services cms',
          'openmates server restart --rebuild --services cms',
          'openmates server start --with-overrides --services cms',
        ]) {
          const decision = workerBashGateDecisionForTest({
            sessionID: 'ses_worker',
            command,
            run: () => { throw new Error('worker-state should not be called for approved CMS recovery'); },
          });
          assert.equal(decision.decision, 'allow', command);
          assert.match(decision.message, /approved CMS control-plane recovery command/);
        }

        for (const command of [
          'openmates server restart --services api',
          'openmates server restart --rebuild --services api',
          'openmates server restart --reset-cache --services cms',
          'openmates server start --services cms',
          'openmates server stop',
        ]) {
          const calls = [];
          const decision = workerBashGateDecisionForTest({
            sessionID: 'ses_worker',
            command,
            run: (...args) => {
              calls.push(args);
              return { status: 0, stdout: '{"active_worker": true}', stderr: '' };
            },
          });
          assert.equal(calls.length, 1, command);
          assert.equal(calls[0][0], 'python3', command);
          assert.deepEqual(calls[0][1], ['scripts/tests.py', 'campaign', 'worker-state', '--session', 'ses_worker'], command);
          assert.equal(decision.decision, 'block', command);
        }
        """
    )


def test_worker_edit_gate_blocks_unresolved_paths_for_active_workers() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { routedEditRelativePathForTest, workerEditPathDecisionForTest } = OpenMatesHooks.test;
        const activeRun = () => ({ status: 0, stdout: '{"active_worker": true}', stderr: '' });
        const inactiveRun = () => ({ status: 0, stdout: '{"active_worker": false}', stderr: '' });

        assert.equal(
          routedEditRelativePathForTest('/tmp/worker-a/frontend/test-1.test.ts', '/tmp/worker-a'),
          'frontend/test-1.test.ts',
        );
        assert.equal(
          routedEditRelativePathForTest('/tmp/worker-b/frontend/test-1.test.ts', '/tmp/worker-a'),
          '',
        );

        const blocked = workerEditPathDecisionForTest({
          sessionID: 'ses_worker',
          files: ['/tmp/outside.ts'],
          relativePaths: [],
          run: activeRun,
        });
        assert.equal(blocked.decision, 'block');
        assert.match(blocked.message, /resolve inside the repository/);

        const inactive = workerEditPathDecisionForTest({
          sessionID: 'ses_plan',
          files: ['/tmp/outside.ts'],
          relativePaths: [],
          run: inactiveRun,
        });
        assert.equal(inactive.decision, 'allow');

        const resolved = workerEditPathDecisionForTest({
          sessionID: 'ses_worker',
          files: ['/repo/frontend/test-1.test.ts'],
          relativePaths: ['frontend/test-1.test.ts'],
          run: () => { throw new Error('worker-state should not be called for resolved paths'); },
        });
        assert.equal(resolved.decision, 'allow');
        """
    )


def test_worker_bash_gate_blocks_mutating_commands_for_active_workers() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { workerBashGateDecisionForTest } = OpenMatesHooks.test;
        const activeRun = () => ({ status: 0, stdout: '{"active_worker": true}', stderr: '' });
        const blocked = workerBashGateDecisionForTest({
          sessionID: 'ses_worker',
          command: `python3 -c "from pathlib import Path; Path('frontend/x.ts').write_text('x')"`,
          run: activeRun,
        });
        assert.equal(blocked.decision, 'block');

        const inactive = workerBashGateDecisionForTest({
          sessionID: 'ses_worker',
          command: 'python3 scripts/custom_tool.py --fix',
          run: () => ({ status: 0, stdout: '{"active_worker": false}', stderr: '' }),
        });
        assert.equal(inactive.decision, 'allow');

        const sessionStart = workerBashGateDecisionForTest({
          sessionID: 'ses_worker',
          command: 'python3 scripts/sessions.py start --mode testing --task "Debug group" --opencode-session "${OPENCODE_SESSION_ID}"',
          run: activeRun,
        });
        assert.equal(sessionStart.decision, 'allow');
        const mismatchedSessionStart = workerBashGateDecisionForTest({
          sessionID: 'ses_worker',
          command: 'python3 scripts/sessions.py start --mode testing --task "Debug group" --opencode-session ses_other',
          run: activeRun,
        });
        assert.equal(mismatchedSessionStart.decision, 'block');

        const campaignIntent = workerBashGateDecisionForTest({
          sessionID: 'ses_worker',
          command: 'python3 scripts/tests.py campaign intent --group g --lease l --worker w --base-commit abc --hypothesis h --write-file frontend/x.ts',
          run: activeRun,
        });
        assert.equal(campaignIntent.decision, 'allow');
        const generatedIntent = workerBashGateDecisionForTest({
          sessionID: 'ses_worker',
          command: 'python3 scripts/tests.py campaign intent --group group-1 --lease lease-1 --worker worker-one --base-commit current-commit --hypothesis "..." --write-file frontend/test-1.test.ts',
          run: activeRun,
        });
        assert.equal(generatedIntent.decision, 'allow');

        for (const command of [
          'OPENCODE_SESSION_ID=ses_other python3 scripts/tests.py campaign intent --group g --lease l --worker w --base-commit abc --hypothesis h --write-file frontend/x.ts',
          'env -u OPENCODE_SESSION_ID python3 scripts/tests.py campaign boundary --group g --lease l --worker w --file frontend/x.ts --reason h',
          'env -i python3 scripts/tests.py campaign intent --group g --lease l --worker w --base-commit abc --hypothesis h --write-file frontend/x.ts',
          'env OPENCODE_SESSION_ID=ses_other python3 scripts/tests.py campaign finish-worker --group g --lease l --worker w --base-commit abc --changed-file frontend/x.ts --summary h',
          'command env OPENCODE_SESSION_ID=ses_other python3 scripts/tests.py campaign intent --group g --lease l --worker w --base-commit abc --hypothesis h --write-file frontend/x.ts',
          'builtin env OPENCODE_SESSION_ID=ses_other python3 scripts/tests.py campaign finish-worker --group g --lease l --worker w --base-commit abc --changed-file frontend/x.ts --summary h',
        ]) {
          assert.equal(
            workerBashGateDecisionForTest({ sessionID: 'ses_worker', command, run: activeRun }).decision,
            'block',
            command,
          );
        }
        const inactiveRun = () => ({ status: 0, stdout: '{"active_worker": false}', stderr: '' });
        for (const command of [
          'OPENCODE_SESSION_ID=ses_other python3 scripts/tests.py campaign intent --group g --lease l --worker w --base-commit abc --hypothesis h --write-file frontend/x.ts',
          'OPENCODE_SESSION_ID=coordinator python3 -u ./scripts/tests.py campaign approve-intent --group g --lease l --session coordinator --current-commit abc',
          `OPENCODE_SESSION_ID=coordinator python3 ${process.cwd()}/scripts/tests.py campaign approve-boundary --group g --lease l --session coordinator`,
          'export OPENCODE_SESSION_ID=coordinator; python3 scripts/tests.py campaign approve-intent --group g --lease l --session coordinator --current-commit abc',
          'OPENCODE_SESSION_ID=coordinator && python3 scripts/tests.py campaign approve-boundary --group g --lease l --session coordinator',
          'bash -c "OPENCODE_SESSION_ID=coordinator python3 scripts/tests.py campaign approve-intent --group g --lease l --session coordinator --current-commit abc"',
          'sh -c "export OPENCODE_SESSION_ID=coordinator; python3 scripts/tests.py campaign approve-boundary --group g --lease l --session coordinator"',
          `python3 -c "import os, subprocess; os.environ['OPENCODE_SESSION_ID']='coordinator'; subprocess.run(['python3','scripts/tests.py','campaign','approve-intent','--group','g','--lease','l','--session','coordinator'])"`,
          'env "$(printf %s OPENCODE_SESSION_ID=coordinator)" python3 scripts/tests.py campaign approve-intent --group g --lease l --session coordinator --current-commit abc',
          `python3 -c "import os, subprocess; os.environ['OPENCODE' + '_SESSION_ID']='coordinator'; subprocess.run(['python3','scripts/tests.py','campaign','approve-boundary','--group','g','--lease','l','--session','coordinator'])"`,
          `python3 -c "import os, runpy, sys; os.environ['OPEN' + 'CODE_SESSION_ID']='coordinator'; sys.argv=['scripts/' + 'tests.py','campaign','approve-intent','--group','g','--lease','l','--session','coordinator']; runpy.run_path('scripts/' + 'tests.py', run_name='__main__')"`,
          `node -p "process.env['OPEN' + 'CODE_SESSION_ID']='coordinator'; require('child_process').spawnSync('python3',['scripts/' + 'tests.py','campaign','approve-intent','--group','g','--lease','l','--session','coordinator'])"`,
          'command env OPENCODE_SESSION_ID=ses_other python3 scripts/tests.py campaign boundary --group g --lease l --worker w --requested-file frontend/x.ts --reason h',
          'builtin env OPENCODE_SESSION_ID=ses_other python3 scripts/tests.py campaign finish-worker --group g --lease l --worker w --base-commit abc --changed-file frontend/x.ts --summary h',
          'timeout 10 env OPENCODE_SESSION_ID=coordinator python3 scripts/tests.py campaign approve-intent --group g --lease l --session coordinator --current-commit abc',
        ]) {
          assert.equal(
            workerBashGateDecisionForTest({ sessionID: 'ses_attacker', command, run: inactiveRun }).decision,
            'block',
            command,
          );
        }
        """
    )


def test_merged_managed_worktree_routes_when_path_exists() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { routingDecisionForTest } = OpenMatesHooks.test;
        const worktreePath = '/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-test';
        const result = routingDecisionForTest({
          session: { worktree: { status: 'merged', path: worktreePath, merged_commit: 'b2b533062cc16' } },
          pathExists: (path) => path === worktreePath || path === `${worktreePath}/.git`,
        });

        assert.equal(result.decision, 'worktree_routed');
        assert.equal(result.worktreePath, worktreePath);
        """
    )


def test_opencode_discord_notifier_contract_is_registered() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { completedAssistantMessageID, isTodoWriteTool, notifierEventArgsForTest, presenceIsLive } = OpenMatesHooks.test;
        for (const tool of ['todowrite', 'todo_write', 'todo.write', 'TodoWrite']) assert.equal(isTodoWriteTool(tool), true, tool);
        assert.equal(isTodoWriteTool('task'), false);
        assert.equal(presenceIsLive({ execution: 'busy', turn: 'none' }), true);
        assert.equal(presenceIsLive({ execution: 'idle', turn: 'streaming' }), true);
        assert.equal(presenceIsLive({ execution: 'idle', turn: 'completed' }), false);

        assert.equal(
          completedAssistantMessageID({
            type: 'message.completed',
            properties: { info: { id: 'msg_123', role: 'assistant', time: { completed: 1 } } },
          }),
          'msg_123',
        );
        const args = notifierEventArgsForTest({ eventType: 'response-completed', sessionID: 'ses_1', messageID: 'msg_123' });
        assert.deepEqual(args.slice(-6), ['--event', 'response-completed', '--session-id', 'ses_1', '--message-id', 'msg_123']);
        """
    )


def test_openmatescloud_repo_root_routes_tools_to_sibling_checkout() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { routingDecisionForTest, routeLocalToolArgsForTest } = OpenMatesHooks.test;
        const route = routingDecisionForTest({
          session: {
            repo_id: 'openmatescloud',
            repo_name: 'OpenMatesCloud',
            repo_root: '/tmp/OpenMatesCloud',
            repo_branch: 'main',
          },
        });

        assert.equal(route.decision, 'worktree_routed');
        assert.equal(route.worktreePath, '/tmp/OpenMatesCloud');
        assert.equal(
          routeLocalToolArgsForTest('bash', { command: 'git status --short --branch' }, route.worktreePath).workdir,
          '/tmp/OpenMatesCloud',
        );
        assert.equal(
          routeLocalToolArgsForTest('bash', { command: 'python3 scripts/sessions.py deploy --session abcd --title "x"' }, route.worktreePath).workdir,
          '/home/superdev/projects/.openmates-runtime/opencode-server',
        );
        """
    )


def test_reviewer_loop_guard_requires_an_intervening_source_revision() -> None:
    run_hook_assertion(
        """
        import { strict as assert } from 'node:assert';
        import { OpenMatesHooks } from './.opencode/plugins/openmates-hooks.js';

        const { reviewerSpawnDecisionForTest } = OpenMatesHooks.test;
        assert.equal(
          reviewerSpawnDecisionForTest({ agent: 'code-reviewer', generation: 4 }).decision,
          'allow',
        );
        const duplicate = reviewerSpawnDecisionForTest({
          agent: 'code-reviewer',
          generation: 4,
          lastReviewedGeneration: 4,
        });
        assert.equal(duplicate.decision, 'block');
        assert.match(duplicate.message, /already has a completed code-reviewer pass/);
        assert.equal(
          reviewerSpawnDecisionForTest({
            agent: 'code-reviewer',
            generation: 5,
            lastReviewedGeneration: 4,
          }).decision,
          'allow',
        );
        assert.equal(
          reviewerSpawnDecisionForTest({ agent: 'explore', generation: 4, lastReviewedGeneration: 4 }).decision,
          'allow',
        );
        """
    )
