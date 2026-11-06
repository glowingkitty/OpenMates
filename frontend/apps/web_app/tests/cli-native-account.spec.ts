/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (CLI differential; native login is recorded in a real terminal)
/**
 * Native vs npm CLI: account, interface, credits, whoami and connected-accounts commands.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');

const { email, password, otpKey } = getTestAccount();

test.describe('CLI native differential: account', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('read-only and reversible account commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'account');
		try {
			// Read-only.
			await diff.check('whoami', ['whoami'], { catalog: ['whoami'] });
			await diff.check('credits', ['credits'], { catalog: ['credits'] });
			for (const prefix of [[], ['settings']]) {
				const tag = prefix.length ? 'settings ' : '';
				await diff.check(`${tag}account info`, [...prefix, 'account', 'info'], { catalog: [`${tag}account info`] });
				await diff.check(`${tag}account storage overview`, [...prefix, 'account', 'storage', 'overview'], { catalog: [`${tag}account storage overview`] });
				await diff.check(`${tag}account storage files`, [...prefix, 'account', 'storage', 'files'], { catalog: [`${tag}account storage files`] });
				await diff.check(`${tag}account chats stats`, [...prefix, 'account', 'chats', 'stats'], { catalog: [`${tag}account chats stats`] });
				await diff.check(`${tag}account interests list`, [...prefix, 'account', 'interests', 'list'], { catalog: [`${tag}account interests list`] });
			}
			await diff.check('account delete preview', ['account', 'delete', 'preview'], { catalog: ['account delete preview', 'settings account delete preview'] });
			await diff.check('account email (web-only notice)', ['account', 'email'], { mode: 'exit', catalog: ['account email', 'settings account email'] });
			await diff.check('connected-accounts help', ['connected-accounts'], { mode: 'exit', catalog: ['connected-accounts'] });
			await diff.check('connect-account revolut consent-url', ['connect-account', 'revolut', 'consent-url', '--client-id', 'differential-client'], { catalog: ['connect-account revolut consent-url'] });

			// Reversible mutations: baseline from the npm CLI, set on both, restore.
			const before = JSON.parse((await diff.npm(['account', 'info', '--json'])).stdout);
			const timezone = String(before.timezone ?? 'Europe/Berlin');
			await diff.check('account timezone set', ['account', 'timezone', 'set', 'Europe/Paris'], { catalog: ['account timezone set', 'settings account timezone set'] });
			await diff.npm(['account', 'timezone', 'set', timezone, '--json']);
			await diff.check('account interests set', ['account', 'interests', 'set', 'privacy', 'run_code'], { catalog: ['account interests set', 'settings account interests set'] });
			await diff.check('account interests clear', ['account', 'interests', 'clear', '--yes'], { catalog: ['account interests clear', 'settings account interests clear'] });
			// Documented gap: the npm CLI posts {dark_mode} but the backend field is `darkmode` (HTTP 422);
			// the native binary posts the correct field and succeeds.
			await diff.check('settings interface dark-mode set', ['settings', 'interface', 'dark-mode', 'set', 'on'], { expectedGap: 'exit: npm=1 native=0', catalog: ['settings interface dark-mode set'] });
			await diff.check('settings interface font set', ['settings', 'interface', 'font', 'set', 'lexend'], { catalog: ['settings interface font set'] });
			await diff.check('settings interface language set', ['settings', 'interface', 'language', 'set', 'en'], { catalog: ['settings interface language set'] });
		} finally {
			await finishDifferential(diff);
		}
	});
});
