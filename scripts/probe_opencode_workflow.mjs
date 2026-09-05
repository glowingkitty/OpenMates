#!/usr/bin/env node
// Probe the effective packaged hook and schema in an isolated state directory.
// This creates no OpenCode chats and calls no product API or mutating helper.
// The package's installed plugin dependency must load successfully.
// Guard probes include both a rejected root write and an unaffected routed read.
// See docs/architecture/agent-workflow-decisions.md for release activation.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
const packageRoot = resolve(process.argv[2]);
const { OpenMatesHooks } = await import(pathToFileURL(resolve(packageRoot, 'plugins/openmates-hooks.js')));
const hooks = await OpenMatesHooks({ client: {}, directory: process.env.OPENMATES_PROJECT_ROOT, routingData: { sessions: {} } });
assert(hooks.tool?.openmates_task, 'Effective Task tool is missing');
const actions = hooks.tool.openmates_task.args.action.options;
assert(Array.isArray(actions), 'Effective Task action schema is unavailable');
const root = process.env.OPENMATES_PROJECT_ROOT;
assert.equal(OpenMatesHooks.test.rootGuardDecisionForTest({ mode: 'strict', cwd: root, target: `${root}/scripts/sessions.py`, sessionID: 'probe' }).decision, 'block');
const worktree = `${root}/.openmates-agent-worktrees/agent-probe`;
const routed = OpenMatesHooks.test.routeLocalToolArgsForTest('read', { filePath: 'safe.txt' }, worktree);
assert.equal(routed.filePath, `${worktree}/safe.txt`);
assert.equal(typeof hooks['tool.execute.before'], 'function');
assert.equal(typeof hooks['tool.execute.after'], 'function');
console.log(JSON.stringify({ actions, guards: 'passed', normal_read: 'passed', hook_exports: 1 }));
