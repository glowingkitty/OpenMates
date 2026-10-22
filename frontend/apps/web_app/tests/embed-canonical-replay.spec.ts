/* eslint-disable @typescript-eslint/no-require-imports */
/** Real provider-free producer → sealed recovery ACK → reconnect lifecycle. */
export {};
const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { observeRecoveryFrames, focusRecoveryPage } = require('./storage-recovery-fixtures');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

/** Open typed recovery only inside this disposable, provider-free marker stack.
 * The fixture uses the same cutover transactions/controller as the CI harness;
 * its separately pinned harness does not register this newer lifecycle spec. */
function prepareCanonicalRecoveryEpoch(): Record<string, unknown> {
	const root = path.resolve(__dirname, '../../../..');
	const compose = path.join(root, 'test-results/ci-private/compose.json');
	if (process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI !== 'true' || process.env.OPENMATES_CI_ISOLATED !== '1'
		|| process.env.PLAYWRIGHT_TEST_API_URL !== 'http://localhost:8000'
		|| process.env.PLAYWRIGHT_TEST_BASE_URL !== 'http://localhost:5173' || !fs.existsSync(compose)) {
		throw new Error('Canonical recovery setup requires the exact GitHub-hosted isolated localhost fixture');
	}
	const profile = JSON.parse(fs.readFileSync(compose, 'utf8'));
	const services = profile.services ?? {};
	const api = services.api?.environment ?? {};
	const expected = { CI: 'true', OPENMATES_CI_ISOLATED: '1', OPENMATES_CI_AI_FIXTURES: '1',
		CMS_URL: 'http://cms:8055', VAULT_URL: 'http://vault:8200',
		SERVER_ENVIRONMENT: 'development', MOCK_EXTERNAL_APIS: 'true',
		OPENMATES_DEPLOYMENT_MODE: 'self_host', FRONTEND_URL: 'http://localhost:5173',
		E2E_TEST_DEV_ENABLED: 'false', E2E_TEST_PROD_ENABLED: 'false' };
	const permittedServices = new Set(['api', 'core-worker', 'cms', 'cms-setup', 'cms-database',
		'cache', 'vault', 'vault-init', 'fixture-init', 'runner-gateway', 'ai-worker']);
	if (Object.entries(expected).some(([key, value]) => api[key] !== value)
		|| profile.name !== 'openmates-ci' || profile.networks?.default?.internal !== true
		|| Object.keys(services).some((name) => !permittedServices.has(name))
		|| api.OPENMATES_STORAGE_CAPACITY_FIXTURES != null || api.S3_ENDPOINT_URL != null
		|| services['ai-worker']?.environment?.CELERY_QUEUES !== 'app_ai,app_ai_routing'
		|| services['ai-worker']?.environment?.OPENMATES_CI_AI_FIXTURES !== '1'
		|| services['runner-gateway']?.environment?.OPENMATES_CI_PUBLIC_PROVIDER_PROXY != null
		|| Object.values(services).some((service: any) => ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']
			.some((key) => key in (service.environment ?? {})))) {
		throw new Error('Canonical recovery setup requires the internal, provider-free isolated marker profile');
	}
	const program = `
import asyncio,json,logging,os
logging.disable(logging.CRITICAL)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
from backend.core.api.app.services.chat_recovery_cutover import ChatRecoveryCutoverController
async def main():
    expected={'CI':'true','OPENMATES_CI_ISOLATED':'1','OPENMATES_CI_AI_FIXTURES':'1',
        'OPENMATES_CI_CANONICAL_REPLAY_EPOCH_FIXTURE':'1',
        'CMS_URL':'http://cms:8055','VAULT_URL':'http://vault:8200','MOCK_EXTERNAL_APIS':'true',
        'SERVER_ENVIRONMENT':'development','OPENMATES_DEPLOYMENT_MODE':'self_host',
        'FRONTEND_URL':'http://localhost:5173','E2E_TEST_DEV_ENABLED':'false','E2E_TEST_PROD_ENABLED':'false'}
    if any(os.getenv(key)!=value for key,value in expected.items()) or any(
        os.getenv(key) is not None for key in ('S3_ENDPOINT_URL','OPENMATES_STORAGE_CAPACITY_FIXTURES',
            'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')):
        raise RuntimeError('Canonical replay epoch requires the disposable internal marker fixture')
    cache=CacheService(); directus=DirectusService(cache_service=cache)
    try:
        service=ChatRecoveryService(directus)
        state=await service.execute('get_cutover_state',{'protocol_version':1})
        initial=state.get('protocol_epoch')
        if type(initial) is not int or initial not in (0,1) or type(state.get('legacy_in_flight')) is not int or state['legacy_in_flight']!=0 or state.get('sends_paused') is not False:
            raise RuntimeError('Canonical replay cutover requires an open idle epoch zero or one')
        if initial==0:
            paused=False
            try:
                pause=await service.execute('set_sends_paused',{'protocol_version':1,'sends_paused':True})
                paused=True
                if pause!={'protocol_epoch':0,'sends_paused':True,'legacy_in_flight':0}:
                    raise RuntimeError('Canonical replay pause was not acknowledged')
                activated=await service.execute('activate_protocol_epoch',{'protocol_version':1,'target_epoch':1})
                if activated!={'protocol_epoch':1,'sends_paused':True,'legacy_in_flight':0,'activated':True}:
                    raise RuntimeError('Canonical replay epoch one was not activated')
            finally:
                if paused:
                    resumed=await service.execute('set_sends_paused',{'protocol_version':1,'sends_paused':False})
                    if resumed!={'protocol_epoch':1,'sends_paused':False,'legacy_in_flight':0}:
                        raise RuntimeError('Canonical replay sends were not safely resumed')
        # Retry/central activation may already have opened this same guarded
        # disposable profile. Never pause or mutate an existing idle epoch one.
        controller=ChatRecoveryCutoverController(cache,directus)
        authoritative=await controller.get_state(authoritative=True)
        cached=await controller.get_state()
        final={'protocol_epoch':1,'sends_paused':False,'legacy_in_flight':0}
        if authoritative!=final or cached!=final:
            raise RuntimeError('Canonical replay epoch one is not authoritatively open')
        print(json.dumps({**final,'initial_epoch':initial,'activated':initial==0,'profile':'isolated-marker-provider-free'}))
    finally:
        await directus.close(); await cache.close()
asyncio.run(main())
`;
	const output = execFileSync('docker', ['compose', '-f', compose, 'exec', '-T',
		'-e', 'OPENMATES_CI_CANONICAL_REPLAY_EPOCH_FIXTURE=1',
		'api', 'python', '-c', program], { cwd: root, encoding: 'utf8', timeout: 60_000 });
	return JSON.parse(output.trim());
}

