/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (CLI JSON contract; web save and reuse are recorded by memory-reuse.spec.ts)
/**
 * Native Rust CLI: the assistant saves a Memory and a later chat reuses it,
 * real stack (plan assistant-memory-writes T-CLI, AC-2). Replies come from the
 * committed TEST_MOCK fixtures memory_reuse_save / memory_reuse_load on the
 * real API and AI worker; no provider inference.
 *
 * What this proves: a CLI turn whose reply carries a memory write ends with the
 * core having stored the encrypted Memory (`memoryWrites[].status` applied, the
 * Memory listed with its title); a later chat that needs the ask-first Memory
 * gets a load request the CLI approves with --auto-approve-memories, and the
 * continued answer uses it, readable again through `chats show`; the human
 * `chats show` reads the assistant's write and the shared Memories as one line
 * each, never as raw event JSON or a placeholder mapping; Undo (which reads the
 * chat's assistant-write history notice) removes the Memory.
 * Not proven here: model choice of what to save (real-inference proof in
 * scripts/memory_reuse_web_real_test.py and scripts/jobs_focus_real_test.py).
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { parseJson, pickString } = require('./helpers/cli-native-fixtures');

const { email, password, otpKey } = getTestAccount();
const TITLE = 'Career profile';

type MemoryWrite = { action?: string; status?: string; title?: string; entryId?: string; undoAvailable?: boolean };

/** Listed Memory rows titled TITLE. */
function careerRows(listing: any): any[] {
	return (Array.isArray(listing) ? listing : []).filter((row: any) => row?.data?.title === TITLE);
}

test.describe('CLI native: assistant Memory writes', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=app-memories.lifecycle.encrypted-crud,app-memories.conversation.explicit-approval,app-memories.surface.semantic-parity,app-memories.privacy.anonymized-on-send
	test('a saved Memory is stored by the CLI, reused after approval in a new chat and undone', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.setTimeout(900_000);
		expect(process.env.E2E_USE_MOCKS, 'Committed fixture replies only; never paid inference').toBeTruthy();
		process.env.OPENMATES_TEST_SEND_PHASE_DIAGNOSTIC = '1';
		const diff = await setupDifferential(page, testInfo, 'memory-write');
		const chats: string[] = [];
		const run = async (args: string[], timeoutMs?: number) => {
			const result = await diff.native(args, timeoutMs);
			if (result.code !== 0 && args[0] === 'chats' && args[1] === 'new') {
				// An admitted turn that failed later still owns a chat (and maybe a
				// saved Memory); record it so the cleanup below can undo it.
				const failedChat = String(result.stdout).match(/"chat_id":"([0-9a-f-]{36})"/)?.[1];
				if (failedChat && !chats.includes(failedChat)) chats.push(failedChat);
			}
			expect(result.code, `${args.join(' ')}\nstderr: ${result.stderr}\nstdout: ${String(result.stdout).slice(-1500)}`).toBe(0);
			return parseJson(result);
		};
		const marked = (text: string, fixture: string) => {
			const value = withMockMarker(text, fixture, 'fast');
			expect(value).toContain('<<<TEST_MOCK:');
			return value;
		};
		try {
			// A leftover from an aborted run would make the load request ambiguous.
			expect(careerRows(await run(['settings', 'memories', 'list', '--json'])), 'leftover Career profile Memory').toHaveLength(0);

			// Chat 1: the reply carries a memory write; the core stores it.
			const first = await run(['chats', 'new', marked('Please remember my career profile for later.', 'memory_reuse_save'), '--personal', '--json'], 300_000);
			const firstId = pickString(first, ['chatId', 'chat_id']);
			expect(firstId).toMatch(/^[0-9a-f-]{36}$/);
			if (!chats.includes(firstId)) chats.push(firstId);
			const writes: MemoryWrite[] = first.memoryWrites ?? [];
			expect(writes, JSON.stringify(writes)).toHaveLength(1);
			expect(writes[0]).toMatchObject({ action: 'create', status: 'applied', title: TITLE, undoAvailable: true });
			const listed = careerRows(await run(['settings', 'memories', 'list', '--json']));
			expect(listed).toHaveLength(1);
			expect(JSON.stringify(listed[0].data)).toContain('Example Retail GmbH');

			// Chat 2: the ask-first Memory is requested, approved and used.
			const second = await run(['chats', 'new', marked('Which employer should I mention in my cover letter?', 'memory_reuse_load'), '--personal', '--auto-approve-memories', '--json'], 300_000);
			const secondId = pickString(second, ['chatId', 'chat_id']);
			expect(secondId).toMatch(/^[0-9a-f-]{36}$/);
			if (!chats.includes(secondId)) chats.push(secondId);
			expect(second.status).toBe('completed');
			expect(JSON.stringify(second)).toContain('Example Retail GmbH');
			// The persisted answer is readable again after the continuation.
			const shown = await run(['chats', 'show', secondId, '--personal', '--json'], 120_000);
			expect(JSON.stringify(shown)).toContain('Example Retail GmbH');
			// The human view reads system events as lines: no raw event JSON and
			// never the placeholder mapping of the shared Memory.
			const humanSecond = await diff.native(['chats', 'show', secondId, '--personal'], 120_000);
			expect(humanSecond.code, String(humanSecond.stderr)).toBe(0);
			const secondText = String(humanSecond.stdout);
			expect(secondText).toContain('Memories shared with the assistant');
			for (const raw of ['app_settings_memories_', 'pii_mappings', '"placeholder"', '"original"']) {
				expect(secondText, `human chats show prints ${raw}`).not.toContain(raw);
			}
			const humanFirst = await diff.native(['chats', 'show', firstId, '--personal'], 120_000);
			expect(humanFirst.code, String(humanFirst.stderr)).toBe(0);
			expect(String(humanFirst.stdout)).toContain(`Memory created by the assistant: ${TITLE}`);
			expect(String(humanFirst.stdout)).not.toContain('"context_entry"');

			// Undo reads the chat's assistant-write notice and removes the Memory.
			const undone = await run(['settings', 'memories', 'undo', '--chat', firstId, '--json']);
			expect(undone).toMatchObject({ undone: true, title: TITLE });
			expect(careerRows(await run(['settings', 'memories', 'list', '--json']))).toHaveLength(0);
		} finally {
			// Best effort: a failed assertion after the save must not leave the Memory
			// behind (reruns would hit the leftover guard). Exits non-zero when
			// nothing is left to undo.
			if (chats[0]) await diff.native(['settings', 'memories', 'undo', '--chat', chats[0], '--json']);
			for (const chatId of chats) await diff.native(['chats', 'delete', chatId, '--yes']);
			await finishDifferential(diff);
		}
	});
});
