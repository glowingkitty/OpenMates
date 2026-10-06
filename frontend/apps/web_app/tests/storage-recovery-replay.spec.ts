/* eslint-disable @typescript-eslint/no-require-imports */
/** Signed, provider-free child recovery across a browser disconnect. */
// contract-test-file: infrastructure
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');

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
		for (const { output_kind: kind, record_id: recordId } of discovered) {
			const acknowledgedType = kind === 'message' ? 'recovery_output_persisted' : 'recovery_output_summary_persisted';
			await expect.poll(() => frames.some((frame) => frame.direction === 'received'
				&& frame.type === acknowledgedType && frame.payload.record_id === recordId
				&& frame.payload.state === 'ACKNOWLEDGED'), { timeout: 120_000 }).toBe(true);
		}
		await recovery.reload();
		await expect(recovery.getByTestId('message-assistant').filter({ hasText: 'Synthetic child' }).first())
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