/** Bounded structural receipt: never attach ciphertext, private text or raw IDs. */
function canonicalRecoveryFrameReceipt(frames: any[], outputs: any[]): Record<string, unknown>[] {
	const words = (value: unknown) => typeof value === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(value) ? value : null;
	const ordinal = (recordId: unknown) => outputs.findIndex((output) => output.record_id === recordId);
	return frames.filter((frame) => frame.type.startsWith('recovery_output')
		|| frame.type === 'native_client_lifecycle' || frame.type === 'native_client_lifecycle_ack' || frame.type === 'error')
		.slice(-80).map((frame) => ({ direction: frame.direction, type: words(frame.type),
			status: words(frame.payload.status), code: words(frame.payload.code),
			foreground: typeof frame.payload.is_foreground === 'boolean' ? frame.payload.is_foreground : null,
			target_record_ordinal: ordinal(frame.payload.record_id),
			state: ['ACKNOWLEDGED', 'PENDING'].includes(frame.payload.state) ? frame.payload.state : null,
			request_present: typeof frame.payload.request_id === 'string',
			outputs: Array.isArray(frame.payload.outputs) ? frame.payload.outputs.slice(0, 8).map((output: any) => ({
				target_record_ordinal: ordinal(output.record_id), kind: words(output.output_kind), version: output.output_version,
			})) : undefined,
		}));
}

/** Seed only opaque ownership/wrappers, then real sealed output envelopes.
 * Canonical heads and ACKs are always written through the browser protocol. */
