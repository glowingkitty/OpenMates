/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Draft-only chats must remain discoverable after their Redis entries expire. */
const { test, expect } = require('./helpers/cookie-audit');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createWorkflowCliHome,
	loginWorkflowCliViaPair,
	removeWorkflowCliHome,
	runWorkflowCliJson,
	workflowApiUrl
} = require('./helpers/workflow-cli-e2e-helpers');

const root = path.resolve(__dirname, '../../../..');
const composeFile = path.join(root, 'test-results/ci-private/compose.json');
const { email, password, otpKey } = getTestAccount(1);

/** Persist ciphertext and evict only this test's draft keys in the disposable stack. */
function persistAndEvictDrafts(userId: string, drafts: any[]): void {
	expect(fs.existsSync(composeFile)).toBe(true);
	const program = `
import asyncio, hashlib, json, logging, os, sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED') == '1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService

async def main():
    payload = json.load(sys.stdin)
    user_id = payload['userId']
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    cache = CacheService()
    directus = DirectusService(cache_service=cache)
    try:
        for draft in payload['drafts']:
            chat_id = draft['chatId']
            persisted = await directus.chat.get_user_draft_from_directus(owner_hash, chat_id)
            if not persisted:
                persisted = await directus.chat.create_user_draft_in_directus({
                    'chat_id': chat_id, 'hashed_user_id': owner_hash,
                    'encrypted_content': draft['encryptedDraftMd'], 'version': draft['draftV'],
                })
            assert persisted and persisted['encrypted_content'] == draft['encryptedDraftMd']
            assert not await directus.chat.get_chat_metadata(chat_id), 'Fixture must be draft-only'
            redis = await cache.client
            await redis.delete(cache._get_user_chat_draft_key(user_id, chat_id),
                               cache._get_chat_versions_key(user_id, chat_id))
            await cache.remove_chat_from_ids_versions(user_id, chat_id)
            assert await cache.get_user_draft_from_cache(user_id, chat_id) is None
        print('persisted draft ciphertext retained; cache entries evicted')
    finally:
        await directus.close()
        await cache.close()

asyncio.run(main())
`;
	const output = execFileSync('docker', [
		'compose', '-f', composeFile, 'exec', '-T', '-e', 'OPENMATES_CI_ISOLATED=1',
		'api', 'python', '-c', program
	], { cwd: root, input: JSON.stringify({ userId, drafts }), encoding: 'utf8', timeout: 60_000 });
	expect(output.trim()).toBe('persisted draft ciphertext retained; cache entries evicted');
}

// contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted,drafts.draft-only.lifecycle,drafts.navigation.includes-draft-only
test('CLI and fresh web sync discover persisted draft-only chats after cache eviction', async ({ page }: { page: any }) => {
	test.setTimeout(240_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const cliHome = createWorkflowCliHome('persisted-drafts');
	const drafts: any[] = [];
	const cleanupIds = new Set<string>();
	let webContext: any;
	let webPage = page;
	try {
		await loginWorkflowCliViaPair(page, apiUrl, cliHome, 'PERSISTED_DRAFT_DISCOVERY');
		const user = await runWorkflowCliJson(apiUrl, cliHome, ['whoami'], 'paired account');
		// Close the app's socket before creation so web cannot receive local copies.
		await page.goto('about:blank');
		await page.context().setOffline(true);
		for (const text of ['Berlin', 'Keep this unrelated draft']) {
			const draft = await runWorkflowCliJson(apiUrl, cliHome, ['drafts', 'create', text], 'create draft');
			expect(draft.markdown).toBe(text);
			expect(draft.encryptedDraftMd).not.toContain(text);
			drafts.push(draft);
			cleanupIds.add(draft.chatId);
		}

		persistAndEvictDrafts(user.id, drafts);
		fs.rmSync(path.join(cliHome, '.openmates', 'sync_cache.json'), { force: true });
		const listed = await runWorkflowCliJson(apiUrl, cliHome, ['drafts', 'list', '--refresh'], 'cold CLI discovery');
		for (const draft of drafts) {
			expect(listed.drafts.find((item: any) => item.chatId === draft.chatId)?.markdown).toBe(draft.markdown);
		}

		// Evict again so web also proves database discovery without CLI warming it.
		persistAndEvictDrafts(user.id, drafts);
		// A new browser context starts with empty IndexedDB and localStorage.
		webContext = await page.context().browser().newContext();
		webPage = await webContext.newPage();
		await loginToTestAccount(webPage, console.log, undefined, { credentials: { email, password, otpKey } });
		await waitForChatReady(webPage, console.log);
		const toggle = webPage.getByTestId('sidebar-toggle');
		if (await toggle.getAttribute('aria-expanded') !== 'true') {
			await toggle.click();
		}
		await expect(toggle).toHaveAttribute('aria-expanded', 'true');
		const chatItem = (id: string) => webPage.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${id}"]`);
		for (const draft of drafts) {
			await expect(chatItem(draft.chatId)).toContainText(draft.markdown, { timeout: 30_000 });
		}

		await runWorkflowCliJson(apiUrl, cliHome, ['drafts', 'clear', drafts[0].chatId], 'selective draft cleanup');
		cleanupIds.delete(drafts[0].chatId);
		const after = await runWorkflowCliJson(apiUrl, cliHome, ['drafts', 'list', '--refresh'], 'drafts after deletion');
		expect(after.drafts.some((draft: any) => draft.chatId === drafts[0].chatId)).toBe(false);
		expect(after.drafts.find((draft: any) => draft.chatId === drafts[1].chatId)?.markdown).toBe(drafts[1].markdown);
		await expect(chatItem(drafts[0].chatId)).toHaveCount(0, { timeout: 30_000 });
		await expect(chatItem(drafts[1].chatId)).toContainText(drafts[1].markdown);
	} catch (error) {
		if (webContext) {
			await test.info().attach('fresh-web-state', {
				body: await webPage.screenshot(), contentType: 'image/png'
			}).catch(() => undefined);
		}
		throw error;
	} finally {
		await page.context().setOffline(false).catch(() => undefined);
		for (const chatId of cleanupIds) {
			await runWorkflowCliJson(apiUrl, cliHome, ['drafts', 'clear', chatId], 'cleanup draft').catch(() => undefined);
		}
		await webContext?.close().catch(() => undefined);
		removeWorkflowCliHome(cliHome);
	}
});
