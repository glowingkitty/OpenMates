/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (draft storage policy moved into the Rust core; the UI is unchanged, the Playwright video and step screenshots are kept)
/**
 * Opt-in shared Rust core (WASM) — drafts unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: drafts). A saved chat is seeded through
 * the normal send (CI mock replay) and reopened behind Rust history. Typing in
 * its editor must save the draft through the shared Worker's `drafts` unit
 * (marker `rust-synced`: Rust encrypted and stored it in chats_db, the page sent
 * Rust's ciphertext on the existing socket and Rust removed its sync intent),
 * with still one shared Worker and one WASM instance. After a reload the
 * existing TS restore must decrypt the Rust-written draft back into the editor
 * (byte compatibility); clearing it removes the draft again.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { seedCodeEmbedChat } = require('./helpers/embed-ready-metrics');
const { rustCoreInstances } = require('./helpers/rust-core-instances');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

let consoleForFailure: string[] = [];
test.afterEach(async ({ page }: { page: any }, testInfo: any) => {
	if (testInfo.status !== testInfo.expectedStatus) {
		console.log('--- failure url ---\n' + page.url());
		console.log('--- browser console (errors/warnings/draft/rust, last 150) ---\n'
			+ consoleForFailure.filter((line) => /error|warn|fail|rust|draft/i.test(line)).slice(-150).join('\n'));
	}
});

/** JSON type of each chats_db field the Rust draft writer validates (types only, never values). */
function draftRowShape(chatId: string): Promise<Record<string, string> | null> {
	const fields = ['chat_id', 'id', 'user_id', 'owner_id', 'team_id', 'hashed_team_id', 'chat_visibility', 'encrypted_chat_key',
		'key_version', 'key_fingerprint', 'messages_v', 'draft_v', 'cleared_draft_v', 'encrypted_draft_md', 'encrypted_draft_preview', 'updated_at'];
	return new Promise((resolve) => {
		const open = indexedDB.open('chats_db');
		open.onerror = () => resolve(null);
		open.onsuccess = () => {
			const db = open.result;
			const request = db.transaction('chats', 'readonly').objectStore('chats').get(chatId);
			request.onsuccess = () => {
				db.close();
				const row = request.result as Record<string, unknown> | undefined;
				if (!row) { resolve(null); return; }
				const shape: Record<string, string> = {};
				for (const field of fields) {
					const value = row[field];
					shape[field] = !(field in row) ? 'absent' : value === null ? 'null' : typeof value === 'number'
						? (Number.isSafeInteger(value) && value >= 0 ? 'uint' : 'number') : Array.isArray(value) ? 'array' : typeof value;
				}
				resolve(shape);
			};
			request.onerror = () => { db.close(); resolve(null); };
		};
	});
}

/** Committed chats_db draft fields of one chat (ciphertext presence and version only). */
function chatIds(): Promise<string[]> {
	return new Promise((resolve) => {
		const open = indexedDB.open('chats_db');
		open.onerror = () => resolve([]);
		open.onsuccess = () => {
			const db = open.result;
			const request = db.transaction('chats', 'readonly').objectStore('chats').getAllKeys();
			request.onsuccess = () => { db.close(); resolve((request.result as IDBValidKey[]).map(String)); };
			request.onerror = () => { db.close(); resolve([]); };
		};
	});
}

