/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: tasks commands.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 * Each CLI creates its own throwaway Tasks and Project (create -> read -> update -> delete);
 * plain reads run against the npm-created Task on both CLIs.
 *
 * Open native gaps (asserted as expectedGap, therefore NOT counted as verified):
 * `tasks activity add|search|delete` (native entry_id is a 64-hex value, npm a UUID),
 * `tasks activity flush` (native adds `delivered`), `tasks reorder` (queue_state/blocked_reason
 * representation), `tasks start` (stderr class), `tasks release` (task.version offset),
 * `tasks history` (entry count), and the not-found stderr class of `tasks delete` / `tasks show`
 * (native reports invalid_argument where npm reports http-not-found).
 * `tasks list --label` is not exercised: the backend label filter needs a separate fix.
 */
export {};
import type { TestInfo } from '@playwright/test';

const { randomUUID } = require('node:crypto');
const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { bothIds, pickId } = require('./helpers/cli-native-fixtures');

const { email, password, otpKey } = getTestAccount();
const UNKNOWN = '00000000-0000-4000-8000-000000000000';
const TASK_KEYS = ['task_id', 'taskId', 'id'];
const HISTORY_IDS = ['change_set_id', 'entry_id', 'restored_from_entry_id', 'version_before', 'encrypted_before_ref', 'rollback_entry_commands', 'undo_all_command', 'undo_entry_commands'];
const VOLATILE = ['short_id', 'shortId', 'slug', 'position', 'sort_key', 'order_key'];

