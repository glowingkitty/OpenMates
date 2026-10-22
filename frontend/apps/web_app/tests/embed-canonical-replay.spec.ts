/* eslint-disable @typescript-eslint/no-require-imports */
/** Real browser/API replay of already acknowledged encrypted heads; no inference. */
export {};
const { test, expect, allowConsoleErrorPatterns } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { observeRecoveryFrames, focusRecoveryPage } = require('./storage-recovery-fixtures');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

function seedCanonicalFixture(fixture: Record<string, any>, acknowledged = true): void {
	const root = path.resolve(__dirname, '../../../..');
	const compose = path.join(root, 'test-results/ci-private/compose.json');
	expect(process.env.GITHUB_ACTIONS).toBe('true');
	expect(fs.existsSync(compose), 'Requires the disposable isolated CI stack').toBe(true);
	const program = `
import asyncio,hashlib,json,logging,os,sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED')=='1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.tasks.persistence_tasks import _chat_list_cache_data_from_metadata,_chat_versions_from_metadata
async def main():
    d=json.load(sys.stdin); cache=CacheService(); ds=DirectusService(cache_service=cache)
    digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
    owner=digest(d['ownerId']); chat_hash=digest(d['chatId'])
    assert d['chat']['hashed_user_id']==owner and d['message']['hashed_user_id']==owner
    assert len(d['keys'])==4 and len(d['outputs'])==2
    try:
        created,duplicate=await ds.chat.create_chat_in_directus(d['chat'])
        assert created and not duplicate
        assert await ds.chat.create_message_in_directus(d['message'])
        for embed in (d['parent'],d['child']):
            assert embed['hashed_user_id']==owner and embed['hashed_chat_id']==chat_hash
            created,_=await ds.create_item('embeds',embed,admin_required=True)
            assert created
        assert d['child']['parent_embed_id']==d['parentId']
        for key in d['keys']:
            assert key['hashed_user_id']==owner and key['hashed_embed_id']==digest(d['parentId'])
            assert key.get('hashed_chat_id')==(chat_hash if key['key_type']=='chat' else None)
            created,_=await ds.create_item('embed_keys',key,admin_required=True)
            assert created
        for output in (d['outputs'] if d['acknowledged'] else []):
            assert output['hashed_user_id']==owner and output['target_chat_id']==d['chatId']
            assert output['subject_id'] in (d['parentId'],d['childId']) and output['state']=='ACKNOWLEDGED'
            created,_=await ds.create_item('chat_recovery_outputs',output,admin_required=True)
            assert created
        assert await cache.add_chat_to_ids_versions(d['ownerId'],d['chatId'],d['chat']['last_edited_overall_timestamp'])
        assert await cache.set_chat_list_item_data(d['ownerId'],d['chatId'],_chat_list_cache_data_from_metadata(d['chat']))
        assert await cache.set_chat_versions(d['ownerId'],d['chatId'],_chat_versions_from_metadata(d['chat']))
        print('canonical replay fixture seeded')
    finally:
        await ds.close(); await cache.close()
asyncio.run(main())
`;
	const output = execFileSync('docker', ['compose', '-f', compose, 'exec', '-T', '-e', 'OPENMATES_CI_ISOLATED=1',
		'api', 'python', '-c', program], { cwd: root, input: JSON.stringify({ ...fixture, acknowledged }), encoding: 'utf8', timeout: 60_000 });
	expect(output.trim()).toBe('canonical replay fixture seeded');
}

// contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted,chats.sync.key-gated-recovery
test('acknowledged parent and child replays preserve ciphertext without authorization errors after reload', async ({ page }: { page: any }) => {
	test.setTimeout(240_000);
	const { email, password, otpKey } = getTestAccount();
	skipWithoutCredentials(test, email, password, otpKey);
	const log = createSignupLogger('embed-canonical-replay');
	const frames = observeRecoveryFrames(page, true);
	await loginToTestAccount(page, log, createStepScreenshotter(log));
	await focusRecoveryPage(page);
	await expect.poll(() => page.evaluate(() => typeof (window as any).__openmatesE2ESeedCanonicalEmbedReplay)).toBe('function');
	const fixture = await page.evaluate(() => (window as any).__openmatesE2ESeedCanonicalEmbedReplay());
	seedCanonicalFixture(fixture);
	await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(fixture.chatId)}`));
	await focusRecoveryPage(page);
	await expect(page.getByTestId('message-assistant').first()).toBeVisible();
	const apiOrigin = process.env.PLAYWRIGHT_TEST_API_URL;
	if (!apiOrigin) throw new Error('The isolated API origin is required');
	const read = (embedId: string, authenticated = true) => page.evaluate(async ({ apiOrigin, chatId, embedId, authenticated }) => {
		const response = await fetch(`${apiOrigin}/v1/embeds/chats/${encodeURIComponent(chatId)}/embeds/${encodeURIComponent(embedId)}`, {
			credentials: authenticated ? 'include' : 'omit', headers: { 'x-openmates-client-capabilities': 'agentic-storage-v2' },
		});
		if (!response.ok) return { status: response.status };
		const data = await response.json();
		return { status: response.status, embed: data.embed, keys: data.embed_keys };
	}, { apiOrigin: apiOrigin.replace(/\/$/, ''), chatId: fixture.chatId, embedId, authenticated });
	const rootProof = await page.evaluate(async ({ apiOrigin, chatId, parentId }) => {
		const response = await fetch(`${apiOrigin}/v1/embeds/chats/${chatId}/references/availability`, {
			method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ embed_ids: [parentId], required_recovery_versions: { [parentId]: 1 } }),
		});
		if (!response.ok) throw new Error(`Canonical ACK proof failed (${response.status})`);
		return (await response.json()).results[0];
	}, { apiOrigin: apiOrigin.replace(/\/$/, ''), chatId: fixture.chatId, parentId: fixture.parentId });
	expect(rootProof).toMatchObject({ embed_id: fixture.parentId, state: 'ready',
		recovery_ack: { state: 'ACKNOWLEDGED', version: 1, canonical_digest: fixture.outputs[0].canonical_digest } });
	const before = new Map<string, any>();
	for (const embedId of [fixture.parentId, fixture.childId]) {
		const canonical = await read(embedId);
		expect(canonical.status).toBe(200);
		expect(canonical.keys).toHaveLength(4);
		expect(canonical.embed.encrypted_content).toBe(fixture.parent.encrypted_content);
		before.set(embedId, canonical);
	}
	expect([401, 403]).toContain((await read(fixture.childId, false)).status);
	const replay = (embedId: string, changeContent = false) => page.evaluate(async ({ chatId, embedId, changeContent }) => {
		return (window as any).__openmatesE2EReplayCanonicalEmbedWrite({ chatId, embedId, changeContent });
	}, { chatId: fixture.chatId, embedId, changeContent });
	for (const embedId of [fixture.parentId, fixture.childId]) {
		expect(await replay(embedId)).toEqual({ pending: false, connected: true });
		expect(await read(embedId)).toEqual(before.get(embedId));
	}
	const beforeReload = frames.length;
	await page.reload();
	await focusRecoveryPage(page);
	await expect.poll(() => frames.slice(beforeReload).some((frame: any) => frame.type === 'native_client_lifecycle_ack'
		&& frame.payload.is_foreground === true), { timeout: 60_000 }).toBe(true);
	for (const embedId of [fixture.parentId, fixture.childId]) {
		expect(await replay(embedId)).toEqual({ pending: false, connected: true });
		expect(await read(embedId)).toEqual(before.get(embedId));
	}
	allowConsoleErrorPatterns([/\[EmbedSenders\] Canonical embed .* is pending retry: Error: Canonical embed content or type differs; use a versioned edit\./]);
	expect(await replay(fixture.parentId, true)).toEqual({ pending: true, connected: true });
	expect(await read(fixture.parentId)).toEqual(before.get(fixture.parentId));
	expect(frames.filter((frame: any) => frame.direction === 'sent' && frame.type === 'store_embed')).toHaveLength(0);
	expect(frames.filter((frame: any) => frame.type === 'error' && frame.payload.code === 'embed_write_denied')).toHaveLength(0);
	// A finished legacy head without a recovery ACK still accepts its legitimate
	// preview/content update; immutable-replay protection must preserve that path.
	const mutable = await page.evaluate(() => (window as any).__openmatesE2ESeedCanonicalEmbedReplay());
	seedCanonicalFixture(mutable, false);
	const changed = await page.evaluate(({ chatId, embedId }) =>
		(window as any).__openmatesE2EReplayCanonicalEmbedWrite({ chatId, embedId, changeContent: true }),
	{ chatId: mutable.chatId, embedId: mutable.parentId });
	expect(changed).toEqual({ pending: false, connected: true });
	expect(frames.filter((frame: any) => frame.direction === 'sent' && frame.type === 'store_embed'
		&& frame.payload.embed_id === mutable.parentId)).toHaveLength(1);
	expect(frames.filter((frame: any) => frame.type === 'error' && frame.payload.code === 'embed_write_denied')).toHaveLength(0);
});