function seedCanonicalFixture(fixture: Record<string, any>, stage: 'ownership' | 'wrappers' | 'legacy' | 'sealed'): any[] {
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
from backend.shared.python_utils.chat_completion_recovery_job import build_sealed_recovery_output_data
async def main():
    d=json.load(sys.stdin); cache=CacheService(); ds=DirectusService(cache_service=cache)
    digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
    owner=digest(d['ownerId']); chat_hash=digest(d['chatId']); outputs=[]
    assert d['chat']['hashed_user_id']==owner and d['message']['hashed_user_id']==owner
    assert len(d['keys'])==4 and len(d['outputs'])==2
    try:
        if d['stage']=='ownership':
            created,duplicate=await ds.chat.create_chat_in_directus(d['chat'])
            assert created and not duplicate
            assert await ds.chat.create_message_in_directus(d['message'])
            assert await cache.add_chat_to_ids_versions(d['ownerId'],d['chatId'],d['chat']['last_edited_overall_timestamp'])
            assert await cache.set_chat_list_item_data(d['ownerId'],d['chatId'],_chat_list_cache_data_from_metadata(d['chat']))
            assert await cache.set_chat_versions(d['ownerId'],d['chatId'],_chat_versions_from_metadata(d['chat']))
        elif d['stage']=='wrappers':
            # The storage guard requires the real parent head before any key.
            for index,key in enumerate(d['keys']):
                assert key['hashed_user_id']==owner and key['hashed_embed_id']==digest(d['parentId'])
                assert key.get('hashed_chat_id')==(chat_hash if key['key_type']=='chat' else None)
                created,details=await ds.create_item('embed_keys',key,admin_required=True)
                if not created:
                    status=details.get('status_code') if isinstance(details,dict) else None
                    missing_parent='embed_key_parent_unavailable' in str(details)
                    raise AssertionError(f'fixture_wrapper_create_failed:index={index};status={status};parent_unavailable={missing_parent}')
        elif d['stage']=='legacy':
            # Recreate only historical version metadata after the actual sender
            # created this body. Current producers correctly normalize new v1.
            updated=await ds.embed.update_embed(d['parentId'], {'version_number':None})
            assert updated and updated['version_number'] is None
        else:
            for head,identity in zip((d['parent'],d['child']),d['outputs']):
                content={**d['outputContent'],'embed_id':head['embed_id']}
                if head.get('parent_embed_id'): content['parent_embed_id']=head['parent_embed_id']
                sealed=build_sealed_recovery_output_data(owner_id=d['ownerId'],owner_hash=owner,
                    root_chat_id=d['chatId'],target_chat_id=d['chatId'],turn_id=identity['turn_id'],
                    preflight_id=identity['preflight_id'],inference_task_id=identity['inference_task_id'],
                    recovery_public_key=d['recoveryPublicKey'],chat_key_version=1,subject_id=head['embed_id'],
                    output_kind='embed',output_version=1,content=content)
                payload=sealed['sealed_payload']; record_id=sealed['record_id']
                row={k:v for k,v in sealed.items() if k not in ('protocol_version','record_id')}
                row.update(id=record_id,root_hashed_team_id=None,message_role=None,
                    sealed_payload_digest=digest(payload),payload_storage='inline',payload_size_bytes=len(payload.encode()),
                    state='PENDING',created_at=identity['created_at'])
                created,_=await ds.create_item('chat_recovery_outputs',row,admin_required=True)
                assert created
                outputs.append({'record_id':record_id,'subject_id':head['embed_id']})
        print(json.dumps(outputs))
    finally:
        await ds.close(); await cache.close()
asyncio.run(main())
`;
	const output = execFileSync('docker', ['compose', '-f', compose, 'exec', '-T',
		'api', 'python', '-c', program], { cwd: root, input: JSON.stringify({ ...fixture, stage }), encoding: 'utf8', timeout: 60_000 });
	return JSON.parse(output.trim());
}

// contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted,chats.sync.key-gated-recovery
test('nullable web root survives producer, sealed ACK, preview, legacy queue reconnect and cold reload', async ({ page: producerPage, browser, baseURL }: { page: any; browser: any; baseURL: string }) => {
	let page = producerPage;
	test.setTimeout(300_000);
	const { email, password, otpKey } = getTestAccount();
	skipWithoutCredentials(test, email, password, otpKey);
	const log = createSignupLogger('embed-canonical-lifecycle');
	const frames = observeRecoveryFrames(page, true);
	// Retain transient error toasts across navigations, including auto-dismissed ones.
	const errorToasts: string[] = [];
	const conflictWarnings: string[] = [];
	const observeToasts = async (target: any) => {
		await target.exposeFunction('__canonicalErrorToast', (text: string) => errorToasts.push(text));
		await target.exposeFunction('__canonicalConflictWarning', (text: string) => conflictWarnings.push(text));
		await target.addInitScript(() => {
			const recordedWarnings = new WeakSet<Element>();
			const observer = new MutationObserver(() => {
				for (const element of document.querySelectorAll('[data-testid="notification"].notification-error')) {
					void (window as any).__canonicalErrorToast(element.textContent ?? '');
				}
				for (const element of document.querySelectorAll('[data-testid="notification"].notification-warning')) {
					const text = element.textContent ?? '';
					if (!recordedWarnings.has(element) && /saved result has a conflicting revision|chats\.embed_sync\.conflict/.test(text)) {
						recordedWarnings.add(element);
						void (window as any).__canonicalConflictWarning(text);
					}
				}
			});
			observer.observe(document, { childList: true, subtree: true, characterData: true });
		});
	};
	const epoch = prepareCanonicalRecoveryEpoch();
	await test.info().attach('canonical-recovery-epoch', { body: JSON.stringify(epoch), contentType: 'application/json' });
	await observeToasts(page);
	await loginToTestAccount(page, log, createStepScreenshotter(log));
	await focusRecoveryPage(page);
	await expect.poll(() => page.evaluate(() => typeof (window as any).__openmatesE2ESeedCanonicalEmbedReplay)).toBe('function');
	const fixture = await page.evaluate(() => (window as any).__openmatesE2ESeedCanonicalEmbedReplay({ legacyWeb: true }));
	seedCanonicalFixture(fixture, 'ownership');
	const apiOrigin = process.env.PLAYWRIGHT_TEST_API_URL;
	if (!apiOrigin) throw new Error('The isolated API origin is required');
	const read = (embedId: string, authenticated = true, chatId = fixture.chatId) => page.evaluate(async ({ apiOrigin, chatId, embedId, authenticated }) => {
		const response = await fetch(`${apiOrigin}/v1/embeds/chats/${encodeURIComponent(chatId)}/embeds/${encodeURIComponent(embedId)}`, {
			credentials: authenticated ? 'include' : 'omit', headers: { 'x-openmates-client-capabilities': 'agentic-storage-v2' },
		});
		if (!response.ok) return { status: response.status };
		const data = await response.json();
		return { status: response.status, embed: data.embed, keys: data.embed_keys.sort((a: any, b: any) => String(a.id).localeCompare(String(b.id))) };
	}, { apiOrigin: apiOrigin.replace(/\/$/, ''), chatId, embedId, authenticated });
	const availability = () => page.evaluate(async ({ apiOrigin, chatId, parentId }) => {
		const response = await fetch(`${apiOrigin}/v1/embeds/chats/${chatId}/references/availability`, {
			method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ embed_ids: [parentId], required_recovery_versions: { [parentId]: 1 } }),
		});
		if (!response.ok) throw new Error(`Canonical revision proof failed (${response.status})`);
		return (await response.json()).results[0];
	}, { apiOrigin: apiOrigin.replace(/\/$/, ''), chatId: fixture.chatId, parentId: fixture.parentId });
	const lifecycle = (action: string, extra: Record<string, unknown> = {}) => page.evaluate((input: any) =>
		(window as any).__openmatesE2ECanonicalLifecycle(input), { action, chatId: fixture.chatId, ...extra });
	const replay = (embedId: string, changeContent = false, queueOnly = false) => page.evaluate((input: any) =>
		(window as any).__openmatesE2EReplayCanonicalEmbedWrite(input), { chatId: fixture.chatId, embedId, changeContent, queueOnly });
	const reconnect = async () => {
		const offset = frames.length;
		await lifecycle('reconnect');
		await focusRecoveryPage(page);
		await expect.poll(() => frames.slice(offset).some((frame: any) => frame.type === 'native_client_lifecycle_ack'
			&& frame.payload.is_foreground === true), { timeout: 60_000 }).toBe(true);
	};

	// Initial ordinary producer writes against missing heads; the root intentionally
	// omits version_number, which the sender now normalizes to logical v1.
	// No head or ACK is inserted directly by the runner.
	expect((await availability()).state).toBe('missing');
	for (const [index, head] of [fixture.parent, fixture.child].entries()) {
		const result = await page.evaluate(({ chatId, head }: any) =>
			(window as any).__openmatesE2EInitialCanonicalEmbedWrite({ chatId, head }), { chatId: fixture.chatId, head });
		expect(result.status).toBe('persisted');
		// Storage requires an existing parent before wrappers. A readable parent
		// (including its wrappers) is then required for the ordinary child write.
		if (index === 0) seedCanonicalFixture(fixture, 'wrappers');
	}
	expect((await read(fixture.parentId)).embed.version_number).toBe(1);
	seedCanonicalFixture(fixture, 'legacy');
	const before = new Map<string, any>();
	for (const embedId of [fixture.parentId, fixture.childId]) {
		const canonical = await read(embedId);
		expect(canonical.status).toBe(200);
		expect(canonical.keys).toHaveLength(4);
		expect(canonical.embed.encrypted_content).toBe(fixture.parent.encrypted_content);
		before.set(embedId, canonical);
	}
	expect(before.get(fixture.parentId).embed.version_number).toBeNull();
	expect(before.get(fixture.childId).embed.version_number).toBe(1);
	expect((await availability()).canonical_revision).toMatchObject({ version: 1, write_state: 'mutable' });
	const outputs = seedCanonicalFixture(fixture, 'sealed');
	const recoveryOffset = frames.length;
	try {
		await reconnect();
		await expect.poll(() => frames.slice(recoveryOffset).some((frame: any) => frame.type === 'recovery_outputs_discovery_complete'
			&& frame.payload.status === 'completed'), { timeout: 30_000, message: 'Fresh foreground discovery must run under the active recovery epoch' }).toBe(true);
		for (const output of outputs) {
			await expect.poll(() => frames.some((frame: any) => frame.direction === 'received'
				&& frame.type === 'recovery_output_embed_acknowledged'
				&& frame.payload.record_id === output.record_id && frame.payload.state === 'ACKNOWLEDGED'),
			{ timeout: 90_000, message: 'The real sealed envelope must be decrypted, validated and ACKed' }).toBe(true);
			expect(frames.some((frame: any) => frame.direction === 'sent' && frame.type === 'recovery_output_get'
				&& frame.payload.record_id === output.record_id)).toBe(true);
			expect(frames.some((frame: any) => frame.direction === 'sent' && frame.type === 'recovery_output_ack_embed'
				&& frame.payload.record_id === output.record_id && frame.payload.canonical_source === 'head')).toBe(true);
		}
	} finally {
		await test.info().attach('canonical-recovery-frames', {
			body: JSON.stringify(canonicalRecoveryFrameReceipt(frames.slice(recoveryOffset), outputs)),
			contentType: 'application/json',
		});
	}
	const proof = await availability();
	expect(proof).toMatchObject({ state: 'ready', canonical_revision: { version: 1, write_state: 'immutable' },
		recovery_ack: { state: 'ACKNOWLEDGED', version: 1, canonical_digest: fixture.outputs[0].canonical_digest } });
	expect(proof.canonical_revision.ciphertext_sha256).toBe(proof.recovery_ack.canonical_digest);
	const afterAck = frames.length;
	expect(await lifecycle('preview', { embedId: fixture.parentId })).toMatchObject({
		updated: true, durablePayloadReturned: false, canonicalPayloadUnchanged: true, resultCount: 1,
		previewResults: [{ title: 'Enriched canonical preview', url: 'https://example.com/canonical-fixture' }],
	});
	for (const embedId of [fixture.parentId, fixture.childId]) {
		expect(await replay(embedId)).toMatchObject({ pending: false, connected: true, status: 'adopted' });
		expect(await read(embedId)).toEqual(before.get(embedId));
	}

	// These rows model ciphertext retained by old browser builds: no state/origin,
	// one equivalent fresh encryption and one conflicting body for the same head.
	const equivalent = await replay(fixture.parentId, false, true);
	const conflicting = await replay(fixture.parentId, true, true);
	const queued = await lifecycle('inspect', { operationIds: [equivalent.operationId, conflicting.operationId] });
	expect(queued).toHaveLength(2);
	const originalConflict = queued.find((operation: any) => operation.operation_id === conflicting.operationId);
	expect(originalConflict.state).toBeUndefined();
	await reconnect();
	await expect.poll(() => lifecycle('inspect', { operationIds: [equivalent.operationId] })).toEqual([]);
	await expect.poll(async () => (await lifecycle('inspect', { operationIds: [conflicting.operationId] }))[0]?.state).toBe('conflict');
	const terminal = (await lifecycle('inspect', { operationIds: [conflicting.operationId] }))[0];
	expect(terminal.store_embed_payload).toEqual(originalConflict.store_embed_payload);
	expect(terminal.store_embed_keys_payload).toEqual(originalConflict.store_embed_keys_payload);
	expect(terminal.store_embed_keys_payload.keys).toHaveLength(4);
	expect(terminal.failure_code).toBeTruthy();
	await expect.poll(() => conflictWarnings.length).toBe(1);
	await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(fixture.chatId)}`));
	await focusRecoveryPage(page);
	await expect(page.getByTestId('message-assistant').first()).toBeVisible();
	await reconnect();
	expect(await lifecycle('inspect', { operationIds: [conflicting.operationId] })).toEqual([terminal]);
	for (const embedId of [fixture.parentId, fixture.childId]) expect(await read(embedId)).toEqual(before.get(embedId));

	// Normal reload retains the original client's explicit terminal row.
	await page.reload();
	await focusRecoveryPage(page);
	await expect(page.getByTestId('message-assistant').first()).toBeVisible();
	expect(await lifecycle('inspect', { operationIds: [conflicting.operationId] })).toEqual([terminal]);
	const retainedClient = page;
	// A separate browser context has no IndexedDB, localStorage or cookies. Its
	// real login restores server data while the original client stays connected.
	const coldContext = await browser.newContext({ baseURL,
		recordVideo: { dir: test.info().outputPath('canonical-cold-client') } });
	expect(await coldContext.storageState({ indexedDB: true })).toEqual({ cookies: [], origins: [] });
	const coldPage = await coldContext.newPage();
	const coldVideo = coldPage.video();
	const coldFrames = observeRecoveryFrames(coldPage, true);
	try {
		page = coldPage;
		await observeToasts(page);
		await loginToTestAccount(page, log, createStepScreenshotter(log));
		await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(fixture.chatId)}`));
		await focusRecoveryPage(page);
		await expect.poll(() => coldFrames.some((frame: any) => frame.type === 'native_client_lifecycle_ack'
			&& frame.payload.is_foreground === true), { timeout: 60_000 }).toBe(true);
		await expect(page.getByTestId('message-assistant').first()).toBeVisible();
		expect(await lifecycle('inspect', { operationIds: [conflicting.operationId] })).toEqual([]);
		for (const embedId of [fixture.parentId, fixture.childId]) {
			expect(await replay(embedId)).toMatchObject({ connected: true, status: 'adopted' });
			expect(await read(embedId)).toEqual(before.get(embedId));
		}
		expect((await availability()).canonical_revision.write_state).toBe('immutable');
		expect([...frames.slice(afterAck), ...coldFrames].filter((frame: any) => frame.direction === 'sent' && frame.type === 'store_embed'
			&& [fixture.parentId, fixture.childId].includes(frame.payload.embed_id))).toHaveLength(0);
		expect([...frames, ...coldFrames].filter((frame: any) => frame.type === 'error' && frame.payload.code === 'embed_write_denied')).toHaveLength(0);
		expect(errorToasts).toEqual([]);

		// The guard still admits a normal fresh create after terminal conflicts exist.
		const fresh = await page.evaluate(() => (window as any).__openmatesE2ESeedCanonicalEmbedReplay());
		seedCanonicalFixture(fresh, 'ownership');
		const newCreate = await page.evaluate(({ chatId, head }: any) =>
			(window as any).__openmatesE2EInitialCanonicalEmbedWrite({ chatId, head }), { chatId: fresh.chatId, head: fresh.parent });
		expect(newCreate.status).toBe('persisted');
		seedCanonicalFixture(fresh, 'wrappers');
		expect((await read(fresh.parentId, true, fresh.chatId)).embed.encrypted_content).toBe(fresh.parent.encrypted_content);
		// Authentication and source-chat authority remain mandatory for scoped reads.
		expect([401, 403]).toContain((await read(fixture.childId, false)).status);
		expect([403, 404]).toContain((await read(fixture.childId, true, fresh.chatId)).status);
		expect(await retainedClient.evaluate((input: any) => (window as any).__openmatesE2ECanonicalLifecycle(input),
			{ action: 'inspect', chatId: fixture.chatId, operationIds: [conflicting.operationId] })).toEqual([terminal]);
		expect(errorToasts).toEqual([]);
		expect(conflictWarnings).toHaveLength(1);
	} finally {
		await coldContext.close();
		if (coldVideo) await test.info().attach('canonical-cold-client', { path: await coldVideo.path(), contentType: 'video/webm' });
	}
});
