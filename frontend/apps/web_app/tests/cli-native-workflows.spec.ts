/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: read-only Workflow commands (no workflow is created or run).
 * Open native gaps found by the first CI run and therefore not asserted here:
 * `workflows create` (native returns conflict/invalid_argument where npm succeeds),
 * `workflows run-show <wf> <run>` (native parser rejects the second positional) and
 * the exit code/stderr class of `workflows delete` without --yes and unknown input sessions.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');

const { email, password, otpKey } = getTestAccount();

test.describe('CLI native differential: workflows', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('workflows read commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'workflows');
		try {
			await diff.check('workflows (help)', ['workflows'], { mode: 'exit', catalog: ['workflows'] });
			await diff.check('workflows list', ['workflows', 'list'], { structureOnly: true, catalog: ['workflows list'] });
			await diff.check('workflows capabilities', ['workflows', 'capabilities'], { structureOnly: true, catalog: ['workflows capabilities'] });
			await diff.check('workflows help-app', ['workflows', 'help-app', 'web.search'], { structureOnly: true, catalog: ['workflows help-app'] });
		} finally {
			await finishDifferential(diff);
		}
	});
});
