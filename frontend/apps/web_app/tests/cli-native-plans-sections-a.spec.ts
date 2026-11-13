/**
 * Native vs npm CLI: Plan text sections, part A (goal, scope-in, scope-out, open-questions, constraints).
 * Each action runs against the same throwaway Plan with the section reset before every CLI run.
 * Harness: helpers/cli-native-plans-sections.ts -> helpers/cli-native-differential.ts.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type { TestInfo } from '@playwright/test';

const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { runSectionChecks } = require('./helpers/cli-native-plans-sections');

const { email, password, otpKey } = getTestAccount();

test.describe('CLI native differential: plans sections A', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('plan text sections goal to constraints match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		await runSectionChecks(page, testInfo, 'plans-sections-a', ['goal', 'scope-in', 'scope-out', 'open-questions', 'constraints']);
	});
});
