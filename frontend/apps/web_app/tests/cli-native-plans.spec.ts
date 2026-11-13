/**
 * Native vs npm CLI: the `plans` reads, edits, history/restore, dependencies and revisions.
 * Other plan specs: cli-native-plans-lifecycle (state transitions), -sections-a/-b (text sections),
 * -children / -children-b (assumptions, criteria, checks, learnings). Each spec stays under the
 * 20-minute CI spec timeout.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 *
 * Fixtures are created with the npm CLI in a throwaway Project and removed afterwards.
 * Commands that mutate shared state reset it before each CLI run (`before`); one-way
 * state transitions give each CLI its own identical fresh fixture (`argsFor`), so only
 * the per-fixture `short_id` and the optimistic-lock `version` counter are ignored.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { VOLATILE, createFixtures, logAbort, npmJson, perSide } = require('./helpers/cli-native-plans-fixtures');

const { email, password, otpKey } = getTestAccount();

type Side = 'npm' | 'native';

test.describe('CLI native differential: plans', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('plan reads, edits and dependencies match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'plans', { paceMs: 4_000 });
		const fx = await createFixtures(diff, 'reads');
		try {
			const base = await fx.plan('Differential base plan');
			const other = await fx.plan('Differential dependency target');
			await diff.check('plans group help', ['plans'], { mode: 'exit', catalog: ['plans'] });
			await diff.check('plans list', ['plans', 'list', '--project', fx.projectId], { catalog: ['plans list'] });
			await diff.check('plans status (list)', ['plans', 'status', '--project', fx.projectId], { catalog: ['plans status'] });
			await diff.check('plans status <id>', ['plans', 'status', base], { catalog: ['plans status'] });
			await diff.check('plans show', ['plans', 'show', base], { catalog: ['plans show'] });

			for (const verb of ['edit', 'update']) {
				await diff.check(`plans ${verb}`, ['plans', verb, base, '--title', 'Differential base plan', '--goal', 'Edited goal'], { ignoreKeys: VOLATILE, catalog: [`plans ${verb}`] });
			}
			// npm silently ignores `plans edit --summary` (no Plan summary field); native refuses it explicitly.
			await diff.check('plans edit --summary', ['plans', 'edit', base, '--summary', 'Ignored'], { ignoreKeys: VOLATILE, expectedGap: 'exit: npm=0 native=1' });
			await npmJson(diff, ['plans', 'goal', 'set', base, '--text', 'Goal to restore'], 'goal change for restore');
			await diff.check('plans history', ['plans', 'history', base, '--limit', '5'], { catalog: ['plans history'] });
			// Known gap: CI answers the restore with HTTP 409 for both CLIs; npm reports command_failed, native a conflict error.
			// A restore consumes its entry: each CLI restores the newest (highest version) update entry of
			// its own fresh edit; restoring the create entry would delete the Plan.
			const restorable = perSide(async (side: Side) => {
				await npmJson(diff, ['plans', 'goal', 'set', base, '--text', `Goal to restore ${side}`], 'goal change for restore');
				const history = await npmJson(diff, ['plans', 'history', base, '--limit', '500'], 'plan history');
				const entries = history.entries ?? history.history ?? history.items;
				expect(Array.isArray(entries) && entries.length > 1, JSON.stringify(history).slice(0, 400)).toBeTruthy();
				const newest = entries.reduce((a: any, b: any) => ((b.version_after ?? 0) > (a.version_after ?? 0) ? b : a));
				return (newest.entry_id ?? newest.id) as string;
			});
			await diff.check('plans restore', [], { before: restorable.before, argsFor: (side: Side) => ['plans', 'restore', base, '--entry', restorable.get(side), '--state', 'before'], ignoreKeys: VOLATILE, expectedGap: 'stderr class: npm=http-client-error native=other', catalog: ['plans restore'] });

			await diff.check('plans dependencies list', ['plans', 'dependencies', 'list', base], { catalog: ['plans dependencies list'] });
			const detach = async () => { await diff.npm(['plans', 'dependencies', 'remove', base, '--target', `plan:${other}`, '--json']); };
			const attach = async () => { await diff.npm(['plans', 'dependencies', 'add', base, '--target', `plan:${other}`, '--json']); };
			await diff.check('plans dependencies add', ['plans', 'dependencies', 'add', base, '--target', `plan:${other}`], { before: detach, ignoreKeys: VOLATILE, catalog: ['plans dependencies add'] });
			await diff.check('plans dependencies remove', ['plans', 'dependencies', 'remove', base, '--target', `plan:${other}`], { before: attach, ignoreKeys: VOLATILE, catalog: ['plans dependencies remove'] });

			await diff.check('plans revisions list', ['plans', 'revisions', 'list', base], { structureOnly: true, catalog: ['plans revisions list'] });
			await diff.check('plans revisions status', ['plans', 'revisions', 'status', base], { catalog: ['plans revisions status'] });
			await diff.check('plans revisions diff (web-only)', ['plans', 'revisions', 'diff', base], { mode: 'exit', catalog: ['plans revisions diff'] });
			// Each submission is a new immutable revision: number, fingerprint and encrypted snapshot are per run.
			await diff.check('plans revisions submit-for-review', ['plans', 'revisions', 'submit-for-review', base], { structureOnly: true, catalog: ['plans revisions submit-for-review'] });
		} catch (error) {
			logAbort(error);
		} finally {
			await fx.cleanup();
			await finishDifferential(diff);
		}
	});
});
