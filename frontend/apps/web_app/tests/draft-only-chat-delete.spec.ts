/* eslint-disable @typescript-eslint/no-require-imports -- Existing CLI E2E helpers expose CommonJS exports. */
// proof-video: not_required reason=non_visual_setup (CLI and server-state assertions; no UI changes)
export {};

/**
 * Deleting a draft-only chat must also delete its encrypted draft.
 *
 * Regression: the server's delete_chat path for a chat that only exists as a
 * draft (no chat row) queued no persistence task, so the persisted draft row
 * and its cache entry survived and the chat came back as a draft on the next
 * sync. A CLI with no local sync cache cannot recognise the shell and sends
 * delete_chat instead of clearing the draft, so it exercises that server path.
 */
const { test, expect } = require('./helpers/cookie-audit');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createWorkflowCliHome,
	loginWorkflowCliViaPair,
	removeWorkflowCliHome,
	runWorkflowCli,
	runWorkflowCliJson,
	workflowApiUrl
} = require('./helpers/workflow-cli-e2e-helpers');

const root = path.resolve(__dirname, '../../../..');
const composeFile = path.join(root, 'test-results/ci-private/compose.json');
const { email, password, otpKey } = getTestAccount(1);

/** Run one Python program against this test's disposable stack only. */
function inStack(program: string, input: unknown): string {
	expect(fs.existsSync(composeFile)).toBe(true);
	return execFileSync('docker', [
		'compose', '-f', composeFile, 'exec', '-T', '-e', 'OPENMATES_CI_ISOLATED=1',
		'api', 'python', '-c', program
	], { cwd: root, input: JSON.stringify(input), encoding: 'utf8', timeout: 60_000 }).trim();
}

const PROGRAM_PRELUDE = `
import asyncio, hashlib, json, logging, os, sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED') == '1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
`;

/** Persist the draft ciphertext as a Directus draft row and confirm no chat row exists. */
function persistDraftRow(userId: string, draft: any): void {
	const output = inStack(`${PROGRAM_PRELUDE}
async def main():
    payload = json.load(sys.stdin)
    user_id, draft = payload['userId'], payload['draft']
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    cache = CacheService()
    directus = DirectusService(cache_service=cache)
    try:
        persisted = await directus.chat.get_user_draft_from_directus(owner_hash, draft['chatId'])
        if not persisted:
            persisted = await directus.chat.create_user_draft_in_directus({
                'chat_id': draft['chatId'], 'hashed_user_id': owner_hash,
                'encrypted_content': draft['encryptedDraftMd'], 'version': draft['draftV'],
            })
        assert persisted and persisted['encrypted_content'] == draft['encryptedDraftMd']
        assert not await directus.chat.get_chat_metadata(draft['chatId']), 'Fixture must be draft-only'
        print('draft row persisted')
    finally:
        await directus.close()
        await cache.close()

asyncio.run(main())
`, { userId, draft });
	expect(output).toBe('draft row persisted');
}

/** Report what the server still holds for this user's draft of the chat. */
function draftResidue(userId: string, chatId: string): { rows: number; liveCachedDraft: boolean } {
	return JSON.parse(inStack(`${PROGRAM_PRELUDE}
async def main():
    payload = json.load(sys.stdin)
    user_id, chat_id = payload['userId'], payload['chatId']
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    cache = CacheService()
    directus = DirectusService(cache_service=cache)
    try:
        rows = await directus.get_items('drafts', params={
            'filter[hashed_user_id][_eq]': owner_hash, 'filter[chat_id][_eq]': chat_id,
            'fields': 'id', 'limit': -1,
        }, no_cache=True, admin_required=True, raise_on_error=True)
        cached = await cache.get_user_draft_from_cache(user_id, chat_id)
        tombstoned = await cache.is_user_draft_tombstoned(user_id, chat_id)
        live = bool(cached and cached[0]) and not tombstoned
        print(json.dumps({'rows': len(rows or []), 'liveCachedDraft': live}))
    finally:
        await directus.close()
        await cache.close()

asyncio.run(main())
`, { userId, chatId }));
}

/** Count the server's draft-shell deletion log lines (the logger redacts chat ids). */
function draftShellDeletionLogCount(): number {
	const logs = execFileSync('docker', ['compose', '-f', composeFile, 'logs', '--no-color', 'api'],
		{ cwd: root, encoding: 'utf8', timeout: 60_000, maxBuffer: 64 * 1024 * 1024 });
	return logs.split('\n').filter((line: string) =>
		line.includes('Deleted 1 persisted draft row(s) of draft-only chat')).length;
}

// contract-test: direct surface=rest_api assertions=drafts.draft-only.lifecycle
// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
test('deleting a draft-only chat removes its persisted encrypted draft', async ({ page }: { page: any }) => {
	test.setTimeout(180_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const cliHome = createWorkflowCliHome('draft-only-delete');
	let chatId: string | undefined;
	let deleted = false;
	try {
		await loginWorkflowCliViaPair(page, apiUrl, cliHome, 'DRAFT_ONLY_CHAT_DELETE');
		const user = await runWorkflowCliJson(apiUrl, cliHome, ['whoami'], 'paired account');
		const draft = await runWorkflowCliJson(apiUrl, cliHome,
			['drafts', 'create', 'Draft that must not survive deletion'], 'create draft');
		chatId = draft.chatId;
		expect(chatId).toMatch(/^[0-9a-f-]{36}$/i);
		persistDraftRow(user.id, draft);
		expect(draftResidue(user.id, chatId!)).toEqual({ rows: 1, liveCachedDraft: true });

		// Without its sync cache the CLI cannot tell the chat is a draft shell,
		// so it sends delete_chat (the server path under test).
		fs.rmSync(path.join(cliHome, '.openmates', 'sync_cache.json'), { force: true });
		const deletionLogsBefore = draftShellDeletionLogCount();
		// `chats delete` prints a text summary even with --json.
		const deletion = await runWorkflowCli(apiUrl, cliHome, ['chats', 'delete', chatId!, '--yes'], 60_000);
		expect(deletion.code, `delete failed:\n${deletion.stdout}\n${deletion.stderr}`).toBe(0);
		expect(deletion.stdout).toMatch(/^1\/1 chat\(s\) deleted\.$/m);
		deleted = true;

		const residue = draftResidue(user.id, chatId!);
		await test.info().attach('draft-only-delete-residue', {
			body: JSON.stringify({ chatId, ...residue }), contentType: 'application/json'
		});
		expect(residue, 'no persisted draft row or live cached draft may survive').toEqual({ rows: 0, liveCachedDraft: false });
		expect(draftShellDeletionLogCount(), 'the delete_chat draft-shell branch removed the row')
			.toBe(deletionLogsBefore + 1);

		const listed = await runWorkflowCliJson(apiUrl, cliHome, ['drafts', 'list', '--refresh'], 'drafts after delete');
		expect(listed.drafts.some((item: any) => item.chatId === chatId)).toBe(false);
	} finally {
		if (chatId && !deleted) {
			await runWorkflowCliJson(apiUrl, cliHome, ['drafts', 'clear', chatId], 'cleanup draft').catch(() => undefined);
		}
		removeWorkflowCliHome(cliHome);
	}
});
