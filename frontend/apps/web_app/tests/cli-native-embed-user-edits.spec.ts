/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (CLI text/JSON contract; native login is recorded in a real terminal)
/**
 * Native Rust CLI: user-made embed versions through the shared core, real
 * stack, no AI inference and no image provider.
 * Assertions: embed-user-edits.edit.next-version, embed-user-edits.restore.creates-version,
 * embed-user-edits.event.chat-notice, embed-user-edits.event.collapse,
 * embed-user-edits.event.project-edit-reaches-chat.
 *
 * What this proves: a Document embed with a user-made v2 (committed by the
 * fixture without writing its chat event) shows that event as one quiet line
 * after `chats show` (the open reconcile writes it); `embeds restore` saves v1
 * as a new v3 and writes its event; both events fold into one line; Enhance refuses a non-image
 * without charging and the CLI refuses an API key for these commands.
 * Not proven here: a real Enhance run. It needs a real image provider, which
 * isolated CI lacks (same classification as cli-images.spec.ts).
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { parseJson } = require('./helpers/cli-native-fixtures');
const { seedUserEditedDocument } = require('./helpers/user-edited-document-fixture');

const { email, password, otpKey } = getTestAccount();

test.describe('CLI native: embed user edits', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=embed-user-edits.edit.next-version,embed-user-edits.restore.creates-version,embed-user-edits.event.chat-notice,embed-user-edits.event.collapse,embed-user-edits.event.project-edit-reaches-chat
	test('restore makes a new version and each edit shows as one quiet chat line', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.setTimeout(300_000);
		const diff = await setupDifferential(page, testInfo, 'embed-user-edits');
		try {
			const seed = seedUserEditedDocument(diff.apiUrl, diff.npmHome);
			expect(seed.embedId).not.toBe('');

			// Opening the chat writes the pending v2 event, shown as one line.
			const first = await diff.native(['chats', 'show', seed.chatId]);
			expect(first.code, first.stderr).toBe(0);
			expect(first.stdout).toContain('· Document updated · version 2 (edited)');
			expect(first.stdout).not.toContain('"embed_updated"');

			const restored = await diff.native(['embeds', 'restore', seed.embedId, '--version', '1', '--chat', seed.chatId, '--json']);
			expect(restored.code, restored.stderr).toBe(0);
			const receipt = parseJson(restored);
			expect(receipt).toMatchObject({ embed_id: seed.embedId, action: 'restore', version: 3, restored_from: 1, revision_origin: 'user' });
			expect(receipt.chat_event.state).toBe('written');

			const second = await diff.native(['chats', 'show', seed.chatId]);
			expect(second.code, second.stderr).toBe(0);
			expect(second.stdout).toContain('· Document updated, 2 changes · version 3 (restored version 1)');
			expect(second.stdout.match(/Document updated/g)?.length).toBe(1);

			const stale = await diff.native(['embeds', 'restore', seed.embedId, '--version', '3', '--chat', seed.chatId]);
			expect(stale.code).not.toBe(0);
			expect(stale.stdout + stale.stderr).toContain('Choose a version below the current version');

			const notImage = await diff.native(['embeds', 'enhance', seed.embedId, '--chat', seed.chatId]);
			expect(notImage.code).not.toBe(0);
			expect(notImage.stdout + notImage.stderr).toContain('not an image');

			const withKey = await diff.native(['embeds', 'restore', seed.embedId, '--version', '1', '--api-key', 'sk-api-synthetic.synthetic']);
			expect(withKey.code).not.toBe(0);
			expect(withKey.stdout + withKey.stderr).toContain('signed-in Personal session');
		} finally {
			await finishDifferential(diff);
		}
	});
});
