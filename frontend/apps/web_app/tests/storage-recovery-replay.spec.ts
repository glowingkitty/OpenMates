/* eslint-disable @typescript-eslint/no-require-imports */
/** Signed, provider-free child recovery across a browser disconnect. */
// contract-test-file: infrastructure
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');
const { observeRecoveryFrames, availableOutputs, requireActiveRecoveryDiscovery, focusRecoveryPage, requireForegroundRecoveryLifecycle } = require('./storage-recovery-fixtures');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

function requireSignedRecoveryProfile(): void {
	if (process.env.E2E_STORAGE_CAPACITY !== '1') {
		throw new Error('Storage recovery replay requires the isolated signed zero-provider CI profile.');
	}
	if (!getTestAccount().email) {
		throw new Error('Storage recovery replay requires a disposable isolated test account.');
	}
}

function deriveApiUrl(baseURL: string): string {
	const explicit = process.env.OPENMATES_E2E_API_URL || process.env.PLAYWRIGHT_TEST_API_URL;
	if (explicit) return explicit.replace(/\/$/, '');
	const url = new URL(baseURL);
	if (url.hostname.startsWith('app.')) url.hostname = `api.${url.hostname.slice(4)}`;
	return url.origin;
}

async function disconnectCanonicalWrites(page: any): Promise<void> {
	await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, (socket: any) => {
		const server = socket.connectToServer();
		const blocked = new Set([
			'store_embed', 'store_embed_diff', 'store_embed_keys',
			'store_chat_compression_checkpoint', 'recovery_output_persist_message',
			'recovery_output_persist_summary', 'recovery_output_ack_checkpoint',
			'recovery_output_ack_embed', 'recovery_job_claim',
		]);
		socket.onMessage((raw: unknown) => {
			let type = '';
			try { type = JSON.parse(String(raw)).type; } catch { /* Preserve non-JSON frames. */ }
			if (!blocked.has(type)) server.send(raw);
		});
		server.onMessage((raw: unknown) => socket.send(raw));
	});
}

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
test('saved child message and summary replay through sealed output records after disconnect', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(240_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const originContext = await browser.newContext({ baseURL });
	const recoveryContext = await browser.newContext({ baseURL });
	const origin = await originContext.newPage();
	const recovery = await recoveryContext.newPage();
	const log = createSignupLogger('storage-recovery-replay');
	const screenshot = createStepScreenshotter(log);
	const frames: Array<{ direction: 'sent' | 'received'; type: string; payload: Record<string, any> }> = [];
	recovery.on('websocket', (socket: any) => {
		const capture = (direction: 'sent' | 'received') => (frame: any) => {
			try {
				const message = JSON.parse(String(frame.payload));
				if (typeof message.type === 'string') frames.push({ direction, type: message.type, payload: message.payload ?? {} });
			} catch { /* Binary frames contain no recovery protocol. */ }
		};
		socket.on('framesent', capture('sent'));
		socket.on('framereceived', capture('received'));
	});
	try {
		await disconnectCanonicalWrites(origin);
		await installE2EServerContentOverrideGate(origin, 'storage-recovery-replay');
		await loginToTestAccount(origin, log, screenshot);
		await startNewChat(origin, log);
		await sendMessage(origin,
			'Synthetic child recovery. STORAGE_CAPACITY_SCENARIO:child <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-recovery-child');
		const chatId = origin.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		await originContext.close();

		await loginToTestAccount(recovery, log, screenshot);
		await recovery.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`), { waitUntil: 'domcontentloaded' });
		await expect.poll(() => frames.some((frame) => frame.direction === 'received'
			&& frame.type === 'recovery_outputs_available'
			&& frame.payload.outputs?.some((output: any) => output.root_chat_id === chatId)),
		{ timeout: 180_000 }).toBe(true);
		const discovered = frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.filter((output: any) => output.root_chat_id === chatId);
		expect(discovered.some((output: any) => output.output_kind === 'message' && output.message_role === 'user')).toBe(true);
		expect(discovered.some((output: any) => output.output_kind === 'message' && output.message_role === 'assistant')).toBe(true);
		expect(discovered.some((output: any) => output.output_kind === 'summary')).toBe(true);
		const childChatIds = [...new Set(discovered.map((output: any) => output.target_chat_id))];
		expect(childChatIds).toHaveLength(1);
		expect(childChatIds[0]).not.toBe(chatId);
		for (const { output_kind: kind, record_id: recordId } of discovered) {
			const acknowledgedType = kind === 'message' ? 'recovery_output_persisted' : 'recovery_output_summary_persisted';
			await expect.poll(() => frames.some((frame) => frame.direction === 'received'
				&& frame.type === acknowledgedType && frame.payload.record_id === recordId
				&& frame.payload.state === 'ACKNOWLEDGED'), { timeout: 120_000 }).toBe(true);
		}
		// These receipts restore the child, not the root chat we used for discovery.
		await recovery.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(String(childChatIds[0]))}`), { waitUntil: 'domcontentloaded' });
		await expect(recovery.getByTestId('message-user').filter({ hasText: 'Summarize this disposable synthetic storage task.' }).first()).toBeVisible();
		await expect(recovery.getByTestId('message-assistant').filter({ hasText: 'Synthetic child storage result.' }).first()).toBeVisible();
		await recovery.reload();
		await expect(recovery.getByTestId('message-assistant').filter({ hasText: 'Synthetic child storage result.' }).first())
			.toBeVisible({ timeout: 90_000 });
	} finally {
		await recoveryContext.close();
		await originContext.close().catch(() => undefined);
	}
});

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
test('sealed output waits for foreground acknowledgement and fresh discovery', async ({ browser }: { browser: any }, testInfo: any) => {
	requireSignedRecoveryProfile();
	test.setTimeout(240_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const sourceContext = await browser.newContext({ baseURL });
	const destinationContext = await browser.newContext({ baseURL, recordVideo: { dir: testInfo.outputDir } });
	const source = await sourceContext.newPage();
	const destination = await destinationContext.newPage();
	const log = createSignupLogger('storage-recovery-foreground');
	const screenshot = createStepScreenshotter(log);
	const frames: Array<{ direction: string; type: string; payload: Record<string, any> }> = [];
	destination.on('websocket', (socket: any) => {
		for (const [direction, event] of [['sent', 'framesent'], ['received', 'framereceived']]) {
			socket.on(event, (frame: any) => {
				try {
					const parsed = JSON.parse(String(frame.payload));
					frames.push({ direction, type: parsed.type, payload: parsed.payload ?? {} });
				} catch { /* Ignore binary frames. */ }
			});
		}
	});
	try {
		await disconnectCanonicalWrites(source);
		await installE2EServerContentOverrideGate(source, 'storage-recovery-replay');
		await loginToTestAccount(source, log, screenshot);
		await startNewChat(source, log);
		await sendMessage(source,
			'Synthetic child recovery. STORAGE_CAPACITY_SCENARIO:child <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-recovery-foreground-source');
		const chatId = source.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		await sourceContext.close();
		await destination.addInitScript(() => {
			(window as any).__recoveryFocused = false;
			Object.defineProperty(document, 'hasFocus', {
				configurable: true,
				value: () => (window as any).__recoveryFocused,
			});
		});
		await loginToTestAccount(destination, log, screenshot);
		await destination.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
		await expect.poll(() => frames.some((frame) => frame.direction === 'sent'
			&& frame.type === 'native_client_lifecycle' && frame.payload.is_foreground === false),
		{ timeout: 60_000 }).toBe(true);
		await expect.poll(() => frames.some((frame) => frame.direction === 'received'
			&& frame.type === 'native_client_lifecycle_ack' && frame.payload.is_foreground === false), { timeout: 120_000 }).toBe(true);
		expect(frames.some((frame) => frame.direction === 'sent'
			&& frame.type.startsWith('recovery_output_'))).toBe(false);
		await destination.evaluate(() => {
			(window as any).__recoveryFocused = true;
			window.dispatchEvent(new Event('focus'));
		});
		await expect.poll(() => frames.some((frame) => frame.direction === 'received'
			&& frame.type === 'native_client_lifecycle_ack' && frame.payload.is_foreground === true),
		{ timeout: 60_000 }).toBe(true);
		await expect.poll(() => frames.some((frame) => frame.direction === 'received'
			&& frame.type === 'recovery_output_persisted' && frame.payload.state === 'ACKNOWLEDGED'),
		{ timeout: 120_000 }).toBe(true);
		const foregroundAck = frames.findIndex((frame) => frame.direction === 'received'
			&& frame.type === 'native_client_lifecycle_ack' && frame.payload.is_foreground === true);
		const discovery = frames.findIndex((frame, index) => index > foregroundAck
			&& frame.direction === 'received' && frame.type === 'recovery_outputs_available');
		const firstWrite = frames.findIndex((frame) => frame.direction === 'sent'
			&& frame.type.startsWith('recovery_output_'));
		expect(discovery).toBeGreaterThan(foregroundAck);
		expect(firstWrite).toBeGreaterThan(discovery);
	} finally {
		await destinationContext.close();
		await sourceContext.close().catch(() => undefined);
	}
});

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,code-run.artifacts.chat-bound-versioned
test('saved code embed and version diff replay with canonical ciphertext acknowledgements', async ({ browser }: { browser: any }, testInfo: any) => {
	requireSignedRecoveryProfile();
	test.setTimeout(360_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const log = createSignupLogger('storage-recovery-artifacts');
	const screenshot = createStepScreenshotter(log);
	const first = await browser.newContext({ baseURL });
	const firstPage = await first.newPage();
	const restored = await browser.newContext({ baseURL, recordVideo: { dir: testInfo.outputDir } });
	const restoredPage = await restored.newPage();
	const frames: Array<{ direction: string; type: string; payload: Record<string, any> }> = [];
	restoredPage.on('websocket', (socket: any) => {
		for (const [direction, event] of [['sent', 'framesent'], ['received', 'framereceived']]) {
			socket.on(event, (frame: any) => {
				try {
					const parsed = JSON.parse(String(frame.payload));
					frames.push({ direction, type: parsed.type, payload: parsed.payload ?? {} });
				} catch { /* Ignore non-JSON frames. */ }
			});
		}
	});
	try {
		await disconnectCanonicalWrites(firstPage);
		await installE2EServerContentOverrideGate(firstPage, 'storage-recovery-replay');
		await loginToTestAccount(firstPage, log, screenshot);
		await startNewChat(firstPage, log);
		await sendMessage(firstPage,
			'Generate the scripted code artifact. STORAGE_CAPACITY_SCENARIO:recovery_embed <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-recovery-embed');
		const chatId = firstPage.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		await first.close();
		await loginToTestAccount(restoredPage, log, screenshot);
		await restoredPage.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
		await expect.poll(() => frames.filter((frame) => frame.direction === 'received'
			&& frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.filter((output: any) => output.root_chat_id === chatId)
			.map((output: any) => output.output_kind), { timeout: 180_000 })
			.toEqual(expect.arrayContaining(['embed', 'diff']));
		const records = frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.filter((output: any) => output.root_chat_id === chatId && ['embed', 'diff'].includes(output.output_kind));
		for (const output of records) {
			await expect.poll(() => frames.some((frame) => frame.direction === 'received'
				&& frame.type === 'recovery_output_embed_acknowledged'
				&& frame.payload.record_id === output.record_id && frame.payload.state === 'ACKNOWLEDGED'),
			{ timeout: 120_000 }).toBe(true);
		}
		// The next unsaved version must be absent, not an existing chain that
		// requires a snapshot. Typed recovery uses this distinction to persist it.
		const initialDiff = records.find((output: any) => output.output_kind === 'diff');
		expect(initialDiff).toBeTruthy();
		const missingVersion = await restoredPage.request.get(
			`${deriveApiUrl(baseURL)}/v1/embeds/${encodeURIComponent(initialDiff.subject_id)}/versions/${initialDiff.output_version + 1}`
			+ `?capability=bounded-v1&chat_id=${encodeURIComponent(chatId)}`,
			{ headers: { 'X-OpenMates-Client-Capabilities': 'agentic-storage-v2' } }
		);
		expect(missingVersion.status()).toBe(404);
		const update = await browser.newContext({ baseURL });
		try {
			const updatePage = await update.newPage();
			await disconnectCanonicalWrites(updatePage);
			await installE2EServerContentOverrideGate(updatePage, 'storage-recovery-replay');
			await loginToTestAccount(updatePage, log, screenshot);
			await updatePage.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
			// Hydrate the existing response before the send helper captures its baseline.
			// Otherwise the old response can masquerade as acceptance of this follow-up.
			await expect(updatePage.locator(`[data-action="message-input"][data-current-chat-id="${chatId}"]`)).toBeVisible();
			await expect(updatePage.getByTestId('message-assistant').first()).toBeVisible();
			await sendMessage(updatePage,
				'Apply the scripted patch to recovery_demo.py. STORAGE_CAPACITY_SCENARIO:recovery_diff <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
				log, screenshot, 'storage-recovery-diff');
		} finally {
			await update.close();
		}
		await restoredPage.bringToFront();
		await expect.poll(() => restoredPage.evaluate(() =>
			document.visibilityState === 'visible' && document.hasFocus()
		), { timeout: 10_000 }).toBe(true);
		const framesBeforeReload = frames.length;
		await restoredPage.reload();
		await expect.poll(() => frames.slice(framesBeforeReload).some((frame) => frame.direction === 'received'
			&& frame.type === 'native_client_lifecycle_ack' && frame.payload.is_foreground === true),
		{ timeout: 60_000 }).toBe(true);
		await expect.poll(() => frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.some((output: any) => output.root_chat_id === chatId
				&& output.output_kind === 'diff' && output.output_version > 1),
		{ timeout: 180_000 }).toBe(true);
		const patch = frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.find((output: any) => output.root_chat_id === chatId
				&& output.output_kind === 'diff' && output.output_version > 1);
		await expect.poll(() => frames.some((frame) => frame.direction === 'received'
			&& frame.type === 'recovery_output_embed_acknowledged'
			&& frame.payload.record_id === patch.record_id && frame.payload.state === 'ACKNOWLEDGED'),
		{ timeout: 120_000 }).toBe(true);
		await restoredPage.reload();
		await expect(restoredPage.getByTestId('message-assistant').first()).toBeVisible();
	} finally {
		await first.close().catch(() => undefined);
		await restored.close();
	}
});

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,storage.compression.incremental-archive
test('sealed compression checkpoint restores its canonical encrypted boundary', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(240_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const log = createSignupLogger('storage-recovery-checkpoint');
	const screenshot = createStepScreenshotter(log);
	const origin = await browser.newContext({ baseURL });
	const source = await origin.newPage();
	const destination = await browser.newContext({ baseURL });
	const recovered = await destination.newPage();
	const frames: Array<{ type: string; payload: Record<string, any> }> = [];
	recovered.on('websocket', (socket: any) => socket.on('framereceived', (frame: any) => {
		try {
			const parsed = JSON.parse(String(frame.payload));
			frames.push({ type: parsed.type, payload: parsed.payload ?? {} });
		} catch { /* Ignore non-JSON frames. */ }
	}));
	try {
		await disconnectCanonicalWrites(source);
		await installE2EServerContentOverrideGate(source, 'storage-recovery-replay');
		await loginToTestAccount(source, log, screenshot);
		await startNewChat(source, log);
		await sendMessage(source,
			'Synthetic durable checkpoint. STORAGE_CAPACITY_SCENARIO:recovery_checkpoint <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-recovery-checkpoint');
		const chatId = source.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		await origin.close();
		await loginToTestAccount(recovered, log, screenshot);
		await recovered.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
		await expect.poll(() => frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.some((output: any) => output.root_chat_id === chatId && output.output_kind === 'checkpoint'),
		{ timeout: 180_000 }).toBe(true);
		const checkpoint = frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.find((output: any) => output.root_chat_id === chatId && output.output_kind === 'checkpoint');
		await expect.poll(() => frames.some((frame) => frame.type === 'recovery_output_checkpoint_acknowledged'
			&& frame.payload.record_id === checkpoint.record_id && frame.payload.state === 'ACKNOWLEDGED'),
		{ timeout: 120_000 }).toBe(true);
	} finally {
		await origin.close().catch(() => undefined);
		await destination.close();
	}
});

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,storage.validation.synthetic-capacity
test('a failed durable child prompt save pauses dependent synthesis', async ({ page }: { page: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(180_000);
	const log = createSignupLogger('storage-recovery-save-failure');
	const screenshot = createStepScreenshotter(log);
	const pauses: Array<Record<string, any>> = [];
	page.on('websocket', (socket: any) => socket.on('framereceived', (frame: any) => {
		try {
			const message = JSON.parse(String(frame.payload));
			if (message.type === 'recovery_output_paused') pauses.push(message.payload ?? {});
		} catch { /* Ignore non-JSON frames. */ }
	}));
	await installE2EServerContentOverrideGate(page, 'storage-recovery-replay');
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	await sendMessage(page,
		'Check a failed durable child save. STORAGE_CAPACITY_SCENARIO:recovery_save_failure <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
		log, screenshot, 'storage-recovery-failure');
	const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
	expect(chatId).toBeTruthy();
	await expect.poll(() => pauses.some((pause) => pause.chat_id === chatId
		&& pause.child_chat_id && pause.reason_code === 'durable_output_unavailable'),
	{ timeout: 120_000 }).toBe(true);
	expect(pauses.filter((pause) => pause.chat_id === chatId)).toHaveLength(1);
});

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
test('ten-child composite replays every sealed embed with typed acknowledgements and ordered fullscreen after reload', async ({ browser }: { browser: any }, testInfo: any) => {
	requireSignedRecoveryProfile();
	test.setTimeout(360_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const origin = await browser.newContext({ baseURL });
	const source = await origin.newPage();
	const destination = await browser.newContext({ baseURL, recordVideo: { dir: testInfo.outputDir } });
	const recovered = await destination.newPage();
	const sourceFrames = observeRecoveryFrames(source, true);
	const recoveryFrames = observeRecoveryFrames(recovered, true);
	const log = createSignupLogger('storage-recovery-composite');
	const screenshot = createStepScreenshotter(log);
	let stage = 'source-login';
	const consoleErrors: Array<Record<string, unknown>> = [];
	// Observe only canonical protocol identities/status; never retain storage bodies,
	// ciphertext, cookies, headers, query strings or server error descriptions.
	const canonicalEvents: Array<Record<string, unknown>> = [];
	const appendCanonicalEvent = (event: Record<string, unknown>) => {
		canonicalEvents.push({ timestamp: Date.now(), ...event });
		if (canonicalEvents.length > 160) canonicalEvents.shift();
	};
	const observeCanonicalProtocol = (page: any, context: string) => {
		page.on('websocket', (socket: any) => {
			for (const [direction, event] of [['sent', 'framesent'], ['received', 'framereceived']]) {
				socket.on(event, (frame: any) => {
					try {
						const message = JSON.parse(String(frame.payload));
						if (!/^(?:store_embed(?:_diff|_keys)?(?:_confirmed)?|error)$/.test(message.type)) return;
						const payload = message.payload ?? {};
						const ids = Object.fromEntries(['request_id', 'recovery_record_id', 'embed_id']
							.filter((key) => /^[0-9a-f-]{36}$/i.test(payload[key] ?? '')).map((key) => [key, payload[key]]));
						if (!Object.keys(ids).length) return;
						const code = typeof payload.code === 'string' && /^[a-z][a-z0-9_]{0,79}$/.test(payload.code) ? payload.code : undefined;
						appendCanonicalEvent({ context, direction, type: message.type, ...ids, ...(code ? { code } : {}) });
					} catch { /* Ignore non-JSON protocol frames. */ }
				});
			}
		});
		page.on('response', (response: any) => {
			if (response.request().method() !== 'GET') return;
			const path = new URL(response.url()).pathname;
			const match = path.match(/^\/v1\/embeds\/chats\/([0-9a-f-]{36})\/embeds\/([0-9a-f-]{36})$/i);
			if (match) appendCanonicalEvent({ context, type: 'canonical_embed_get', chat_id: match[1], embed_id: match[2], status: response.status() });
		});
	};
	observeCanonicalProtocol(source, 'source');
	observeCanonicalProtocol(recovered, 'recovery');

	const observeRecoveryConsole = (page: any, context: string) => page.on('console', async (entry: any) => {
		const level = entry.type();
		const text = entry.text();
		if (!['error', 'warning'].includes(level) || !/\[[^\]]*Recovery[^\]]*\]/.test(text)) return;
		const diagnostic: Record<string, unknown> = {
			context, level, timestamp: new Date().toISOString(),
			category: 'unclassified_recovery_error',
			identities: [...new Set<string>(text.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g) ?? [])].slice(0, 4),
		};
		// Insert before awaiting handles so failure teardown retains the event.
		consoleErrors.push(diagnostic);
		if (consoleErrors.length > 20) consoleErrors.shift();
		const details: Array<Record<string, unknown>> = [];
		for (const handle of entry.args().slice(0, 4)) {
			try {
				const value = await handle.evaluate((raw: any) => {
					if (!raw || typeof raw !== 'object') return null;
					return Object.fromEntries(['name', 'code', 'message', 'stack', 'record_id', 'root_chat_id', 'turn_id', 'request_id']
						.filter((key) => typeof raw[key] === 'string').map((key) => [key, raw[key].slice(0, 2048)]));
				});
				if (!value) continue;
				const safe: Record<string, unknown> = {};
				for (const key of ['record_id', 'root_chat_id', 'turn_id', 'request_id']) {
					if (/^[0-9a-f-]{36}$/i.test(value[key] ?? '')) safe[key] = value[key];
				}
				if (/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(value.name ?? '')) safe.name = value.name;
				if (/^[a-z][a-z0-9_]{0,79}$/.test(value.code ?? '')) safe.code = value.code;
				if (value.message) {
					// Preserve internal recovery failures; never retain arbitrary thrown content.
					safe.message = /^(Canonical|Recovery|Recovered|Acknowledged|Could not|Checkpoint)\b/.test(value.message)
						? value.message.replace(/https?:\/\/\S+/g, '[url]').replace(/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/gi, '[id]')
							.replace(/(failed \(\d+):[^)]*/g, '$1: [redacted]').slice(0, 240)
						: '[redacted unclassified error]';
				}
				if (value.stack) safe.frames = (value.stack.match(/(?:chatSyncServiceHandlersRecovery|[^/\s]*\.js):\d+:\d+/g) ?? []).slice(0, 3);
				if (Object.keys(safe).length) details.push(safe);
			} catch { diagnostic.capture_error = 'console_handle_unavailable'; }
		}
		diagnostic.details = details;
	});
	observeRecoveryConsole(source, 'source');
	observeRecoveryConsole(recovered, 'recovery');
	const identitySummary = (raw: unknown) => {
		const value: Record<string, any> = raw && typeof raw === 'object' ? raw as Record<string, any> : {};
		return Object.fromEntries([
		'direction', 'type', 'state', 'status', 'code', 'request_id', 'record_id', 'recovery_record_id',
		'job_id', 'chat_id', 'root_chat_id', 'target_chat_id', 'subject_id', 'output_kind',
		'output_version', 'message_role', 'is_foreground', 'canonical_source',
	].flatMap((key) => {
		const item = value[key];
		return (typeof item === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(item))
			|| typeof item === 'boolean' || (typeof item === 'number' && Number.isSafeInteger(item))
			? [[key, item]] : [];
		}));
	};
	const summarizeFrames = (frames: typeof sourceFrames) => {
		const selected = frames.filter((frame: any) => /^recovery_/.test(frame.type)
			|| /^native_client_lifecycle(?:_ack)?$/.test(frame.type));
		return { total: selected.length, frames: selected.slice(-80).map((frame: any) => ({
			...identitySummary({ ...frame.payload, direction: frame.direction, type: frame.type }),
			...(Array.isArray(frame.payload.outputs) ? {
				output_count: frame.payload.outputs.length,
				outputs: frame.payload.outputs.slice(0, 32).map(identitySummary),
			} : {}),
		})) };
	};
	const expectedTitles = Array.from({ length: 10 }, (_, index) =>
		`Synthetic Recovery Event ${String(index + 1).padStart(2, '0')}`);
	const requireCalendar = async (page: any) => {
		const view = page.getByTestId('embeds-map-view').filter({ hasText: expectedTitles[0] });
		await expect(view).toBeVisible({ timeout: 90_000 });
		await expect(view).toHaveAttribute('data-loading', 'false');
		await expect(view.getByTestId('embeds-map-view-count')).toHaveText('10 shown');
		const calendar = view.getByTestId('embeds-results-view-calendar');
		await expect(calendar).toBeVisible();
		const children = calendar.getByTestId('embeds-results-view-calendar-item');
		await expect(children).toHaveCount(10);
		await expect(children.locator('strong')).toHaveText(expectedTitles);
		return children;
	};
	// Observe the real calendar interaction's identity without opening overlays
	// or reading embed storage through a test-only path.
	await recovered.addInitScript(() => {
		(window as any).__compositeFullscreenIds = [];
		document.addEventListener('embedfullscreen', (event) => {
			const id = (event as CustomEvent).detail?.embedId;
			if (typeof id === 'string') (window as any).__compositeFullscreenIds.push(id);
		});
	});
	type CompositeOutput = { record_id: string; subject_id: string; output_kind: string };
	const distinctEmbeds = (frames: typeof sourceFrames, chatId: string): CompositeOutput[] =>
		[...new Map<string, CompositeOutput>(availableOutputs(frames, chatId)
			.filter((output: CompositeOutput) => output.output_kind === 'embed')
			.map((output: CompositeOutput) => [output.record_id, output] as const)).values()];
	try {
		await disconnectCanonicalWrites(source);
		await installE2EServerContentOverrideGate(source, 'storage-recovery-replay');
		await loginToTestAccount(source, log, screenshot);
		await requireActiveRecoveryDiscovery(sourceFrames);
		await startNewChat(source, log);
		stage = 'source-send';
		await sendMessage(source,
			'Show ten synthetic 39C3 events, including past sessions. STORAGE_CAPACITY_SCENARIO:recovery_composite <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-recovery-composite-source');
		const chatId = source.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		stage = 'source-sealed-records';
		await expect.poll(() => distinctEmbeds(sourceFrames, chatId!).length,
			{ timeout: 120_000, message: 'All ten children and their parent must be sealed before source disconnect' })
			.toBe(11);
		const sealedOutputs = distinctEmbeds(sourceFrames, chatId!);
		expect(new Set(sealedOutputs.map((output) => output.subject_id)).size).toBe(11);
		stage = 'source-calendar';
		await requireCalendar(source);
		await origin.close();

		stage = 'recovery-login';
		await focusRecoveryPage(recovered);
		await loginToTestAccount(recovered, log, screenshot);
		await recovered.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
		stage = 'recovery-foreground-lifecycle';
		await requireForegroundRecoveryLifecycle(recoveryFrames);
		stage = 'recovery-record-discovery';
		await expect.poll(() => distinctEmbeds(recoveryFrames, chatId!).map((output) => output.record_id).sort(),
			{ timeout: 180_000, message: 'Fresh client must discover the same eleven sealed composite records' })
			.toEqual(sealedOutputs.map((output) => output.record_id).sort());
		for (const output of sealedOutputs) {
			stage = `recovery-typed-ack:${output.record_id}`;
			await expect.poll(() => recoveryFrames.some((frame: any) => frame.direction === 'sent'
				&& frame.type === 'recovery_output_ack_embed' && frame.payload.record_id === output.record_id
				&& /^[a-f0-9]{64}$/.test(frame.payload.canonical_digest ?? '')),
			{ timeout: 120_000, message: 'Every composite record requires its typed canonical ciphertext acknowledgement' }).toBe(true);
			await expect.poll(() => recoveryFrames.some((frame: any) => frame.direction === 'received'
				&& frame.type === 'recovery_output_embed_acknowledged' && frame.payload.record_id === output.record_id
				&& frame.payload.state === 'ACKNOWLEDGED'), { timeout: 120_000 }).toBe(true);
		}
		const sealedSubjectIds = sealedOutputs.map((output) => output.subject_id);
		let firstChildIds: string[] | undefined;
		for (const reload of [false, true]) {
			stage = reload ? 'reloaded-calendar' : 'recovered-calendar';
			if (reload) await recovered.reload();
			const children = await requireCalendar(recovered);
			const childIds: string[] = [];
			for (let index = 0; index < 10; index += 1) {
				stage = `${reload ? 'reloaded' : 'recovered'}-fullscreen-${index + 1}`;
				const fullscreen = await openFullscreen(recovered, children.nth(index));
				await expect(fullscreen.getByTestId('embed-header-title')).toHaveText(expectedTitles[index]);
				const childId = await recovered.evaluate(() => (window as any).__compositeFullscreenIds.at(-1));
				expect(typeof childId).toBe('string');
				expect(sealedSubjectIds).toContain(childId);
				childIds.push(childId);
				if (index === 0 || index === 9) {
					await screenshot(recovered, `composite-${reload ? 'reloaded' : 'recovered'}-child-${index + 1}-fullscreen`);
				}
				await closeFullscreen(recovered, fullscreen);
			}
			expect(new Set(childIds).size).toBe(10);
			// The same ten authored children leave exactly one sealed parent.
			expect(sealedSubjectIds.filter((id) => !childIds.includes(id))).toHaveLength(1);
			if (reload) expect(childIds).toEqual(firstChildIds);
			else firstChildIds = childIds;
			await screenshot(recovered, reload ? 'composite-calendar-after-reload' : 'composite-calendar-recovered');
		}

		stage = 'completed';
	} finally {
		const diagnostic = { stage, source: summarizeFrames(sourceFrames), recovery: summarizeFrames(recoveryFrames), consoleErrors, canonicalEvents };
		// Keep only identity/status metadata and cap the attachment at 256 KiB.
		while (Buffer.byteLength(JSON.stringify(diagnostic, null, 2)) > 256 * 1024) {
			diagnostic.source.frames = diagnostic.source.frames.slice(Math.ceil(diagnostic.source.frames.length / 2));
			diagnostic.recovery.frames = diagnostic.recovery.frames.slice(Math.ceil(diagnostic.recovery.frames.length / 2));
		}
		try {
			await testInfo.attach('composite-recovery-protocol', {
				body: Buffer.from(JSON.stringify(diagnostic, null, 2)), contentType: 'application/json',
			});
		} finally {
			await destination.close();
			await origin.close().catch(() => undefined);
		}
	}
});
