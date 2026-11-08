/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: projects, recovery and workspace history commands.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 * Each CLI creates its own throwaway Project (create -> read -> update -> delete);
 * reads run against the npm-created Project on both CLIs.
 */
export {};
import type { TestInfo } from '@playwright/test';

const path = require('node:path');
const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { bothIds, parseJson, pickString } = require('./helpers/cli-native-fixtures');

const { email, password, otpKey } = getTestAccount();
const UNKNOWN = '00000000-0000-4000-8000-000000000000';
const PROJECT_KEYS = ['project_id', 'projectId', 'id'];

test.describe('CLI native differential: projects', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('project, recovery and history commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'projects');
		const cleanup: Array<() => Promise<unknown>> = [];
		try {
			await diff.check('projects help', ['projects'], { mode: 'exit', catalog: ['projects'] });
			await diff.check('recovery help', ['recovery'], { mode: 'text', catalog: ['recovery'] });
			await diff.check('history help-less list', ['history', '--limit', '5'], { structureOnly: true, catalog: ['history'] });

			// Create: one Project per CLI with the same name.
			// Slugs are unique per account, so each CLI gets its own slug (ignored in the comparison).
			const createArgs = (slug: string) => ['projects', 'create', 'Differential project', '--slug', slug, '--write-policy', 'always_ask', '--description', 'npm vs native', '--personal'];
			const created = await diff.check('projects create', createArgs('differential-npm'), {
				nativeArgs: createArgs('differential-native'),
				ignoreKeys: ['slug', 'short_id'],
				catalog: ['projects create']
			});
			const project = bothIds(created, PROJECT_KEYS);
			const p = project.npm || UNKNOWN;
			const n = project.native || UNKNOWN;
			if (project.npm) cleanup.push(() => diff.npm(['projects', 'delete', project.npm, '--confirm', project.npm, '--json']));
			if (project.native) cleanup.push(() => diff.native(['projects', 'delete', project.native, '--confirm', project.native, '--json']));

			// Read.
			await diff.check('projects list', ['projects', 'list'], { structureOnly: true, catalog: ['projects list'] });
			await diff.check('projects list --include-archived', ['projects', 'list', '--include-archived'], { structureOnly: true, catalog: ['projects list'] });
			await diff.check('projects show', ['projects', 'show', p], { catalog: ['projects show'] });
			// `open` bumps the version after printing, so the second CLI sees the next version.
			await diff.check('projects open', ['projects', 'open', p], { ignoreKeys: ['version'], catalog: ['projects open'] });
			await diff.check('projects items list', ['projects', 'items', 'list', p], { catalog: ['projects items list'] });
			await diff.check('projects sources list', ['projects', 'sources', 'list', p], { catalog: ['projects sources list'] });
			await diff.check('projects plans', ['projects', 'plans', p], { catalog: ['projects plans'] });
			await diff.check('projects tasks', ['projects', 'tasks', p], { catalog: ['projects tasks'] });
			// Documented gap: npm prints the raw encrypted_settings ciphertext; native prints the decrypted default focus.
			await diff.check('projects settings (show)', ['projects', 'settings', p], { expectedGap: '$.settings.encrypted_settings: only in npm', catalog: ['projects settings'] });
			await diff.check('projects settings command-presets list', ['projects', 'settings', p, 'command-presets', 'list'], { catalog: ['projects settings command-presets list'] });
			await diff.check('projects settings command-resources list', ['projects', 'settings', p, 'command-resources', 'list'], { catalog: ['projects settings command-resources list'] });
			await diff.check('projects files list (no source)', ['projects', 'files', 'list', p], { catalog: ['projects files list'] });
			await diff.check('projects files read (no source)', ['projects', 'files', 'read', p, 'README.md'], { catalog: ['projects files read'] });
			await diff.check('projects files search (no source)', ['projects', 'files', 'search', p, 'differential'], { catalog: ['projects files search'] });

			// Update (each CLI on its own Project).
			const per = (args: (id: string) => string[]) => ({ npm: args(p), native: args(n) });
			const mutate = async (label: string, build: (id: string) => string[], catalog: string[], extra: Record<string, unknown> = {}) => {
				const argv = per(build);
				return diff.check(label, argv.npm, { nativeArgs: argv.native, catalog, ...extra });
			};
			await mutate('projects update', (id) => ['projects', 'update', id, '--description', 'updated by differential', '--pin'], ['projects update'], { ignoreKeys: ['slug', 'short_id', 'version'] });
			// Documented gap: native prints the decrypted settings instead of npm's raw ciphertext (see show above).
			await mutate('projects settings write-policy', (id) => ['projects', 'settings', id, '--write-policy', 'apply_and_show', '--auto-selection', 'off'], ['projects settings'], { ignoreKeys: ['default_focus_id_hash'], expectedGap: '$.settings.encrypted_settings: only in npm' });
			await mutate('projects settings focus activate (unknown chat)', (id) => ['projects', 'settings', id, 'focus', 'activate', '--chat', UNKNOWN], ['projects settings focus activate']);
			await mutate('projects settings focus deactivate (unknown chat)', (id) => ['projects', 'settings', id, 'focus', 'deactivate', '--chat', UNKNOWN], ['projects settings focus deactivate'], { expectedGap: 'exit: npm=1 native=0' });
			await mutate('projects settings command stop (unknown execution)', (id) => ['projects', 'settings', id, 'command', 'stop', UNKNOWN, '--chat', UNKNOWN], ['projects settings command stop'], { expectedGap: 'stderr class: npm=http-not-found native=other' });
			for (const action of ['enable', 'disable']) {
				await mutate(`projects settings command-presets ${action} (no source)`, (id) => ['projects', 'settings', id, 'command-presets', action, 'differential-preset'], [`projects settings command-presets ${action}`]);
				for (const kind of ['writable', 'network', 'credential']) {
					await mutate(`projects settings command-resources ${action} ${kind} (no source)`, (id) => ['projects', 'settings', id, 'command-resources', action, kind, 'differential-profile'], [`projects settings command-resources ${action} ${kind}`]);
				}
			}
			await mutate('projects items remove (unknown target)', (id) => ['projects', 'items', 'remove', id, '--type', 'chat', '--target', UNKNOWN, '--confirm'], ['projects items remove']);
			await mutate('projects sources remove (unknown source)', (id) => ['projects', 'sources', 'remove', id, '--source', UNKNOWN, '--confirm', UNKNOWN], ['projects sources remove']);
			await mutate('projects archive', (id) => ['projects', 'archive', id], ['projects archive'], { ignoreKeys: ['slug', 'short_id', 'version'] });
			await mutate('projects unarchive', (id) => ['projects', 'unarchive', id], ['projects unarchive'], { ignoreKeys: ['slug', 'short_id', 'version'] });
			await diff.check('projects ask (missing name)', ['projects', 'ask'], { mode: 'exit', catalog: ['projects ask'] });

			// Project history and restore.
			const history = await mutate('projects history', (id) => ['projects', 'history', id, '--limit', '10'], ['projects history'], { structureOnly: true, expectedGap: '$.entries: array length' });
			const entry = bothIds(history, ['entry_id', 'history_entry_id', 'id']);
			await diff.check('projects restore', ['projects', 'restore', p, '--entry', entry.npm || UNKNOWN, '--state', 'before'], {
				nativeArgs: ['projects', 'restore', n, '--entry', entry.native || UNKNOWN, '--state', 'before'],
				ignoreKeys: ['change_set_id', 'entry_id', 'version', 'version_before', 'version_after', 'encrypted_before_ref', 'encrypted_after_ref', 'restored_from_entry_id', 'rollback_entry_commands', 'undo_entry_commands', 'undo_all_command'],
				catalog: ['projects restore']
			});

			// Workspace history (change sets of each CLI's own Project).
			const changes = await mutate('history list --type project', (id) => ['history', 'list', '--type', 'project', '--id', id, '--limit', '5'], ['history list'], { structureOnly: true });
			const changeSet = bothIds(changes, ['change_set_id', 'changeSetId', 'id']);
			await diff.check('history show', ['history', 'show', changeSet.npm || UNKNOWN], {
				nativeArgs: ['history', 'show', changeSet.native || UNKNOWN],
				structureOnly: true,
				catalog: ['history show']
			});
			await diff.check('history undo', ['history', 'undo', changeSet.npm || UNKNOWN], {
				nativeArgs: ['history', 'undo', changeSet.native || UNKNOWN],
				structureOnly: true,
				catalog: ['history undo']
			});

			// Recovery projection: full-sync -> validate -> restore --dry-run, each CLI in its own home.
			const roots = { npm: path.join(diff.npmHome, 'recovery'), native: path.join(diff.nativeHome, 'recovery') };
			const synced = await diff.check('recovery full-sync', ['recovery', 'full-sync', '--project', p, '--root', roots.npm], {
				nativeArgs: ['recovery', 'full-sync', '--project', n, '--root', roots.native],
				catalog: ['recovery full-sync']
			});
			const files = {
				npm: (synced.raw && pickString(parseJson(synced.raw.npm), ['path'])) || path.join(roots.npm, `${p}.yml`),
				native: (synced.raw && pickString(parseJson(synced.raw.native), ['path'])) || path.join(roots.native, `${n}.yml`)
			};
			await diff.check('recovery validate', ['recovery', 'validate', '--file', files.npm], {
				nativeArgs: ['recovery', 'validate', '--file', files.native],
				catalog: ['recovery validate']
			});
			await diff.check('recovery restore --dry-run', ['recovery', 'restore', '--file', files.npm, '--project', p, '--dry-run'], {
				nativeArgs: ['recovery', 'restore', '--file', files.native, '--project', n, '--dry-run'],
				catalog: ['recovery restore']
			});

			// Delete (each CLI its own Project).
			await mutate('projects delete', (id) => ['projects', 'delete', id, '--confirm', id], ['projects delete']);
			cleanup.length = 0;
			await diff.check('projects show (deleted)', ['projects', 'show', p], { nativeArgs: ['projects', 'show', n], catalog: ['projects show'] });
		} finally {
			for (const undo of cleanup) await undo();
			await finishDifferential(diff);
		}
	});
});