test.describe('CLI native differential: tasks', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('task commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'tasks');
		const cleanup: Array<() => Promise<unknown>> = [];
		try {
			await diff.check('tasks help', ['tasks'], { mode: 'exit', catalog: ['tasks'] });
			await diff.check('tasks ask (no instruction)', ['tasks', 'ask'], { mode: 'exit', catalog: ['tasks ask'] });

			// Create: two Tasks per CLI (the second is a dependency target) and one Project.
			// Task slugs are unique per account (backend 409 TASK_SLUG_CONFLICT), so each CLI gets its own explicit slug.
			const createArgs = (slug: string, title: string, rest: string[]) => ['tasks', 'create', '--title', title, '--slug', slug, ...rest];
			const created = await diff.check('tasks create', createArgs('differential-task-npm', 'Differential task', ['--description', 'npm vs native', '--assign', 'user', '--priority', 'high', '--label', 'differential']), {
				nativeArgs: createArgs('differential-task-native', 'Differential task', ['--description', 'npm vs native', '--assign', 'user', '--priority', 'high', '--label', 'differential']),
				ignoreKeys: VOLATILE,
				catalog: ['tasks create']
			});
			const task = bothIds(created, TASK_KEYS);
			const second = bothIds(await diff.check('tasks create (dependency target)', createArgs('differential-dependency-npm', 'Differential dependency', ['--assign', 'user']), { nativeArgs: createArgs('differential-dependency-native', 'Differential dependency', ['--assign', 'user']), ignoreKeys: VOLATILE, catalog: ['tasks create'] }), TASK_KEYS);
			for (const id of [task.npm, second.npm]) if (id) cleanup.push(() => diff.npm(['tasks', 'delete', id, '--confirm', '--json']));
			for (const id of [task.native, second.native]) if (id) cleanup.push(() => diff.native(['tasks', 'delete', id, '--confirm', '--json']));
			const projectNpm = pickId(await diff.npm(['projects', 'create', 'Differential tasks project', '--slug', 'differential-tasks-project-npm', '--write-policy', 'always_ask', '--personal', '--json']), ['project_id', 'id']);
			const projectNative = pickId(await diff.native(['projects', 'create', 'Differential tasks project', '--slug', 'differential-tasks-project-native', '--write-policy', 'always_ask', '--personal', '--json']), ['project_id', 'id']);
			if (projectNpm) cleanup.push(() => diff.npm(['projects', 'delete', projectNpm, '--confirm', projectNpm, '--json']));
			if (projectNative) cleanup.push(() => diff.native(['projects', 'delete', projectNative, '--confirm', projectNative, '--json']));
			const t = task.npm || UNKNOWN;

			// Read.
			await diff.check('tasks list (unfiltered)', ['tasks', 'list'], { structureOnly: true, catalog: ['tasks list'] });
			await diff.check('tasks board', ['tasks', 'board'], { structureOnly: true, catalog: ['tasks board'] });
			await diff.check('tasks status', ['tasks', 'status'], { structureOnly: true, catalog: ['tasks status'] });
			await diff.check('tasks status <task>', ['tasks', 'status', t], { ignoreKeys: VOLATILE, catalog: ['tasks status'] });
			await diff.check('tasks show', ['tasks', 'show', t], { ignoreKeys: VOLATILE, catalog: ['tasks show'] });
			await diff.check('tasks connection', ['tasks', 'connection', t], { catalog: ['tasks connection'] });
			await diff.check('tasks dependencies list', ['tasks', 'dependencies', 'list', t], { catalog: ['tasks dependencies list'] });
			await diff.check('tasks activity list', ['tasks', 'activity', 'list', t, '--max-entries', '20'], { catalog: ['tasks activity list'] });

			// Update (each CLI on its own Tasks).
			const mutate = (label: string, build: (id: string, other: string, project: string) => string[], catalog: string[], extra: Record<string, unknown> = {}) =>
				diff.check(label, build(t, second.npm || UNKNOWN, projectNpm || UNKNOWN), {
					nativeArgs: build(task.native || UNKNOWN, second.native || UNKNOWN, projectNative || UNKNOWN),
					ignoreKeys: VOLATILE,
					catalog,
					...extra
				});
			await mutate('tasks edit', (id) => ['tasks', 'edit', id, '--description', 'edited by differential', '--add-label', 'edited'], ['tasks edit']);
			const added = await mutate('tasks activity add', (id) => ['tasks', 'activity', 'add', id, '--message', 'Differential activity note'], ['tasks activity add'], { expectedGap: '$.entry.entry_id: npm=' });
			const entry = bothIds(added, ['entry_id', 'entryId', 'id']);
			await mutate('tasks activity search', (id) => ['tasks', 'activity', 'search', id, '--query', 'Differential'], ['tasks activity search'], { expectedGap: '$.entries[0].entry_id: npm=' });
			await diff.check('tasks activity delete', ['tasks', 'activity', 'delete', t, entry.npm || UNKNOWN], {
				nativeArgs: ['tasks', 'activity', 'delete', task.native || UNKNOWN, entry.native || UNKNOWN],
				expectedGap: '$.entry.entry_id: npm=',
				catalog: ['tasks activity delete']
			});
			await mutate('tasks activity flush', (id) => ['tasks', 'activity', 'flush', id], ['tasks activity flush'], { expectedGap: '$.delivered: only in native' });
			await mutate('tasks add-to-project', (id, _other, project) => ['tasks', id, 'add-to-project', project], ['tasks add-to-project']);
			// Backend dependencies must share a Project, so the dependency target joins it too (unchecked setup).
			await diff.npm(['tasks', second.npm || UNKNOWN, 'add-to-project', projectNpm || UNKNOWN, '--json']);
			await diff.native(['tasks', second.native || UNKNOWN, 'add-to-project', projectNative || UNKNOWN, '--json']);
			await mutate('tasks dependencies add', (id, other) => ['tasks', 'dependencies', 'add', id, '--target', `task:${other}`], ['tasks dependencies add'], { ignoreKeys: [...VOLATILE, 'dependency_project_hash'] }); // hash of each CLI's own Project id
			await mutate('tasks dependencies list (after add)', (id) => ['tasks', 'dependencies', 'list', id], ['tasks dependencies list']);
			await mutate('tasks dependencies remove', (id, other) => ['tasks', 'dependencies', 'remove', id, '--target', `task:${other}`], ['tasks dependencies remove']);
			await mutate('tasks remove-from-project', (id, _other, project) => ['tasks', id, 'remove-from-project', project], ['tasks remove-from-project']);
			await mutate('tasks reorder', (id, other) => ['tasks', 'reorder', id, '--before', other], ['tasks reorder'], { expectedGap: '$.tasks[0].queue_state: npm=' });
			await mutate('tasks connect', (id) => ['tasks', 'connect', id, '--thread', randomUUID()], ['tasks connect'], { ignoreKeys: [...VOLATILE, 'thread_id', 'threadId', 'external_chat', 'externalChat'] });
			await mutate('tasks start', (id) => ['tasks', 'start', id], ['tasks start'], { expectedGap: 'stderr class: npm=http-client-error native=validation' });
			await mutate('tasks block', (id) => ['tasks', 'block', id, '--reason-code', 'needs_user_input', '--reason-text', 'differential'], ['tasks block']);
			await mutate('tasks unblock', (id) => ['tasks', 'unblock', id], ['tasks unblock']);
			await mutate('tasks release', (id) => ['tasks', 'release', id], ['tasks release'], { expectedGap: '$.task.version: npm=7 native=8' });
			await mutate('tasks resume', (id) => ['tasks', 'resume', id], ['tasks resume']);
			await mutate('tasks skip', (id) => ['tasks', 'skip', id], ['tasks skip'], { ignoreKeys: [...VOLATILE, 'version'] }); // version offset inherited from the release gap above
			await mutate('tasks done', (id) => ['tasks', 'done', id], ['tasks done'], { ignoreKeys: [...VOLATILE, 'version'] });
			const history = await mutate('tasks history', (id) => ['tasks', 'history', id, '--limit', '10'], ['tasks history'], { structureOnly: true, expectedGap: '$.entries: array length' });
			const historyEntry = bothIds(history, ['entry_id', 'history_entry_id', 'id']);
			await diff.check('tasks restore', ['tasks', 'restore', t, '--entry', historyEntry.npm || UNKNOWN, '--state', 'before'], {
				nativeArgs: ['tasks', 'restore', task.native || UNKNOWN, '--entry', historyEntry.native || UNKNOWN, '--state', 'before'],
				ignoreKeys: [...VOLATILE, ...HISTORY_IDS],
				catalog: ['tasks restore']
			});

			// Delete (each CLI its own Tasks).
			await mutate('tasks delete', (id) => ['tasks', 'delete', id, '--confirm'], ['tasks delete'], { expectedGap: 'stderr class: npm=http-not-found native=validation' });
			await mutate('tasks delete (dependency target)', (_id, other) => ['tasks', 'delete', other, '--confirm'], ['tasks delete'], { ignoreKeys: [...VOLATILE, ...HISTORY_IDS] });
			await mutate('tasks show (deleted)', (id) => ['tasks', 'show', id], ['tasks show'], { expectedGap: 'stderr class: npm=http-not-found native=validation' });
		} finally {
			for (const undo of cleanup) await undo();
			await finishDifferential(diff);
		}
	});
});
