/**
 * Native vs npm CLI: the `plans` child records, part A (assumptions and success criteria).
 * Part B (checks, learnings) is cli-native-plans-children-b.spec.ts; the split keeps each spec under
 * the 20-minute CI spec timeout.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 *
 * Fixtures are created with the npm CLI in a throwaway Project and removed afterwards.
 * Commands that mutate shared state reset it before each CLI run (`before`); one-way
 * state transitions give each CLI its own identical fresh fixture (`argsFor`), so only
 * the per-fixture `short_id` and the optimistic-lock `version` counter are ignored.
 *
 * Documented native gaps (those commands are NOT marked verified in the catalog):
 *  - assumptions/criteria add|create|edit|update: npm prints the raw server ciphertext
 *    (`encrypted_*`), native prints decrypted text.
 *  - criteria edit --optional: the server ignores `required` on PATCH; npm reports success,
 *    native refuses `--optional`.
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

test.describe('CLI native differential: plans assumptions and criteria', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('plan assumptions and criteria match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'plans-children', { paceMs: 4_000 });
		const fx = await createFixtures(diff, 'children');
		try {
			const base = await fx.plan('Differential child plan');

			await diff.check('plans assumptions list', ['plans', 'assumptions', 'list', base], { catalog: ['plans assumptions list'] });
			for (const verb of ['add', 'create']) {
				await diff.check(`plans assumptions ${verb}`, ['plans', 'assumptions', verb, base, '--text', 'Users have a browser'], { expectedGap: NPM_CIPHERTEXT_GAP, catalog: [`plans assumptions ${verb}`] });
			}
			const assumption = perSide(async () => (await npmJson(diff, ['plans', 'assumptions', 'create', base, '--text', 'To correct'], 'assumption')).assumption.assumption_id as string);
			await diff.check('plans assumptions update', [], { before: assumption.before, argsFor: (side: Side) => ['plans', 'assumptions', 'update', base, '--assumption', assumption.get(side), '--corrected', 'Corrected'], expectedGap: NPM_CIPHERTEXT_GAP, catalog: ['plans assumptions update'] });

			for (const kind of ['success-criteria', 'criteria', 'criterion']) {
				for (const verb of ['add', 'create']) {
					await diff.check(`plans ${kind} ${verb}`, ['plans', kind, verb, base, '--text', 'Checkout works'], { expectedGap: NPM_CIPHERTEXT_GAP, catalog: [`plans ${kind} ${verb}`] });
				}
				const criterion = perSide(async () => (await npmJson(diff, ['plans', 'criteria', 'add', base, '--text', 'Fixture criterion'], 'criterion')).criterion.criterion_id as string);
				for (const verb of ['edit', 'update']) {
					await diff.check(`plans ${kind} ${verb}`, [], { before: criterion.before, argsFor: (side: Side) => ['plans', kind, verb, base, '--criterion', criterion.get(side), '--status', 'satisfied'], expectedGap: NPM_CIPHERTEXT_GAP, catalog: [`plans ${kind} ${verb}`] });
				}
				await diff.check(`plans ${kind} edit --optional`, [], { before: criterion.before, argsFor: (side: Side) => ['plans', kind, 'edit', base, '--criterion', criterion.get(side), '--optional'], expectedGap: 'exit: npm=0 native=1', catalog: [`plans ${kind} edit`] });
				for (const verb of ['remove', 'delete']) {
					await diff.check(`plans ${kind} ${verb}`, [], { before: criterion.before, argsFor: (side: Side) => ['plans', kind, verb, base, '--criterion', criterion.get(side)], ignoreKeys: VOLATILE, catalog: [`plans ${kind} ${verb}`] });
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