function draftRow(chatId: string): Promise<{ draftV: number; hasCiphertext: boolean } | null> {
	return new Promise((resolve) => {
		const open = indexedDB.open('chats_db');
		open.onerror = () => resolve(null);
		open.onsuccess = () => {
			const db = open.result;
			const request = db.transaction('chats', 'readonly').objectStore('chats').get(chatId);
			request.onsuccess = () => {
				db.close();
				const row = request.result;
				resolve(row ? { draftV: Number(row.draft_v ?? 0), hasCiphertext: typeof row.encrypted_draft_md === 'string' && row.encrypted_draft_md.length > 0 } : null);
			};
			request.onerror = () => { db.close(); resolve(null); };
		};
	});
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
test('Rust core saves an existing chat draft and the TS restore decrypts it', async ({ page, browser }: { page: any; browser: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_DRAFTS');
	const screenshot = createStepScreenshotter(log);
	const consoleLines: string[] = [];
	consoleForFailure = consoleLines;
	page.on('console', (msg: any) => { consoleLines.push(`[${msg.type()}] ${msg.text()}`.slice(0, 400)); });
	page.on('pageerror', (error: Error) => { consoleLines.push(`[pageerror] ${error.message}`.slice(0, 400)); });

	const chatId = await seedCodeEmbedChat(page, log, screenshot);
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	await page.reload();
	await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rustCoreHistory ?? null),
		{ message: 'Rust supplied the reopened chat history', timeout: 60000 }).toMatch(/^rust:\d+$/);

	// Drafts need the server-checked history admission; a save before it is routed
	// to TS (marked). Wait for the upgrade mark, but do not fail here: the routing
	// evidence below records whether and when it arrived.
	await page.waitForFunction(() => performance.getEntriesByName('openmates:rust:session-ready').length > 0, null, { timeout: 30000 })
		.catch(() => log('session-ready mark not seen within 30 s'));
	const draftText = `Rust drafts unit check ${Date.now()}`;
	// The reloaded chat can mount a hidden editor first; target the visible one.
	const visibleEditor = () => page.getByTestId('message-editor').filter({ visible: true }).first();
	await visibleEditor().locator('.ProseMirror').click();
	await page.keyboard.type(draftText);
	await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rustCoreDraft ?? null),
		{ message: 'the draft save was routed', timeout: 30000 }).toMatch(/^(rust-synced|rust-failed-|rust-ack-failed-)/);
	// Routing evidence: history session marks (local/server admission, readmits,
	// server reads) and draft route marks, with times relative to navigation.
	const evidence = await page.evaluate(() => ({
		marker: document.documentElement.dataset.rustCoreDraft ?? null,
		history: document.documentElement.dataset.rustCoreHistory ?? null,
		marks: performance.getEntriesByType('mark').filter((entry) => entry.name.startsWith('openmates:rust:'))
			.map((entry) => ({ name: entry.name.slice('openmates:rust:'.length), atMs: Math.round(entry.startTime) }))
	}));
	const rowShape = await page.evaluate(draftRowShape, chatId);
	log('draft routing evidence', { ...evidence, rowShape });
	await testInfo.attach('draft-routing-evidence.json', { body: JSON.stringify({ ...evidence, rowShape }, null, 2), contentType: 'application/json' });
	expect(evidence.marker, 'the drafts unit saved and synced the draft').toBe('rust-synced');
	const saved = await page.evaluate(draftRow, chatId);
	expect(saved?.hasCiphertext, 'encrypted draft stored in chats_db').toBe(true);
	expect(saved!.draftV, 'Rust assigned a draft version').toBeGreaterThan(0);
	const instances = await rustCoreInstances(page);
	expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
	expect(instances.sharedWorkerWasm, 'one shared Worker WASM instance').toBe(1);
	expect((instances.workers as { name: string }[]).filter((worker) => worker.name === 'shared.worker').length, 'one shared Rust core Worker').toBe(1);
	expect((instances.workers as { name: string }[]).filter((worker) => /draft/i.test(worker.name)).length, 'no dedicated draft Worker').toBe(0);
	await screenshot(page, 'rust-draft-saved');

	// Sync-inbound slice 2: a second signed-in device receives the server's chat_draft_updated
	// broadcast (the sender device is excluded) and the Rust sync unit admits that frame.
	let consecutiveText = draftText;
	const deviceB = await browser.newContext();
	const pageB = await deviceB.newPage();
	try {
		await loginToTestAccount(pageB, log, screenshot);
		await pageB.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
		await expect.poll(() => pageB.evaluate(() => typeof (window as any).__openmatesRustSyncStats === 'function'),
			{ message: 'second device loaded the Rust sync unit', timeout: 60000 }).toBe(true);

	// Consecutive edits (the bench types several): each one is a new Rust draft version, never a failure marker.
	let previousVersion = saved!.draftV;
	consecutiveText = draftText;
	for (let edit = 1; edit <= 3; edit += 1) {
		consecutiveText += ` edit ${edit}`;
		await page.keyboard.type(` edit ${edit}`);
		await expect.poll(async () => (await page.evaluate(draftRow, chatId))?.draftV ?? 0,
			{ message: `consecutive Rust draft save ${edit} committed a new version`, timeout: 30000 }).toBeGreaterThan(previousVersion);
		previousVersion = (await page.evaluate(draftRow, chatId))!.draftV;
		expect(await page.evaluate(() => document.documentElement.dataset.rustCoreDraft ?? null),
			`consecutive save ${edit} stayed on the Rust writer`).toMatch(/^rust-(local|synced)$/);
	}
		await expect.poll(() => pageB.evaluate(() => (window as any).__openmatesRustSyncStats?.()?.ops?.updateFrame ?? 0),
			{ message: 'second device admitted the draft frame in the Rust sync unit', timeout: 45000 }).toBeGreaterThan(0);
		expect(await pageB.evaluate(() => (window as any).__openmatesRustSyncStats?.()?.failures ?? 0), 'no sync unit call failed on device B').toBe(0);

		// Sync-inbound title frame: renaming the chat on device A broadcasts chat_title_updated; device B
		// shows the new title and its Rust sync unit admits one more update frame.
		const framesBefore: number = await pageB.evaluate(() => (window as any).__openmatesRustSyncStats?.()?.ops?.updateFrame ?? 0);
		const renamed = `Rust synced title ${chatId.slice(0, 8)}`;
		await page.getByTestId('chat-header-title').click();
		await page.getByTestId('workspace-detail-title-input').fill(renamed);
		await page.getByTestId('workspace-detail-title-save').click();
		await expect(page.getByTestId('chat-header-title')).toHaveText(renamed, { timeout: 30000 });
		await expect(pageB.getByTestId('chat-header-title'), 'device B received the renamed title').toHaveText(renamed, { timeout: 45000 });
		await expect.poll(() => pageB.evaluate(() => (window as any).__openmatesRustSyncStats?.()?.ops?.updateFrame ?? 0),
			{ message: 'device B admitted the chat_title_updated frame in the Rust sync unit', timeout: 30000 }).toBeGreaterThan(framesBefore);
		expect(await pageB.evaluate(() => (window as any).__openmatesRustSyncStats?.()?.failures ?? 0), 'no sync unit call failed on device B after the title frame').toBe(0);
	} finally {
		await deviceB.close();
	}

	await page.reload();
	await expect(visibleEditor(), 'the TS restore decrypts the Rust-written draft').toContainText(consecutiveText, { timeout: 60000 });
	await screenshot(page, 'rust-draft-restored');

	// After the reload no ProseMirror has a visible box until the restored input is focused: click the visible input itself.
	await visibleEditor().click({ position: { x: 20, y: 10 } });
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.press('Backspace');
	await expect.poll(async () => (await page.evaluate(draftRow, chatId))?.hasCiphertext ?? false,
		{ message: 'clearing the editor removes the draft', timeout: 30000 }).toBe(false);
});

