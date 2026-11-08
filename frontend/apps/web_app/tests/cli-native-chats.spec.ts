/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: chats reads, drafts CRUD and embeds reads. No AI credits are used:
 * chats are created as draft-only chats (`drafts create`), so no message is ever sent.
 * Skipped on purpose (AI credits): chats send/new/retry/rewind/speak/answer-interactive/fork.
 * Each CLI creates, reads and deletes its own throwaway draft chat; embeds cannot be created
 * without a provider skill, so only help and unknown-id error paths are compared.
 *
 * Open native gaps found by CI (kept as expectedGap checks, so those commands are NOT verified):
 * - usage errors (missing positional): native clap exits 2, npm exits 1 (and classifies stderr differently);
 * - `drafts list` without --refresh: npm serves its cached list, native lists live drafts;
 * - `chats list`: native items differ (category/chatVisibility/createdAt/draftPreview fields);
 * - `chats show`: npm reports "Chat key unavailable" for a draft-only chat, native "selected saved chat
 *   is unavailable" (--all: npm exit 0, native exit 1);
 * - `chats messages`/`chats files`: different JSON shape/title for a draft-only chat;
 * - unknown chat/embed id: npm reports HTTP-not-found, native a generic unavailable/invalid-response error.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 */
export {};
import type { TestInfo } from '@playwright/test';

const path = require('node:path');
const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { bothIds } = require('./helpers/cli-native-fixtures');

const { email, password, otpKey } = getTestAccount();
const UNKNOWN = '00000000-0000-4000-8000-000000000000';
const CHAT_KEYS = ['chat_id', 'chatId', 'id'];
const USAGE_EXIT_GAP = 'exit: npm=1 native=2';
const NOT_FOUND_GAP = 'stderr class: npm=http-not-found native=other';

