/* eslint-disable @typescript-eslint/no-require-imports */
/** Signed isolated browser proof for a saved encrypted message code reference. */
export {};

const { test, expect } = require('./console-monitor');
const { createHash } = require('node:crypto');
const { createSignupLogger, createStepScreenshotter, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat, focusMessageEditor } = require('./helpers/chat-test-helpers');

/** Only boolean presence/binding evidence leaves the browser; never expose ciphertext. */
async function inspectSavedBundleState(
	page: any, expected: { chatId: string; messageId: string; embedId: string; userCiphertext: string },
): Promise<Record<string, boolean | string>> {
	return page.evaluate(async ({ chatId, messageId, embedId, userCiphertext }: typeof expected) => {
		const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(embedId));
		const hashedEmbedId = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
		const open = indexedDB.open('chats_db');
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			open.onsuccess = () => resolve(open.result);
			open.onerror = () => reject(open.error);
		});
		try {
			const tx = db.transaction(['messages', 'chats', 'embeds', 'embed_keys'], 'readonly');
			const read = <T>(request: IDBRequest<T>): Promise<T> => new Promise((resolve, reject) => {
				request.onsuccess = () => resolve(request.result);
				request.onerror = () => reject(request.error);
			});
			const [message, chat, head, keys] = await Promise.all([
				read(tx.objectStore('messages').get(messageId)),
				read(tx.objectStore('chats').get(chatId)),
				read(tx.objectStore('embeds').get(`embed:${embedId}`)),
				read(tx.objectStore('embed_keys').index('hashed_embed_id').getAll(hashedEmbedId)),
			]) as [Record<string, any> | undefined, unknown, Record<string, any> | undefined, Array<Record<string, any>>];
			return {
				messagePresent: message?.chat_id === chatId,
				canonicalCipherPresent: message?.encrypted_content === userCiphertext,
				chatPresent: Boolean(chat),
				localHeadPresent: head?.embed_id === embedId && Boolean(head.encrypted_content),
				masterWrapperPresent: keys.some((key) => key.key_type === 'master'),
				chatWrapperPresent: keys.some((key) => key.key_type === 'chat'),
				turnJournalPresent: typeof message?.pending_encrypted_turn_preflight_v1 === 'string',
				turnMarkerPresent: message?.pending_turn_preflight_v1 === 1,
				status: typeof message?.status === 'string' ? message.status : 'missing',
			};
		} finally { db.close(); }
	}, expected);
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,message-input.embeds.gated-send
test('v31 sealed turn journal is indexed when the app upgrades to v32', async ({ page }: { page: any }) => {
	if (process.env.E2E_STORAGE_CAPACITY !== '1') throw new Error('Isolated capacity replay profile is required.');
	if (!getTestAccount().email) throw new Error('Disposable isolated test account is required.');
	test.setTimeout(120_000);
	const log = createSignupLogger('storage-message-journal-upgrade');
	const screenshot = createStepScreenshotter(log);
	await loginToTestAccount(page, log, screenshot);
	// Leave the app document so its v32 connection closes before creating the
	// legacy database. The account key remains in the disposable browser context.
	await page.goto('/robots.txt');
	const seeded = await page.evaluate(async () => {
		type SavedStore = {
			name: string; keyPath: string | string[] | null; autoIncrement: boolean;
			indexes: Array<{ name: string; keyPath: string | string[]; unique: boolean; multiEntry: boolean }>;
			rows: Array<{ key: IDBValidKey; value: unknown }>;
		};
		const previousOpen = indexedDB.open('chats_db');
		const previous = await new Promise<IDBDatabase>((resolve, reject) => {
			previousOpen.onsuccess = () => resolve(previousOpen.result);
			previousOpen.onerror = () => reject(previousOpen.error);
		});
		if (previous.version !== 32) {
			previous.close();
			throw new Error('Disposable account database must start at v32');
		}
		const stores: SavedStore[] = [];
		let rowCount = 0;
		let snapshotBytes = 0;
		try {
			for (const name of Array.from(previous.objectStoreNames)) {
				const tx = previous.transaction(name, 'readonly');
				const source = tx.objectStore(name);
				const saved: SavedStore = {
					name, keyPath: source.keyPath, autoIncrement: source.autoIncrement,
					indexes: Array.from(source.indexNames, (indexName) => {
						const index = source.index(indexName);
						return { name: indexName, keyPath: index.keyPath, unique: index.unique, multiEntry: index.multiEntry };
					}),
					rows: [],
				};
				await new Promise<void>((resolve, reject) => {
					const cursor = source.openCursor();
					cursor.onsuccess = () => {
						const current = cursor.result;
						if (!current) { resolve(); return; }
						rowCount++;
						snapshotBytes += JSON.stringify(current.value, (_, value) =>
							typeof value === 'bigint' ? value.toString() : value)?.length ?? 0;
						if (rowCount > 1000 || snapshotBytes > 16 * 1024 * 1024) {
							reject(new Error('Disposable v31 upgrade snapshot exceeds admission bounds'));
							return;
						}
						saved.rows.push({ key: current.primaryKey, value: current.value });
						current.continue();
					};
					cursor.onerror = () => reject(cursor.error);
				});
				stores.push(saved);
			}
		} finally { previous.close(); }
		const messages = stores.find((store) => store.name === 'messages');
		if (!messages || !messages.indexes.some((index) => index.name === 'pending_turn_created_at_message_id')) {
			throw new Error('Disposable database is missing the production v32 messages schema');
		}
		const remove = indexedDB.deleteDatabase('chats_db');
		await new Promise<void>((resolve, reject) => {
			const timeout = setTimeout(() => reject(new Error('Legacy database deletion remained blocked')), 15_000);
			remove.onsuccess = () => { clearTimeout(timeout); resolve(); };
			remove.onerror = () => { clearTimeout(timeout); reject(remove.error); };
			// Navigation closes the app connection asynchronously. A transient blocked
			// event is not a failed deletion; IDB will resume when it closes.
		});
		const open = indexedDB.open('chats_db', 31);
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			open.onupgradeneeded = () => {
				for (const saved of stores) {
					const store = open.result.createObjectStore(saved.name, {
						...(saved.keyPath === null ? {} : { keyPath: saved.keyPath }),
						autoIncrement: saved.autoIncrement,
					});
					for (const index of saved.indexes) {
						if (saved.name === 'messages' &&
							['status_created_at_message_id', 'pending_turn_created_at_message_id'].includes(index.name)) continue;
						store.createIndex(index.name, index.keyPath, {
							unique: index.unique, multiEntry: index.multiEntry,
						});
					}
				}
			};
			open.onsuccess = () => resolve(open.result);
			open.onerror = () => reject(open.error);
		});
		const row = {
			message_id: crypto.randomUUID(), chat_id: crypto.randomUUID(),
			role: 'user', status: 'synced', created_at: Date.now(),
			encrypted_content: 'sealed-legacy-message',
			pending_encrypted_turn_preflight_v1: 'sealed-legacy-turn',
		};
		await new Promise<void>((resolve, reject) => {
			const tx = db.transaction(stores.map((store) => store.name), 'readwrite');
			for (const saved of stores) {
				const store = tx.objectStore(saved.name);
				for (const record of saved.rows) {
					const value = record.value as Record<string, unknown>;
					if (saved.name === 'messages' && value && typeof value === 'object') {
						delete value.pending_turn_preflight_v1;
					}
					if (saved.keyPath === null) store.put(value, record.key);
					else store.put(value);
				}
			}
			tx.objectStore('messages').put(row);
			tx.oncomplete = () => resolve();
			tx.onerror = () => reject(tx.error);
			tx.onabort = () => reject(tx.error);
		});
		db.close();
		return row.message_id;
	});
	try {
	await page.goto('/');
	await expect.poll(async () => page.evaluate(async () => {
		const open = indexedDB.open('chats_db');
		return new Promise<number>((resolve, reject) => {
			open.onsuccess = () => { const version = open.result.version; open.result.close(); resolve(version); };
			open.onerror = () => reject(open.error);
		});
	}), { timeout: 30_000, message: 'Production chatDB migration must open the legacy database as v32' })
		.toBe(32);
	const result = await page.evaluate(async (messageId: string) => {
		const open = indexedDB.open('chats_db');
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			open.onsuccess = () => resolve(open.result);
			open.onerror = () => reject(open.error);
		});
		try {
			const tx = db.transaction('messages', 'readonly');
			const store = tx.objectStore('messages');
			const indexes = ['status_created_at_message_id', 'pending_turn_created_at_message_id']
				.every((name) => store.indexNames.contains(name));
			const get = store.get(messageId);
			const row = await new Promise<Record<string, any> | undefined>((resolve, reject) => {
				get.onsuccess = () => resolve(get.result);
				get.onerror = () => reject(get.error);
			});
			const range = IDBKeyRange.bound([1, 0, ''], [1, Number.MAX_SAFE_INTEGER, '\uffff']);
			const query = store.index('pending_turn_created_at_message_id').openCursor(range);
			const discovered = await new Promise<boolean>((resolve, reject) => {
				query.onsuccess = () => resolve(query.result?.value?.message_id === messageId);
				query.onerror = () => reject(query.error);
			});
			return { indexes, marker: row?.pending_turn_preflight_v1, journalRetained:
				row?.pending_encrypted_turn_preflight_v1 === 'sealed-legacy-turn', discovered };
		} finally { db.close(); }
	}, seeded);
	expect(result).toEqual({ indexes: true, marker: 1, journalRetained: true, discovered: true });
	} finally {
		await page.evaluate(async (messageId: string) => {
			const open = indexedDB.open('chats_db');
			const db = await new Promise<IDBDatabase>((resolve, reject) => {
				open.onsuccess = () => resolve(open.result);
				open.onerror = () => reject(open.error);
			});
			try {
				await new Promise<void>((resolve, reject) => {
					const tx = db.transaction('messages', 'readwrite');
					tx.objectStore('messages').delete(messageId);
					tx.oncomplete = () => resolve();
					tx.onerror = () => reject(tx.error);
					tx.onabort = () => reject(tx.error);
				});
			} finally { db.close(); }
		}, seeded);
	}
});

// contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,chats.persistence.client-encrypted,storage.validation.synthetic-capacity
test('signed saved code reference persists its complete encrypted bundle', async ({ page }: { page: any }) => {
	if (process.env.E2E_STORAGE_CAPACITY !== '1') throw new Error('Isolated capacity replay profile is required.');
	if (!getTestAccount().email) throw new Error('Disposable isolated test account is required.');
	test.setTimeout(240_000);
	const log = createSignupLogger('storage-capacity-code-reference');
	const screenshot = createStepScreenshotter(log);
	const frames: Array<{ direction: 'sent' | 'received'; type: string; payload: Record<string, any> }> = [];
	page.on('websocket', (socket: any) => {
		for (const [event, direction] of [['framesent', 'sent'], ['framereceived', 'received']] as const) {
			socket.on(event, (frame: any) => {
				try {
					const parsed = JSON.parse(String(frame.payload));
					if (parsed.type === 'chat_turn_preflight' || parsed.type === 'chat_message_confirmed') {
						frames.push({ direction, type: parsed.type, payload: parsed.payload ?? {} });
					}
				} catch { /* Other websocket frames need no inspection. */ }
			});
		}
	});
	await installE2EServerContentOverrideGate(page, 'storage-capacity-code-reference');
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	const editor = page.getByTestId('message-editor').last();
	await expect(editor).toBeVisible();
	await focusMessageEditor(editor);
	await page.keyboard.insertText('Synthetic code reference:\n```js\nconst x = 1;\n```');
	await expect(editor).toContainText('Synthetic code reference:');
	await expect(editor.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'))
		.toBeVisible({ timeout: 20_000 });
	const availabilityPromise = page.waitForResponse((response: any) =>
		response.request().method() === 'POST' &&
		/\/v1\/embeds\/chats\/[^/]+\/references\/availability(?:\?|$)/.test(response.url()),
		{ timeout: 30_000 });
	await sendMessage(page,
		' Synthetic storage reference. STORAGE_CAPACITY_SCENARIO:round <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
		log, screenshot, 'storage-capacity-code-reference', { preserveExistingContent: true });
	const availabilityResponse = await availabilityPromise;
	expect(availabilityResponse.ok(), 'Batch availability lookup must succeed before send').toBe(true);
	const lookup = await availabilityResponse.json();
	expect(lookup.results?.length, 'One fresh code reference should be checked').toBe(1);
	const embedId = lookup.results[0]?.embed_id;
	expect(typeof embedId).toBe('string');
	expect(lookup.results[0]?.state, 'Fresh code reference must be missing before canonical write').toBe('missing');
	const chatId = new URL(page.url()).hash.match(/chat-id=([0-9a-f-]{36})/i)?.[1];
	expect(chatId, 'Saved code turn must have a canonical chat ID').toBeTruthy();
	await expect.poll(() => {
		const preflight = frames.find((frame) => frame.direction === 'sent' && frame.type === 'chat_turn_preflight');
		const bundle = preflight?.payload.inference_request?.encrypted_embeds;
		const entry = Array.isArray(bundle) ? bundle.find((item: any) => item.embed_id === embedId) : null;
		return {
			matching: Array.isArray(bundle) && bundle.length === 1 && Boolean(entry),
			encrypted: Boolean(entry?.encrypted_type && entry?.encrypted_content),
			noPlaintext: entry?.content === undefined && entry?.type === undefined,
			wrappers: Array.isArray(entry?.embed_keys)
				? entry.embed_keys.map((key: any) => key.key_type).sort().join(',') : '',
			wrapped: Array.isArray(entry?.embed_keys) && entry.embed_keys.length === 2 &&
				entry.embed_keys.every((key: any) => typeof key.encrypted_embed_key === 'string' && key.encrypted_embed_key.length > 0),
			confirmed: frames.some((frame) => frame.direction === 'received' &&
				frame.type === 'chat_message_confirmed' &&
				frame.payload.message_id === preflight?.payload.message_id),
		};
	}, { timeout: 30_000, message: 'Preflight must carry one sealed code bundle with master/chat wrappers and a canonical confirmation' })
		.toEqual({ matching: true, encrypted: true, noPlaintext: true,
			wrappers: 'chat,master', wrapped: true, confirmed: true });
	await expect.poll(async () => {
		const response = await page.request.post(availabilityResponse.url(), { data: { embed_ids: [embedId] } });
		if (!response.ok()) return 'lookup_failed';
		const result = await response.json();
		return result.results?.[0]?.embed_id === embedId ? result.results[0].state : 'wrong_identity';
	}, { timeout: 30_000, message: 'Canonical encrypted code bundle must become ready after confirmation' })
		.toBe('ready');
	await page.reload();
	const acceptedPreflight = frames.find((frame) =>
		frame.direction === 'sent' && frame.type === 'chat_turn_preflight');
	const canonicalMarkdown = acceptedPreflight?.payload.inference_request?.message?.content;
	const referenceBlocks = typeof canonicalMarkdown === 'string'
		? Array.from(canonicalMarkdown.matchAll(/```json\n([\s\S]*?)\n```/g), (match) => {
			try { return JSON.parse(match[1]); } catch { return null; }
		}) : [];
	expect(referenceBlocks.filter((ref: any) => ref?.type === 'code' && ref?.embed_id === embedId),
		'The canonical user markdown must contain the same parseable code reference as its sealed bundle')
		.toHaveLength(1);
	const savedState = await inspectSavedBundleState(page, {
		chatId: chatId!, messageId: acceptedPreflight?.payload.message_id,
		embedId, userCiphertext: acceptedPreflight?.payload.encrypted_user_message?.encrypted_content,
	});
	expect({
		messagePresent: savedState.messagePresent,
		canonicalCipherPresent: savedState.canonicalCipherPresent,
		localHeadPresent: savedState.localHeadPresent,
		masterWrapperPresent: savedState.masterWrapperPresent,
		chatWrapperPresent: savedState.chatWrapperPresent,
	}, 'Saved message and local embed must retain the exact canonical ciphertext and key bindings after reload')
		.toEqual({ messagePresent: true, canonicalCipherPresent: true, localHeadPresent: true,
			masterWrapperPresent: true, chatWrapperPresent: true });
	const canonicalUserBubble = page.locator(`[data-testid="message-user"][data-message-id="${acceptedPreflight?.payload.message_id}"]`);
	await expect(canonicalUserBubble,
		'The rendered user row must be the exact canonically encrypted preflight message')
		.toBeVisible({ timeout: 30_000 });
	try {
		await expect(canonicalUserBubble
			.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'))
			.toBeVisible({ timeout: 30_000 });
	} finally {
		const nodeState = await canonicalUserBubble.evaluate((bubble: Element) => ({
			anyEmbedNodes: bubble.querySelectorAll('[data-type="embed"], [data-embed-id]').length > 0,
			codeEmbedNodes: bubble.querySelectorAll('[data-embed-type="code-code"]').length > 0,
			protocolTextVisible: /"embed_id"/.test(bubble.textContent ?? ''),
		})).catch(() => ({ anyEmbedNodes: false, codeEmbedNodes: false, protocolTextVisible: false }));
		console.log('bounded saved-code render state', nodeState);
	}
	await deleteActiveChat(page, log, screenshot, 'storage-capacity-code-reference');
});

// contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send,chats.persistence.client-encrypted,chats.message.identity-idempotent,storage.validation.synthetic-capacity
test('interrupted code bundle preflight replays the same encrypted turn after reload', async ({ page }: { page: any }) => {
	if (process.env.E2E_STORAGE_CAPACITY !== '1') throw new Error('Isolated capacity replay profile is required.');
	if (!getTestAccount().email) throw new Error('Disposable isolated test account is required.');
	test.setTimeout(300_000);
	const log = createSignupLogger('storage-capacity-code-restart');
	const screenshot = createStepScreenshotter(log);
	type SealedTurn = {
		chatId: string;
		messageId: string;
		turnId: string;
		embedId: string;
		userCiphertext: string;
		userCipherDigest: string;
		bundleDigest: string;
		inferenceDigest: string;
		preflightDigest: string;
		bundleComplete: boolean;
	};
	const digest = (value: unknown): string => createHash('sha256').update(JSON.stringify(value)).digest('hex');
	const sealedTurn = (payload: Record<string, any>): SealedTurn | null => {
		const bundle = payload.inference_request?.encrypted_embeds;
		if (!Array.isArray(bundle) || bundle.length !== 1 ||
			typeof payload.encrypted_user_message?.encrypted_content !== 'string' ||
			!payload.inference_request) return null;
		const entry = bundle[0];
		return {
			chatId: payload.chat_id,
			messageId: payload.message_id,
			turnId: payload.turn_id,
			embedId: entry.embed_id,
			userCiphertext: payload.encrypted_user_message.encrypted_content,
			userCipherDigest: digest(payload.encrypted_user_message?.encrypted_content),
			bundleDigest: digest(bundle),
			inferenceDigest: digest(payload.inference_request),
			preflightDigest: digest(payload),
			bundleComplete: Boolean(entry.encrypted_type && entry.encrypted_content &&
				Array.isArray(entry.embed_keys) && entry.embed_keys.length === 2 &&
				entry.embed_keys.map((key: any) => key.key_type).sort().join(',') === 'chat,master' &&
				entry.embed_keys.every((key: any) => typeof key.encrypted_embed_key === 'string' &&
					key.encrypted_embed_key.length > 0)),
		};
	};
	const attempts: SealedTurn[] = [];
	const confirmations: string[] = [];
	let completedSyncFrames = 0;
	let dropped = false;
	await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, (socket: any) => {
		const server = socket.connectToServer();
		socket.onMessage((raw: unknown) => {
			let frame: { type?: string; payload?: Record<string, any> } | null = null;
			try { frame = JSON.parse(String(raw)); } catch { /* Forward binary frames unchanged. */ }
			if (frame?.type === 'chat_turn_preflight') {
				const summary = sealedTurn(frame.payload ?? {});
				if (summary) attempts.push(summary);
				if (!dropped) {
					dropped = true;
					return; // The server has not committed this preflight.
				}
			}
			server.send(raw);
		});
		server.onMessage((raw: unknown) => {
			try {
				const frame = JSON.parse(String(raw));
				if (frame.type === 'phased_sync_complete') completedSyncFrames++;
				if (frame.type === 'chat_message_confirmed' &&
					typeof frame.payload?.message_id === 'string') confirmations.push(frame.payload.message_id);
			} catch { /* Forward binary frames unchanged. */ }
			socket.send(raw);
		});
	});
	await installE2EServerContentOverrideGate(page, 'storage-capacity-code-restart');
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	const editor = page.getByTestId('message-editor').last();
	await expect(editor).toBeVisible();
	await focusMessageEditor(editor);
	await page.keyboard.insertText('Synthetic restart code:\n```js\nconst restart = 1;\n```');
	await expect(editor.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'))
		.toBeVisible({ timeout: 20_000 });
	const availabilityPromise = page.waitForResponse((response: any) =>
		response.request().method() === 'POST' &&
		/\/v1\/embeds\/chats\/[^/]+\/references\/availability(?:\?|$)/.test(response.url()),
		{ timeout: 30_000 });
	// sendMessage waits for canonical acceptance. Keep its promise observed while
	// this test deliberately withholds the first preflight acknowledgement.
	const firstSend = sendMessage(page,
		' Synthetic retry. STORAGE_CAPACITY_SCENARIO:round <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
		log, screenshot, 'storage-capacity-code-restart', { preserveExistingContent: true })
		.then(() => undefined, () => undefined);
	const availabilityResponse = await availabilityPromise;
	expect(availabilityResponse.ok(), 'Availability lookup must complete before preflight').toBe(true);
	const lookup = await availabilityResponse.json();
	await expect.poll(() => attempts.length, {
		timeout: 30_000, message: 'First sealed preflight must reach the blocked WebSocket route',
	}).toBe(1);
	const original = attempts[0];
	expect({
		identity: Boolean(original.chatId && original.messageId && original.turnId && original.embedId),
		bundleComplete: original.bundleComplete,
		missingBeforeCommit: lookup.results?.length === 1 &&
			lookup.results[0]?.embed_id === original.embedId && lookup.results[0]?.state === 'missing',
		unconfirmed: confirmations.length === 0,
	}).toEqual({ identity: true, bundleComplete: true, missingBeforeCommit: true, unconfirmed: true });
	const beforeReload = await inspectSavedBundleState(page, {
		chatId: original.chatId, messageId: original.messageId,
		embedId: original.embedId, userCiphertext: original.userCiphertext,
	});
	expect({ messagePresent: beforeReload.messagePresent, canonicalCipherPresent: beforeReload.canonicalCipherPresent,
		chatPresent: beforeReload.chatPresent, localHeadPresent: beforeReload.localHeadPresent,
		masterWrapperPresent: beforeReload.masterWrapperPresent, chatWrapperPresent: beforeReload.chatWrapperPresent,
		turnJournalPresent: beforeReload.turnJournalPresent, turnMarkerPresent: beforeReload.turnMarkerPresent,
	}, 'Dropped preflight must leave the complete exact artifact in the disposable browser')
		.toEqual({ messagePresent: true, canonicalCipherPresent: true, chatPresent: true, localHeadPresent: true,
			masterWrapperPresent: true, chatWrapperPresent: true, turnJournalPresent: true, turnMarkerPresent: true });
	// A full reload clears the EmbedStore and chat-key memory caches, while
	// retaining the encrypted message, bundle, key wrappers, and turn journal in IDB.
	await page.reload({ waitUntil: 'domcontentloaded' });
	try {
		await expect.poll(() => attempts.length, {
			timeout: 90_000, message: 'Reconnect must replay the pending message from durable local state',
		}).toBeGreaterThanOrEqual(2);
	} finally {
		const afterReload = await inspectSavedBundleState(page, {
			chatId: original.chatId, messageId: original.messageId,
			embedId: original.embedId, userCiphertext: original.userCiphertext,
		});
		console.log('bounded interrupted-preflight state', {
			...afterReload, completedSyncFrames, replayedPreflightCount: attempts.length,
		});
	}
	const retried = attempts[1];
	expect({
		identity: retried.chatId === original.chatId &&
			retried.messageId === original.messageId &&
			retried.turnId === original.turnId &&
			retried.embedId === original.embedId,
		userCipher: retried.userCipherDigest === original.userCipherDigest,
		bundle: retried.bundleDigest === original.bundleDigest && retried.bundleComplete,
		inference: retried.inferenceDigest === original.inferenceDigest,
		preflight: retried.preflightDigest === original.preflightDigest,
	}).toEqual({ identity: true, userCipher: true, bundle: true, inference: true, preflight: true });
	await expect.poll(() => confirmations.filter((id) => id === original.messageId).length, {
		timeout: 45_000, message: 'Retried preflight must receive canonical user confirmation',
	}).toBe(1);
	await expect.poll(async () => {
		const response = await page.request.post(availabilityResponse.url(), {
			data: { embed_ids: [original.embedId] },
		});
		if (!response.ok()) return 'lookup_failed';
		const result = await response.json();
		return result.results?.[0]?.embed_id === original.embedId
			? result.results[0].state : 'wrong_identity';
	}, { timeout: 30_000, message: 'Retried preflight must persist the same encrypted embed head and wrappers' })
		.toBe('ready');
	const messageWindowUrl = new URL(
		`/v1/chats/${encodeURIComponent(original.chatId)}/messages/window?direction=latest&limit=20`,
		availabilityResponse.url(),
	).toString();
	await expect.poll(async () => {
		const response = await page.request.get(messageWindowUrl);
		if (!response.ok()) return { savedOnce: false, sameCipher: false };
		const window = await response.json();
		const rows = (window.messages ?? []).filter((row: any) => row.message_id === original.messageId);
		return {
			savedOnce: rows.length === 1 && rows[0].role === 'user',
			sameCipher: rows.length === 1 &&
				digest(rows[0].encrypted_content) === original.userCipherDigest,
		};
	}, { timeout: 30_000, message: 'The bounded canonical window must contain one exact user ciphertext row' })
		.toEqual({ savedOnce: true, sameCipher: true });
	await expect(page.getByTestId('message-user').last()
		.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'))
		.toBeVisible({ timeout: 30_000 });
	await firstSend;
	await deleteActiveChat(page, log, screenshot, 'storage-capacity-code-restart');
});
