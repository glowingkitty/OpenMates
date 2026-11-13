/**
 * Native vs npm CLI: the `plans` child records, part B (checks/check/verification and learnings/learning).
 * Part A (assumptions and criteria) is cli-native-plans-children.spec.ts; the split keeps each spec under
 * the 20-minute CI spec timeout.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 *
 * Documented native gaps (those commands are NOT marked verified in the catalog):
 *  - checks/check/verification add|create|edit|update|evidence|record: npm prints the raw server
 *    ciphertext (`encrypted_*`), native prints decrypted text.
 *  - learning(s) create-tasks: a server HTTP 400 is `command_failed` (http-client-error) in npm, but the
 *    SDK path in native reports `invalid_argument` (validation); exit codes agree.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type { TestInfo } from '@playwright/test';

const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { NPM_CIPHERTEXT_GAP, VOLATILE, createFixtures, logAbort, npmJson, perSide } = require('./helpers/cli-native-plans-fixtures');

const { email, password, otpKey } = getTestAccount();

type Side = 'npm' | 'native';

test.describe('CLI native differential: plans checks and learnings', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('plan checks and learnings match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'plans-children-b', { paceMs: 4_000 });
		const fx = await createFixtures(diff, 'children-b');
		try {
			const base = await fx.plan('Differential check plan');

			for (const kind of ['checks', 'check', 'verification']) {
				for (const verb of ['add', 'create']) {
					await diff.check(`plans ${kind} ${verb}`, ['plans', kind, verb, base, '--kind', 'manual_check', '--expected', 'Page loads'], { expectedGap: NPM_CIPHERTEXT_GAP, catalog: [`plans ${kind} ${verb}`] });
				}
				const check = perSide(async () => (await npmJson(diff, ['plans', 'checks', 'add', base, '--kind', 'manual_check', '--expected', 'Fixture'], 'check')).verification.verification_id as string);
				for (const verb of ['edit', 'update']) {
					await diff.check(`plans ${kind} ${verb}`, [], { before: check.before, argsFor: (side: Side) => ['plans', kind, verb, base, '--verification', check.get(side), '--description', 'Edited check'], expectedGap: NPM_CIPHERTEXT_GAP, catalog: [`plans ${kind} ${verb}`] });
				}
				for (const verb of ['evidence', 'record']) {
					await diff.check(`plans ${kind} ${verb}`, [], { before: check.before, argsFor: (side: Side) => ['plans', kind, verb, base, '--verification', check.get(side), '--status', 'passed', '--summary', 'Looked good'], expectedGap: NPM_CIPHERTEXT_GAP, catalog: [`plans ${kind} ${verb}`] });
				}
				for (const verb of ['remove', 'delete']) {
					await diff.check(`plans ${kind} ${verb}`, [], { before: check.before, argsFor: (side: Side) => ['plans', kind, verb, base, '--verification', check.get(side)], ignoreKeys: VOLATILE, catalog: [`plans ${kind} ${verb}`] });
				}
			}

			const shown = (await npmJson(diff, ['plans', 'learnings', 'add', base, '--title', 'Shown learning'], 'learning')).learning.learning_id as string;
			for (const kind of ['learnings', 'learning']) {
				await diff.check(`plans ${kind} list`, ['plans', kind, 'list', base], { catalog: [`plans ${kind} list`] });
				await diff.check(`plans ${kind} show`, ['plans', kind, 'show', base, '--learning', shown], { catalog: [`plans ${kind} show`] });
				for (const verb of ['add', 'create']) {
					await diff.check(`plans ${kind} ${verb}`, ['plans', kind, verb, base, '--title', 'Retry flaky step', '--observation', 'Step flaked'], { catalog: [`plans ${kind} ${verb}`] });
				}
				const learning = perSide(async () => (await npmJson(diff, ['plans', 'learnings', 'add', base, '--title', 'Fixture learning', '--status', 'accepted', '--task-draft', 'Add a retry'], 'learning')).learning.learning_id as string);
				for (const verb of ['edit', 'update']) {
					await diff.check(`plans ${kind} ${verb}`, [], { before: learning.before, argsFor: (side: Side) => ['plans', kind, verb, base, '--learning', learning.get(side), '--title', 'Edited learning'], catalog: [`plans ${kind} ${verb}`] });
				}
				await diff.check(`plans ${kind} create-tasks`, [], { before: learning.before, argsFor: (side: Side) => ['plans', kind, 'create-tasks', base, '--learning', learning.get(side)], ignoreKeys: VOLATILE, expectedGap: 'stderr class: npm=http-client-error native=validation', catalog: [`plans ${kind} create-tasks`] });
				for (const verb of ['remove', 'delete']) {
					await diff.check(`plans ${kind} ${verb}`, [], { before: learning.before, argsFor: (side: Side) => ['plans', kind, verb, base, '--learning', learning.get(side)], catalog: [`plans ${kind} ${verb}`] });
				}
			}
		} catch (error) {
			logAbort(error);
		} finally {
			await fx.cleanup();
			await finishDifferential(diff);
		}
	});
});
