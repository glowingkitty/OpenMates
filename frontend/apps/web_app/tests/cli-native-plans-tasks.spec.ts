/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: the `plans tasks` subtree (Plan-scoped Task commands).
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 * The Plan and Project are npm-created fixtures shared by both CLIs; each CLI creates and
 * deletes its own throwaway Tasks (slugs are unique per account) inside that Plan.
 *
 * Not covered: `plans tasks ask` needs AI inference, unavailable in CI.
 */
export {};
import type { TestInfo } from '@playwright/test';

const { randomUUID } = require('node:crypto');
const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { bothIds, pickId } = require('./helpers/cli-native-fixtures');
const { createFixtures, logAbort } = require('./helpers/cli-native-plans-fixtures');

const { email, password, otpKey } = getTestAccount();
const UNKNOWN = '00000000-0000-4000-8000-000000000000';
const TASK_KEYS = ['task_id', 'taskId', 'id'];
const HISTORY_IDS = ['change_set_id', 'entry_id', 'restored_from_entry_id', 'version_before', 'encrypted_before_ref', 'rollback_entry_commands', 'undo_all_command', 'undo_entry_commands'];
const VOLATILE = ['short_id', 'shortId', 'slug', 'position', 'sort_key', 'order_key'];

test.describe('CLI native differential: plans tasks', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('plans tasks commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'plans-tasks', { paceMs: 4_000 });
		const fx = await createFixtures(diff, 'tasks');
		const cleanup: Array<() => Promise<unknown>> = [];
		try {
			const plan = await fx.plan('Differential tasks plan');
			const createArgs = (slug: string, title: string, rest: string[]) => ['plans', 'tasks', 'create', plan, '--title', title, '--slug', slug, ...rest];
			const created = await diff.check('plans tasks create', createArgs('differential-ptask-npm', 'Differential plan task', ['--assign', 'user', '--priority', 'high']), {
				nativeArgs: createArgs('differential-ptask-native', 'Differential plan task', ['--assign', 'user', '--priority', 'high']),
				ignoreKeys: VOLATILE,
				catalog: ['plans tasks create']
			});
			const task = bothIds(created, TASK_KEYS);
			const second = bothIds(await diff.check('plans tasks create (dependency target)', createArgs('differential-ptask-dep-npm', 'Differential plan dependency', ['--assign', 'user']), { nativeArgs: createArgs('differential-ptask-dep-native', 'Differential plan dependency', ['--assign', 'user']), ignoreKeys: VOLATILE, catalog: ['plans tasks create'] }), TASK_KEYS);
			for (const id of [task.npm, second.npm]) if (id) cleanup.push(() => diff.npm(['tasks', 'delete', id, '--confirm', '--json']));
			for (const id of [task.native, second.native]) if (id) cleanup.push(() => diff.native(['tasks', 'delete', id, '--confirm', '--json']));
			const projectNpm = pickId(await diff.npm(['projects', 'create', 'Differential plan tasks project', '--slug', 'differential-ptasks-project-npm', '--write-policy', 'always_ask', '--personal', '--json']), ['project_id', 'id']);
			const projectNative = pickId(await diff.native(['projects', 'create', 'Differential plan tasks project', '--slug', 'differential-ptasks-project-native', '--write-policy', 'always_ask', '--personal', '--json']), ['project_id', 'id']);
			if (projectNpm) cleanup.push(() => diff.npm(['projects', 'delete', projectNpm, '--confirm', projectNpm, '--json']));
			if (projectNative) cleanup.push(() => diff.native(['projects', 'delete', projectNative, '--confirm', projectNative, '--json']));
			const t = task.npm || UNKNOWN;

			await diff.check('plans tasks group help', ['plans', 'tasks'], { mode: 'exit', expectedGap: 'exit: npm=1 native=0' });
			await diff.check('plans tasks list', ['plans', 'tasks', 'list', plan], { structureOnly: true, catalog: ['plans tasks list'] });
			await diff.check('plans tasks board', ['plans', 'tasks', 'board', plan], { structureOnly: true, catalog: ['plans tasks board'] });
			await diff.check('plans tasks status', ['plans', 'tasks', 'status', plan], { structureOnly: true, catalog: ['plans tasks status'] });
			await diff.check('plans tasks status <task>', ['plans', 'tasks', 'status', plan, t], { ignoreKeys: VOLATILE, catalog: ['plans tasks status'] });
			await diff.check('plans tasks show', ['plans', 'tasks', 'show', plan, t], { ignoreKeys: VOLATILE, catalog: ['plans tasks show'] });
			await diff.check('plans tasks connection', ['plans', 'tasks', 'connection', plan, t], { catalog: ['plans tasks connection'] });
			await diff.check('plans tasks dependencies list', ['plans', 'tasks', 'dependencies', plan, 'list', t], { catalog: ['plans tasks dependencies list'] });
			await diff.check('plans tasks activity list', ['plans', 'tasks', 'activity', plan, 'list', t, '--max-entries', '20'], { catalog: ['plans tasks activity list'] });

			const mutate = (label: string, build: (id: string, other: string, project: string) => string[], catalog: string[], extra: Record<string, unknown> = {}) =>
				diff.check(label, build(t, second.npm || UNKNOWN, projectNpm || UNKNOWN), {
					nativeArgs: build(task.native || UNKNOWN, second.native || UNKNOWN, projectNative || UNKNOWN),
					ignoreKeys: VOLATILE,
					catalog,
					...extra
				});
			await mutate('plans tasks edit', (id) => ['plans', 'tasks', 'edit', plan, id, '--description', 'edited by differential', '--add-label', 'edited'], ['plans tasks edit']);
			const added = await mutate('plans tasks activity add', (id) => ['plans', 'tasks', 'activity', plan, 'add', id, '--message', 'Differential activity note'], ['plans tasks activity add'], { ignoreKeys: [...VOLATILE, ...HISTORY_IDS] });
			const entry = bothIds(added, ['entry_id', 'entryId', 'id']);
			await mutate('plans tasks activity search', (id) => ['plans', 'tasks', 'activity', plan, 'search', id, '--query', 'Differential'], ['plans tasks activity search']);
			await diff.check('plans tasks activity delete', ['plans', 'tasks', 'activity', plan, 'delete', t, entry.npm || UNKNOWN], {
				nativeArgs: ['plans', 'tasks', 'activity', plan, 'delete', task.native || UNKNOWN, entry.native || UNKNOWN],
				catalog: ['plans tasks activity delete']
			});
			await mutate('plans tasks activity flush', (id) => ['plans', 'tasks', 'activity', plan, 'flush', id], ['plans tasks activity flush']);
			// Backend dependencies must share a Project, so both Tasks join it (the second as unchecked setup).
			await mutate('plans tasks add-to-project', (id, _other, project) => ['plans', 'tasks', id, plan, 'add-to-project', project], ['plans tasks add-to-project'], { expectedGap: 'stderr class: npm=other native=http-auth' });
			await diff.npm(['tasks', second.npm || UNKNOWN, 'add-to-project', projectNpm || UNKNOWN, '--json']);
			await diff.native(['tasks', second.native || UNKNOWN, 'add-to-project', projectNative || UNKNOWN, '--json']);
			await mutate('plans tasks dependencies add', (id, other) => ['plans', 'tasks', 'dependencies', plan, 'add', id, '--target', `task:${other}`], ['plans tasks dependencies add'], { ignoreKeys: [...VOLATILE, 'dependency_project_hash'], expectedGap: 'stderr class: npm=http-client-error native=validation' });
			await mutate('plans tasks dependencies list (after add)', (id) => ['plans', 'tasks', 'dependencies', plan, 'list', id], ['plans tasks dependencies list']);
			await mutate('plans tasks dependencies remove', (id, other) => ['plans', 'tasks', 'dependencies', plan, 'remove', id, '--target', `task:${other}`], ['plans tasks dependencies remove'], { expectedGap: 'stderr class: npm=http-client-error native=validation' });
			await mutate('plans tasks remove-from-project', (id, _other, project) => ['plans', 'tasks', id, plan, 'remove-from-project', project], ['plans tasks remove-from-project'], { expectedGap: 'stderr class: npm=other native=http-auth' });
			await mutate('plans tasks reorder', (id, other) => ['plans', 'tasks', 'reorder', plan, id, '--before', other], ['plans tasks reorder']);
			await mutate('plans tasks connect', (id) => ['plans', 'tasks', 'connect', plan, id, '--thread', randomUUID()], ['plans tasks connect'], { ignoreKeys: [...VOLATILE, 'thread_id', 'threadId', 'external_chat', 'externalChat'] });
			await mutate('plans tasks start', (id) => ['plans', 'tasks', 'start', plan, id], ['plans tasks start'], { expectedGap: 'stderr class: npm=http-client-error native=validation' });
			await mutate('plans tasks block', (id) => ['plans', 'tasks', 'block', plan, id, '--reason-code', 'needs_user_input', '--reason-text', 'differential'], ['plans tasks block']);
			await mutate('plans tasks unblock', (id) => ['plans', 'tasks', 'unblock', plan, id], ['plans tasks unblock']);
			await mutate('plans tasks release', (id) => ['plans', 'tasks', 'release', plan, id], ['plans tasks release']);
			await mutate('plans tasks resume', (id) => ['plans', 'tasks', 'resume', plan, id], ['plans tasks resume']);
			await mutate('plans tasks skip', (id) => ['plans', 'tasks', 'skip', plan, id], ['plans tasks skip']);
			await mutate('plans tasks done', (id) => ['plans', 'tasks', 'done', plan, id], ['plans tasks done'], { expectedGap: 'stderr class: npm=http-client-error native=validation' });
			const history = await mutate('plans tasks history', (id) => ['plans', 'tasks', 'history', plan, id, '--limit', '10'], ['plans tasks history'], { structureOnly: true });
			const historyEntry = bothIds(history, ['entry_id', 'history_entry_id', 'id']);
			await diff.check('plans tasks restore', ['plans', 'tasks', 'restore', plan, t, '--entry', historyEntry.npm || UNKNOWN, '--state', 'before'], {
				nativeArgs: ['plans', 'tasks', 'restore', plan, task.native || UNKNOWN, '--entry', historyEntry.native || UNKNOWN, '--state', 'before'],
				ignoreKeys: [...VOLATILE, ...HISTORY_IDS],
				catalog: ['plans tasks restore']
			});

			// add/edit/remove are the legacy list|add|edit|remove layout: a second pair of throwaway Tasks.
			const legacy = bothIds(await diff.check('plans tasks add', ['plans', 'tasks', 'add', plan, '--title', 'Differential legacy task', '--slug', 'differential-ptask-legacy-npm', '--assign', 'user'], {
				nativeArgs: ['plans', 'tasks', 'add', plan, '--title', 'Differential legacy task', '--slug', 'differential-ptask-legacy-native', '--assign', 'user'],
				ignoreKeys: VOLATILE,
				catalog: ['plans tasks add']
			}), TASK_KEYS);
			await diff.check('plans tasks remove', ['plans', 'tasks', 'remove', plan, legacy.npm || UNKNOWN, '--confirm'], {
				nativeArgs: ['plans', 'tasks', 'remove', plan, legacy.native || UNKNOWN, '--confirm'],
				ignoreKeys: [...VOLATILE, ...HISTORY_IDS],
				catalog: ['plans tasks remove']
			});

			await mutate('plans tasks delete', (id) => ['plans', 'tasks', 'delete', plan, id, '--confirm'], ['plans tasks delete']);
			await mutate('plans tasks delete (dependency target)', (_id, other) => ['plans', 'tasks', 'delete', plan, other, '--confirm'], ['plans tasks delete'], { ignoreKeys: [...VOLATILE, ...HISTORY_IDS] });
			await mutate('plans tasks show (deleted)', (id) => ['plans', 'tasks', 'show', plan, id], ['plans tasks show']);
		} catch (error) {
			logAbort(error);
		} finally {
			for (const undo of cleanup) await undo();
			await fx.cleanup();
			await finishDifferential(diff);
		}
	});
});
