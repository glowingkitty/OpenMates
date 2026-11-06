/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (CLI differential; native login is recorded in a real terminal)
/**
 * Native vs npm CLI: settings notifications and reminders commands.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');

const { email, password, otpKey } = getTestAccount();

test.describe('CLI native differential: notifications and reminders', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('notification and reminder commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'notifications');
		try {
			await diff.check('settings notifications status', ['settings', 'notifications', 'status'], { catalog: ['settings notifications status'] });
			await diff.check('settings notifications email get', ['settings', 'notifications', 'email', 'get'], { catalog: ['settings notifications email get'] });
			await diff.check('settings notifications list', ['settings', 'notifications', 'list', '--limit', '5'], { catalog: ['settings notifications list'] });
			await diff.check('settings reminders list', ['settings', 'reminders', 'list'], { catalog: ['settings reminders list'] });

			// Reversible: the fresh CI account starts with the defaults, so restore by disabling again.
			await diff.check('settings notifications email set', ['settings', 'notifications', 'email', 'set', '--enabled', 'false'], { catalog: ['settings notifications email set'] });
			await diff.check('settings notifications backup set', ['settings', 'notifications', 'backup', 'set', '--enabled', 'false', '--interval', '30'], { catalog: ['settings notifications backup set'] });
			// Documented gap: HTTP 404 is printed by npm as command_failed with the status, while the shared
			// Rust SDK transport maps 404/410 to the typed invalid_argument "requested item is unavailable".
			await diff.check('settings reminders update (unknown id)', ['settings', 'reminders', 'update', '00000000-0000-4000-8000-000000000000', '--enabled', 'false'], { expectedGap: 'stderr class: npm=http-not-found', catalog: ['settings reminders update'] });
			await diff.check('settings reminders delete (unknown id)', ['settings', 'reminders', 'delete', '00000000-0000-4000-8000-000000000000', '--yes'], { expectedGap: 'stderr class: npm=http-not-found', catalog: ['settings reminders delete'] });
		} finally {
			await finishDifferential(diff);
		}
	});
});
