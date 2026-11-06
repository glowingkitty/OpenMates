/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (CLI differential; native login is recorded in a real terminal)
/**
 * Native vs npm CLI: settings billing commands (read-only; no payment or purchase commands).
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');

const { email, password, otpKey } = getTestAccount();

test.describe('CLI native differential: billing', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('read-only billing commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'billing');
		try {
			// Documented gap: the isolated backend answers these routes with HTTP 404/422. npm prints a
			// command_failed error with the HTTP status; the native binary maps the same status to an
			// invalid_argument error with a generic message (and exit 2 for two of the routes).
			const unavailable = new Set(['usage summaries', 'usage export', 'invoices list', 'gift-card list', 'gift-card purchased', 'bank-transfer list', 'address show']);
			const read = async (name: string, args: string[], catalog = `settings billing ${name}`) =>
				diff.check(`settings billing ${name}`, ['settings', 'billing', ...args], {
					catalog: [catalog],
					expectedGap: unavailable.has(name) ? 'stderr class: npm=http-' : undefined
				});
			await read('overview', ['overview']);
			await read('usage', ['usage']);
			await read('usage overview', ['usage', 'overview']);
			await read('usage summaries', ['usage', 'summaries']);
			await read('usage daily', ['usage', 'daily']);
			await read('usage export', ['usage', 'export']);
			await read('invoices list', ['invoices', 'list']);
			await read('gift-card list', ['gift-card', 'list']);
			await read('gift-card purchased', ['gift-card', 'purchased']);
			await read('bank-transfer list', ['bank-transfer', 'list']);
			await read('address show', ['address', 'show']);
			await diff.check('settings billing buy-credits (web-only notice)', ['settings', 'billing', 'buy-credits'], { mode: 'exit', catalog: ['settings billing buy-credits'] });
			await diff.check('settings billing auto-topup monthly (web-only notice)', ['settings', 'billing', 'auto-topup', 'monthly'], { mode: 'exit', catalog: ['settings billing auto-topup monthly'] });
		} finally {
			await finishDifferential(diff);
		}
	});
});