/** Number of queued sync intents (pending_sync_changes) for one chat; never reads their content. */
function queuedIntentCount(chatId: string): Promise<number> {
	return new Promise((resolve) => {
		const open = indexedDB.open('chats_db');
		open.onerror = () => resolve(-1);
		open.onsuccess = () => {
			const db = open.result;
			const request = db.transaction('pending_sync_changes', 'readonly').objectStore('pending_sync_changes').getAll();
			request.onsuccess = () => {
				db.close();
				resolve((request.result as { chat_id?: string }[]).filter((row) => row.chat_id === chatId).length);
			};
			request.onerror = () => { db.close(); resolve(-1); };
		};
	});
}

// contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
test('Rust core saves a draft written offline locally and publishes its queued intent after reconnect', async ({ page, context }: { page: any; context: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_DRAFTS_OFFLINE');
	const screenshot = createStepScreenshotter(log);
	const consoleLines: string[] = [];
	consoleForFailure = consoleLines;
	page.on('console', (msg: any) => { consoleLines.push(`[${msg.type()}] ${msg.text()}`.slice(0, 400)); });

	const chatId = await seedCodeEmbedChat(page, log, screenshot);
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rustCoreHistory ?? null),
		{ message: 'Rust supplied the chat history while online', timeout: 60000 }).toMatch(/^rust:\d+$/);
	const onlineVersion = (await page.evaluate(draftRow, chatId))?.draftV ?? 0;
	const chatsBeforeOffline = new Set(await page.evaluate(chatIds));

	// Cold offline boot: the app shell still loads (as from a cache), but every API
	// request and WebSocket fails, so the browser restore cannot validate the session
	// and the core admits a local-read-only client. Context-level routes also cover the
	// shared Worker's requests, which page routes do not see. (context.setOffline
	// before a reload would block the shell itself: the page stays blank.)
	let apiOffline = true;
	const apiRequest = /\/v1\//;
	const failApiRequest = async (route: any) => {
		if (apiOffline) await route.abort('internetdisconnected');
		else await route.continue();
	};
	await context.route(apiRequest, failApiRequest);
	await context.routeWebSocket(/\/v1\/ws(?:\?|$)/, async (socket: any) => {
		if (apiOffline) await socket.close({ code: 3001, reason: 'API unreachable in test' });
		else socket.connectToServer();
	});
	// ActiveChat records its draft-restore decisions in this trace when a page opts in.
	await page.addInitScript(() => { (window as any).__savedComposerInputTrace = []; });
	await page.reload();
	// A person types into the chat they see: wait until the deep-linked chat is open
	// from the local cache and its (empty) draft restore has settled. Text typed
	// before that lands in the blank new-chat composer the page mounts first.
	await expect(page.getByTestId('active-chat-container'), 'the deep-linked chat opened offline')
		.toHaveAttribute('data-current-chat-id', chatId, { timeout: 60000 });
	await expect.poll(() => page.evaluate((id: string) => ((window as any).__savedComposerInputTrace ?? [])
		.some((entry: { kind?: string; chat?: string }) => entry.kind === 'noDraftRestoreDecision' && entry.chat === id), chatId),
		{ message: 'the open chat finished its draft restore', timeout: 30000 }).toBe(true);
	const visibleEditor = () => page.getByTestId('message-editor').filter({ visible: true }).first();
	await visibleEditor().locator('.ProseMirror').click({ timeout: 60000 });
	let offlineSaveState = 'none';
	const offlineText = 'Offline draft written without a connection';
	await page.keyboard.type(offlineText);
	const offlineMarker = async () => `marker=${await page.evaluate(() => document.documentElement.dataset.rustCoreDraft ?? null)}`;
	try {
		await expect.poll(async () => {
			const version = (await page.evaluate(draftRow, chatId))?.draftV ?? 0;
			if (version <= onlineVersion) offlineSaveState = await offlineMarker();
			return version;
		}, { message: 'the offline draft was saved locally by Rust', timeout: 30000 }).toBeGreaterThan(onlineVersion);
	} catch (error) {
		const draftLines = consoleLines.filter((line) => /DraftService|RustCore|draft/i.test(line)).slice(-25);
		throw new Error(`the offline draft was not saved by Rust (route outcome: ${offlineSaveState}); draft console lines:\n${draftLines.join('\n')}\n${error instanceof Error ? error.message : String(error)}`);
	}
	expect((await page.evaluate(draftRow, chatId))?.hasCiphertext, 'encrypted draft stored in chats_db').toBe(true);
	expect(await page.evaluate(() => document.documentElement.dataset.rustCoreDraft ?? null), 'no TS writer fallback').toMatch(/^rust-(local|synced)$/);
	expect(await page.evaluate(queuedIntentCount, chatId), 'an encrypted update is queued offline').toBeGreaterThan(0);
	// The offline draft belongs to the open chat: no new draft-only chat was minted for it.
	expect((await page.evaluate(chatIds)).filter((id: string) => !chatsBeforeOffline.has(id)), 'no extra chat created offline').toEqual([]);
	await screenshot(page, 'rust-draft-offline-saved');

	// Back online: the next boot validates the session, and the queued encrypted
	// intent is published from durable storage (it must survive the reload).
	apiOffline = false;
	await context.unroute(apiRequest, failApiRequest);
	await page.reload();
	await expect.poll(() => page.evaluate(queuedIntentCount, chatId),
		{ message: 'the queued intent was published and removed after reconnect', timeout: 90000 }).toBe(0);
	expect((await page.evaluate(draftRow, chatId))?.draftV ?? 0, 'the offline draft version survived publication')
		.toBeGreaterThan(onlineVersion);
	await testInfo.attach('offline-draft.json', { body: JSON.stringify({ onlineVersion, final: await page.evaluate(draftRow, chatId) }), contentType: 'application/json' });
	await screenshot(page, 'rust-draft-offline-published');
});