test.describe('CLI native differential: chats, drafts, embeds', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('chats reads, drafts CRUD and embeds reads match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'chats');
		const cleanup: Array<() => Promise<unknown>> = [];
		try {
			for (const group of ['chats', 'drafts', 'embeds']) {
				await diff.check(`${group} help`, [group], { mode: 'exit', catalog: [group] });
			}

			// Drafts: one draft-only chat per CLI.
			await diff.check('drafts list (before)', ['drafts', 'list'], { structureOnly: true, catalog: ['drafts list'] });
			await diff.check('drafts create (missing text)', ['drafts', 'create'], { mode: 'exit', expectedGap: USAGE_EXIT_GAP, catalog: ['drafts create'] });
			const created = await diff.check('drafts create', ['drafts', 'create', 'Differential draft one'], {
				ignoreKeys: ['chat_id', 'chatId', 'id', 'version', 'short_id'],
				structureOnly: true,
				catalog: ['drafts create']
			});
			const chat = bothIds(created, CHAT_KEYS);
			const p = chat.npm || UNKNOWN;
			const n = chat.native || UNKNOWN;
			if (chat.npm) cleanup.push(() => diff.npm(['chats', 'delete', chat.npm, '--yes']));
			if (chat.native) cleanup.push(() => diff.native(['chats', 'delete', chat.native, '--yes']));
			const per = (build: (id: string) => string[]) => ({ npm: build(p), native: build(n) });
			const both = (label: string, build: (id: string) => string[], catalog: string[], extra: Record<string, unknown> = {}) => {
				const argv = per(build);
				return diff.check(label, argv.npm, { nativeArgs: argv.native, catalog, ...extra });
			};

			await diff.check('drafts list', ['drafts', 'list'], { structureOnly: true, expectedGap: '$.drafts: array length', catalog: ['drafts list'] });
			await diff.check('drafts list --refresh', ['drafts', 'list', '--refresh'], { structureOnly: true, catalog: ['drafts list'] });
			await both('drafts get', (id) => ['drafts', 'get', id], ['drafts get'], { structureOnly: true });
			await both('drafts update', (id) => ['drafts', 'update', id, 'Differential draft two'], ['drafts update'], { structureOnly: true });
			await both('drafts get (updated)', (id) => ['drafts', 'get', id], ['drafts get'], { structureOnly: true });
			await diff.check('drafts sync', ['drafts', 'sync'], { structureOnly: true, catalog: ['drafts sync'] });
			await diff.check('drafts get (missing id)', ['drafts', 'get'], { mode: 'exit', expectedGap: USAGE_EXIT_GAP, catalog: ['drafts get'] });
			await diff.check('drafts update (missing text)', ['drafts', 'update', p], { nativeArgs: ['drafts', 'update', n], mode: 'exit', expectedGap: USAGE_EXIT_GAP, catalog: ['drafts update'] });

			// Chats: reads.
			await diff.check('chats list', ['chats', 'list'], { structureOnly: true, expectedGap: '$.chats[0].category', catalog: ['chats list'] });
			await diff.check('chats list --limit --page', ['chats', 'list', '--limit', '2', '--page', '1'], { structureOnly: true, expectedGap: '$.chats[0].category', catalog: ['chats list'] });
			await diff.check('chats search', ['chats', 'search', 'Differential'], { structureOnly: true, catalog: ['chats search'] });
			await diff.check('chats search (missing query)', ['chats', 'search'], { mode: 'exit', expectedGap: USAGE_EXIT_GAP, catalog: ['chats search'] });
			await both('chats show', (id) => ['chats', 'show', id], ['chats show'], { structureOnly: true, expectedGap: 'stderr class: npm=other native=validation' });
			await both('chats show --all', (id) => ['chats', 'show', id, '--all'], ['chats show'], { structureOnly: true, expectedGap: 'exit: npm=0 native=1' });
			await both('chats messages', (id) => ['chats', 'messages', id], ['chats messages'], { structureOnly: true, expectedGap: '$.chat: only in npm' });
			await both('chats files', (id) => ['chats', 'files', id], ['chats files'], { structureOnly: true, expectedGap: '$.title' });
			await diff.check('chats show (unknown)', ['chats', 'show', UNKNOWN], { mode: 'exit', expectedGap: NOT_FOUND_GAP, catalog: ['chats show'] });
			await diff.check('chats show (missing id)', ['chats', 'show'], { mode: 'exit', expectedGap: USAGE_EXIT_GAP, catalog: ['chats show'] });
			await diff.check('chats messages (unknown)', ['chats', 'messages', UNKNOWN], { mode: 'exit', expectedGap: NOT_FOUND_GAP, catalog: ['chats messages'] });
			await both('chats download', (id) => ['chats', 'download', id, '--output', path.join(id === p ? diff.npmHome : diff.nativeHome, 'chat.md')], ['chats download'], { mode: 'exit' });
			await diff.check('chats download (unknown)', ['chats', 'download', UNKNOWN, '--output', path.join(diff.npmHome, 'x.md')], {
				nativeArgs: ['chats', 'download', UNKNOWN, '--output', path.join(diff.nativeHome, 'x.md')],
				mode: 'exit',
				expectedGap: NOT_FOUND_GAP,
				catalog: ['chats download']
			});

			// Drafts clear, then delete the draft chats.
			await both('drafts clear', (id) => ['drafts', 'clear', id], ['drafts clear'], { structureOnly: true });
			await diff.check('drafts clear (missing id)', ['drafts', 'clear'], { mode: 'exit', expectedGap: USAGE_EXIT_GAP, catalog: ['drafts clear'] });
			await both('chats delete', (id) => ['chats', 'delete', id, '--yes'], ['chats delete'], { mode: 'exit' });
			cleanup.length = 0;
			await diff.check('chats delete (missing id)', ['chats', 'delete'], { mode: 'exit', expectedGap: USAGE_EXIT_GAP, catalog: ['chats delete'] });

			// Embeds: no embed can be created without a provider skill; compare error paths.
			await diff.check('embeds show (unknown)', ['embeds', 'show', UNKNOWN], { mode: 'exit', expectedGap: 'stderr class: npm=http-not-found native=validation', catalog: ['embeds show'] });
			await diff.check('embeds show (missing id)', ['embeds', 'show'], { mode: 'exit', expectedGap: USAGE_EXIT_GAP, catalog: ['embeds show'] });
		} finally {
			for (const undo of cleanup) await undo();
			await finishDifferential(diff);
		}
	});
});
