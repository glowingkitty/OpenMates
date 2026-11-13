/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: settings records not covered by the account/billing/notifications specs
 * (web-only notices, memories, mates, newsletter, privacy, developers, report-issue, imports,
 * exports and the remaining billing reads). Payment-creating commands are never run.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 */
export {};
import type { TestInfo } from '@playwright/test';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');

const { email, password, otpKey } = getTestAccount();
const UNKNOWN_ID = '00000000-0000-4000-8000-000000000000';
const FIXTURES = path.join(__dirname, 'fixtures');

function parseJson(stdout: string): any {
	return JSON.parse(stdout.trim());
}

test.describe('CLI native differential: settings', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('remaining settings commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'settings');
		const work = fs.mkdtempSync(path.join(os.tmpdir(), 'diff-settings-'));
		try {
			const s = (...args: string[]) => ['settings', ...args];

			// Bare groups and informational web-only notices: no account access.
			await diff.check('settings (help)', ['settings'], { mode: 'exit', catalog: ['settings'] });
			await diff.check('settings memories (help)', s('memories'), { mode: 'exit', catalog: ['settings memories'] });
			const notices: string[][] = [
				['security'], ['security', '2fa'], ['security', 'passkeys'], ['security', 'password'],
				['security', 'recovery-key'], ['security', 'sessions'], ['server'], ['shared', 'tip'], ['support'],
				['incognito', 'info'], ['privacy', 'personal-data'], ['developers', 'devices'], ['developers', 'webhooks'],
				['billing', 'gift-card', 'buy']
			];
			for (const notice of notices) {
				const name = `settings ${notice.join(' ')}`;
				await diff.check(`${name} (notice)`, s(...notice), { catalog: [name] });
			}

			// Read-only account reads.
			await diff.check('settings mates list', s('mates', 'list'), { catalog: ['settings mates list'] });
			await diff.check('settings mates info', s('mates', 'info', 'software_development'), { catalog: ['settings mates info'] });
			await diff.check('settings newsletter categories', s('newsletter', 'categories'), { catalog: ['settings newsletter categories'] });
			await diff.check('settings memories types', s('memories', 'types', '--app-id', 'code'), { catalog: ['settings memories types'] });
			await diff.check('settings developers api-keys list', s('developers', 'api-keys', 'list'), { catalog: ['settings developers api-keys list'] });
			await diff.check('settings gift-card list', s('gift-card', 'list'), { catalog: ['settings gift-card list'] });
			await diff.check('settings billing usage chat-total', s('billing', 'usage', 'chat-total', '--chat-id', UNKNOWN_ID), { catalog: ['settings billing usage chat-total'] });
			await diff.check('settings billing usage details', s('billing', 'usage', 'details', '--type', 'chat', '--identifier', UNKNOWN_ID, '--month', '2026-08'), { catalog: ['settings billing usage details'] });

			// Unknown-id error paths (read-only or refused before any state changes).
			// Documented npm defects: npm reads the id from the wrong argv index and fails before the request.
			const npmDefects: Record<string, string> = {
				'settings billing gift-card purchase-status': 'Missing order ID.',
				'settings account storage delete': 'Missing file ID.'
			};
			const unknown: Array<[string, string[]]> = [
				['settings billing bank-transfer status', s('billing', 'bank-transfer', 'status', UNKNOWN_ID)],
				['settings billing gift-card purchase-status', s('billing', 'gift-card', 'purchase-status', UNKNOWN_ID)],
				['settings billing invoices download', s('billing', 'invoices', 'download', UNKNOWN_ID, '--output', work)],
				['settings billing invoices credit-note', s('billing', 'invoices', 'credit-note', UNKNOWN_ID, '--output', work)],
				['settings billing gift-card redeem', s('billing', 'gift-card', 'redeem', 'DIFF-0000-0000')],
				['settings gift-card redeem', s('gift-card', 'redeem', 'DIFF-0000-0000')],
				['settings report-issue status', s('report-issue', 'status', UNKNOWN_ID)],
				['settings account storage delete', s('account', 'storage', 'delete', UNKNOWN_ID, '--yes')],
				['settings account export status', s('account', 'export', 'status', UNKNOWN_ID)],
				['settings account export manifest', s('account', 'export', 'manifest', UNKNOWN_ID)],
				['settings account export chunks', s('account', 'export', 'chunks', UNKNOWN_ID)],
				['settings account export data', s('account', 'export', 'data', UNKNOWN_ID)],
				['settings account export accept-partial', s('account', 'export', 'accept-partial', UNKNOWN_ID)],
				['settings account export cancel', s('account', 'export', 'cancel', UNKNOWN_ID)],
				['settings newsletter confirm', s('newsletter', 'confirm', 'invalid-differential-token')],
				['settings newsletter unsubscribe', s('newsletter', 'unsubscribe', 'invalid-differential-token')],
				['settings newsletter subscribe', s('newsletter', 'subscribe', 'not-an-email')]
			];
			for (const [name, args] of unknown) {
				await diff.check(`${name} (error path)`, args, { catalog: [name], ...(npmDefects[name] ? { expectedGap: npmDefects[name] } : {}) });
			}

			// Import dry-runs from generated transcripts (no account writes).
			const generic = path.join(work, 'generic.json');
			fs.writeFileSync(generic, JSON.stringify({ id: 'diff-generic', title: 'Differential', messages: [{ role: 'user', content: 'Hello' }, { role: 'assistant', content: 'Hi there' }] }));
			const claude = path.join(work, 'claude.json');
			fs.writeFileSync(claude, JSON.stringify([{ uuid: 'diff-claude', name: 'Differential', chat_messages: [{ uuid: 'm1', sender: 'human', text: 'Hello' }, { uuid: 'm2', sender: 'assistant', text: 'Hi there' }] }]));
			const chatgpt = path.join(work, 'chatgpt.json');
			fs.writeFileSync(chatgpt, JSON.stringify([{ id: 'diff-chatgpt', title: 'Differential', current_node: 'n2', mapping: {
				n1: { id: 'n1', parent: null, message: { id: 'n1', author: { role: 'user' }, content: { content_type: 'text', parts: ['Hello'] }, create_time: 1 } },
				n2: { id: 'n2', parent: 'n1', message: { id: 'n2', author: { role: 'assistant' }, content: { content_type: 'text', parts: ['Hi there'] }, create_time: 2 } }
			} }]));
			const opencode = path.join(work, 'opencode.json');
			fs.writeFileSync(opencode, JSON.stringify({ info: { id: 'diff-opencode', title: 'Differential' }, messages: [
				{ info: { id: 'm1', role: 'user', time: { created: 1_700_000_000_000 } }, parts: [{ type: 'text', text: 'Hello' }] },
				{ info: { id: 'm2', role: 'assistant', time: { created: 1_700_000_001_000 } }, parts: [{ type: 'text', text: 'Hi there' }] }
			] }));
			await diff.check('settings account import generic', s('account', 'import', 'generic', generic, '--source', 'gemini', '--dry-run'), { catalog: ['settings account import generic'] });
			await diff.check('settings account import claude', s('account', 'import', 'claude', claude, '--dry-run'), { catalog: ['settings account import claude'] });
			await diff.check('settings account import chatgpt', s('account', 'import', 'chatgpt', chatgpt, '--dry-run'), { catalog: ['settings account import chatgpt'] });
			await diff.check('settings account import opencode', s('account', 'import', 'opencode', opencode, '--dry-run'), { catalog: ['settings account import opencode'] });
			await diff.check('settings account import openmates (not an export)', s('account', 'import', 'openmates', path.join(FIXTURES, 'import-chats-test.zip'), '--dry-run'), { catalog: ['settings account import openmates'] });
			await diff.check('settings account import-chat', s('account', 'import-chat', path.join(FIXTURES, 'import-chat-1.yml')), { structureOnly: true, catalog: ['settings account import-chat'] });

			// Memories: create -> list -> update -> delete; each CLI acts on its own entry.
			const memoryData = JSON.stringify({ name: 'DiffLang-native', proficiency: 'intermediate' });
			const memoryArgs = ['--app-id', 'code', '--item-type', 'preferred_tech'];
			await diff.check('settings memories create', s('memories', 'create', ...memoryArgs, '--data', memoryData), { ignoreKeys: ['id'], catalog: ['settings memories create'] });
			await diff.check('settings memories list', s('memories', 'list', ...memoryArgs), { catalog: ['settings memories list'], timeoutMs: 90_000 });
			const entries = parseJson((await diff.npm(s('memories', 'list', ...memoryArgs, '--json'), 90_000)).stdout)
				.filter((entry: any) => entry?.data?.name === 'DiffLang-native');
			if (entries.length !== 2) throw new Error(`expected one memory entry per CLI, found ${entries.length}`);
			const [first, second] = entries;
			const updateArgs = (entry: any) => s('memories', 'update', '--id', entry.id, ...memoryArgs, '--data', JSON.stringify({ name: 'DiffLang-native', proficiency: 'advanced' }), '--version', String(entry.item_version));
			await diff.check('settings memories update', updateArgs(first), { nativeArgs: updateArgs(second), catalog: ['settings memories update'] });
			await diff.check('settings memories delete', s('memories', 'delete', '--id', first.id), { nativeArgs: s('memories', 'delete', '--id', second.id), catalog: ['settings memories delete'] });

			// API keys: create one per CLI, then each CLI revokes its own key.
			// Reversible preference writes (the CI account is throwaway; restore where a prior value exists).
			const info = parseJson((await diff.npm(['account', 'info', '--json'])).stdout);
			const username = typeof info.username === 'string' && info.username ? info.username : null;
			await diff.check('settings account username set', s('account', 'username', 'set', `diffuser${Date.now().toString(36)}`), { catalog: ['settings account username set'] });
			if (username) await diff.npm(s('account', 'username', 'set', username, '--json'));
			// The CI stack has no reachable upload service: npm fails with "fetch failed" while native reports the
			// upload token rejection. Both exit 1; only the stderr class differs, so the gap is recorded.
			await diff.check('settings account profile-picture set', s('account', 'profile-picture', 'set', path.join(FIXTURES, 'finance.jpeg')), { structureOnly: true, catalog: ['settings account profile-picture set'], expectedGap: 'stderr class: npm=other native=validation' });
			await diff.check('settings ai models set-defaults', s('ai', 'models', 'set-defaults', '--simple', 'auto', '--complex', 'auto', '--most-demanding', 'auto'), { catalog: ['settings ai models set-defaults'] });
			await diff.check('settings privacy auto-delete chats set', s('privacy', 'auto-delete', 'chats', 'set', '90d'), { catalog: ['settings privacy auto-delete chats set'] });
			await diff.check('settings privacy debug-logs share', s('privacy', 'debug-logs', 'share', '--duration', '1h', '--confirm'), { structureOnly: true, catalog: ['settings privacy debug-logs share'] });
			await diff.check('settings mates consent', s('mates', 'consent', '--yes'), { catalog: ['settings mates consent'] });
			await diff.check('settings newsletter categories set', s('newsletter', 'categories', 'set', '--updates', 'true', '--tips', 'true', '--daily', 'false'), { catalog: ['settings newsletter categories set'] });
			await diff.check('settings report-issue create', s('report-issue', 'create', '--title', 'CLI differential check', '--body', 'Automated npm vs native CLI differential test on the isolated CI backend.'), { structureOnly: true, catalog: ['settings report-issue create'] });

			// Buyer address (non-payment profile data): set then clear.
			const address = path.join(work, 'address.json');
			fs.writeFileSync(address, JSON.stringify({ name: 'Differential Test', street_line_1: 'Example Street 1', postal_code: '10115', city: 'Berlin', country: 'DE' }));
			await diff.check('settings billing address set', s('billing', 'address', 'set', '--billing-address-file', address), { catalog: ['settings billing address set'] });
			await diff.check('settings billing address clear', s('billing', 'address', 'clear'), { catalog: ['settings billing address clear'] });
			// Last: api-keys create needs recent verification. npm reports it as a plain error while native maps
			// it to session_expired and drops its session, so nothing may run on the native session after this.
			await diff.check('settings developers api-keys create', s('developers', 'api-keys', 'create', 'diff-native-key', '--yes'), { ignoreKeys: ['id', 'api_key', 'key_prefix'], catalog: ['settings developers api-keys create'] });
			const keys = parseJson((await diff.npm(s('developers', 'api-keys', 'list', '--json'))).stdout);
			const keyList = (Array.isArray(keys) ? keys : keys.api_keys ?? keys.keys ?? []).filter((key: any) => key?.name === 'diff-native-key');
			if (keyList.length === 2) {
				await diff.check('settings developers api-keys revoke', s('developers', 'api-keys', 'revoke', keyList[0].id, '--yes'), { nativeArgs: s('developers', 'api-keys', 'revoke', keyList[1].id, '--yes'), catalog: ['settings developers api-keys revoke'] });
			} else {
				for (const key of keyList) await diff.npm(s('developers', 'api-keys', 'revoke', key.id, '--yes', '--json'));
				await diff.check('settings developers api-keys revoke (unknown id)', s('developers', 'api-keys', 'revoke', UNKNOWN_ID, '--yes'), { expectedGap: 'stderr class: npm=http-auth native=auth-required', catalog: ['settings developers api-keys revoke'] });
			}

		} finally {
			fs.rmSync(work, { recursive: true, force: true });
			await finishDifferential(diff);
		}
	});
});
