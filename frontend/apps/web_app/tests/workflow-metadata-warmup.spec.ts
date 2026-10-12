/* eslint-disable @typescript-eslint/no-require-imports */
/** First-party composer hint and authenticated WebSocket warmup boundary. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials, skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady, focusMessageEditor, startNewChat,
	sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');

const { email, password, otpKey } = getTestAccount();
type WarmupFrame = { type: string; payload: Record<string, unknown> };

test.describe('Chat metadata warmup WebSocket contract', () => {
	test.setTimeout(180_000);
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: direct surface=gui.web assertions=workflows.chat.metadata-warmup
	test('focus sends one draft-free hint and the server enforces auth, Team and rate boundaries', async ({ page, browser }: { page: any; browser: any }) => {
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		const sentHints: WarmupFrame[] = [];
		let applicationSocketUrl: string | null = null;
		page.on('websocket', (socket: any) => {
			if (!new URL(socket.url()).pathname.endsWith('/v1/ws')) return;
			applicationSocketUrl = socket.url();
			socket.on('framesent', (frame: { payload?: string }) => {
				try {
					const message = JSON.parse(String(frame.payload || ''));
					if (message.type === 'chat_metadata_warmup') sentHints.push(message);
				} catch { /* WebSocket control frame. */ }
			});
		});

		await loginToTestAccount(page);
		await waitForChatReady(page);
		await expect.poll(() => applicationSocketUrl).not.toBeNull();
		const editor = page.getByTestId('message-editor');
		const editable = editor.locator('[contenteditable="true"]').first();
		await focusMessageEditor(editor);
		await expect.poll(() => sentHints.length).toBe(1);
		await expect(editor).toBeVisible();
		await editable.fill('Private draft text that must stay in the browser');
		await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
		await focusMessageEditor(editor);
		await page.waitForTimeout(300); // The focus send is immediate; observe the dedupe window.
		expect(sentHints).toHaveLength(1);
		const { _traceparent, ...hintFields } = sentHints[0].payload;
		expect(hintFields).toEqual({});
		if (_traceparent !== undefined) {
			expect(_traceparent).toMatch(/^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$/);
		}
		expect(JSON.stringify(sentHints)).not.toContain('Private draft text');
		await editable.fill('');

		const authenticatedUrl = applicationSocketUrl as string;
		const authenticated = await page.evaluate(async (url: string) => {
			const openSocket = () => new Promise<WebSocket>((resolve, reject) => {
				const dedicatedUrl = new URL(url);
				// Each connection needs its own sessionId so it cannot replace the app socket.
				dedicatedUrl.searchParams.set('sessionId', `workflow-warmup-${crypto.randomUUID()}`);
				const socket = new WebSocket(dedicatedUrl);
				socket.addEventListener('open', () => resolve(socket), { once: true });
				socket.addEventListener('error', () => reject(new Error('Authenticated WebSocket did not open')), { once: true });
			});
			const request = (socket: WebSocket, payload: Record<string, unknown>, type = 'chat_metadata_warmup') =>
				new Promise<string[]>((resolve, reject) => {
					const statuses: string[] = [];
					const timeout = setTimeout(() => { socket.removeEventListener('message', receive); reject(new Error('Warmup result timed out')); }, 20_000);
					function receive(event: MessageEvent) {
						let message: WarmupFrame;
						try { message = JSON.parse(String(event.data)); } catch { return; }
						if (message.type !== `${type}_result`) return;
						const status = message.payload?.status;
						if (typeof status !== 'string') return;
						statuses.push(status);
						if (status === 'accepted') return;
						clearTimeout(timeout);
						socket.removeEventListener('message', receive);
						resolve(statuses);
					}
					socket.addEventListener('message', receive);
					socket.send(JSON.stringify({ type, payload }));
				});
			const forbiddenSocket = await openSocket();
			try {
				const forbidden = await request(forbiddenSocket, { team_id: '00000000-0000-4000-8000-000000000001' });
				const personalSocket = await openSocket();
				try {
					const personal = [];
					for (let index = 0; index < 4; index += 1) personal.push(await request(personalSocket, {}));
					const legacySocket = await openSocket();
					try {
						const legacy = await request(legacySocket, {}, 'workflow_metadata_warmup');
						return { forbidden, personal, legacy };
					} finally { legacySocket.close(); }
				} finally { personalSocket.close(); }
			} finally { forbiddenSocket.close(); }
		}, authenticatedUrl);
		expect(authenticated.forbidden).toEqual(['accepted', 'forbidden']);
		for (const result of authenticated.personal.slice(0, 3)) {
			expect(result[0]).toBe('accepted');
			expect(['ready', 'in_progress']).toContain(result[1]);
		}
		expect(authenticated.personal[3]).toEqual(['rate_limited']);
		expect(authenticated.legacy[0]).toBe('accepted');
		expect(['ready', 'in_progress']).toContain(authenticated.legacy[1]);

		const guestContext = await browser.newContext();
		try {
			const guestPage = await guestContext.newPage();
			await guestPage.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			const rejected = await guestPage.evaluate(async (observedUrl: string) => {
				const url = new URL(observedUrl);
				url.searchParams.delete('token');
				url.searchParams.set('sessionId', 'unauthenticated-workflow-warmup');
				return new Promise<{ opened: boolean; closeCode: number }>((resolve) => {
					const socket = new WebSocket(url);
					let opened = false;
					const timeout = setTimeout(() => { socket.close(); resolve({ opened, closeCode: 0 }); }, 10_000);
					socket.addEventListener('open', () => {
						opened = true;
						socket.send(JSON.stringify({ type: 'chat_metadata_warmup', payload: {} }));
					});
					socket.addEventListener('close', (event) => { clearTimeout(timeout); resolve({ opened, closeCode: event.code }); });
				});
			}, authenticatedUrl);
			expect(rejected.opened).toBe(false);
			expect([1008, 1006]).toContain(rejected.closeCode);
		} finally { await guestContext.close(); }
	});

	// contract-test: direct surface=gui.web assertions=message-input.send.ownership,chat-processing-feedback.selection-after-acceptance
	test('first personal text turn admits once before connected-account discovery finishes', async ({ page }: { page: any }, testInfo: any) => {
		// Observe real protocol frames without changing or delaying the socket.
		const queueWire: Array<{ socket: number; at: number; type: string; chatId: string; uncertain?: boolean; capabilities?: string[]; phase?: string; contextFields?: string[] }> = [];
		let socketCount = 0;
		page.on('websocket', (socket: any) => {
			if (!new URL(socket.url()).pathname.endsWith('/v1/ws')) return;
			const socketIndex = ++socketCount;
			for (const eventName of ['framesent', 'framereceived']) {
				socket.on(eventName, (frame: { payload?: string }) => {
					try {
						const envelope = JSON.parse(String(frame.payload || ''));
						const type = envelope.type;
					if (!['server_capabilities', 'chat_turn_admit', 'chat_turn_context_ready', 'chat_message_added',
						'chat_turn_preflight', 'get_queued_messages', 'queued_messages_snapshot',
							'request_chat_content_batch'].includes(type)) return;
						const payload = envelope.payload ?? {};
						if (type === 'server_capabilities' && eventName === 'framereceived') {
							queueWire.push({ socket: socketIndex, at: Date.now(), type, chatId: '',
								capabilities: Array.isArray(payload.capabilities) ? payload.capabilities : [] });
							return;
						}
						const chatId = typeof payload.chat_id === 'string' ? payload.chat_id : '';
						if (type === 'request_chat_content_batch') {
							for (const id of payload.chat_ids ?? []) {
								if (typeof id === 'string') queueWire.push({ socket: socketIndex, at: Date.now(), type, chatId: id });
							}
						} else if (chatId) {
							queueWire.push({ socket: socketIndex, at: Date.now(), type, chatId,
								...(type === 'chat_turn_context_ready' ? {
									phase: typeof payload.phase === 'string' ? payload.phase : '',
									contextFields: payload.context && typeof payload.context === 'object'
										? Object.keys(payload.context).sort() : [],
								} : {}),
								...(type === 'queued_messages_snapshot' ? { uncertain: payload.uncertain === true } : {}) });
						}
					} catch { /* WebSocket control frame. */ }
				});
			}
		});
		// The isolated self-hosted CI stack has no provider key. Mock inference still
		// travels through the real send protocol, so only lift the public UI gate.
		await page.route('**/v1/settings/server-status', async (route: any) => {
			const response = await route.fetch();
			if (!response.ok()) throw new Error(`Server status failed (${response.status()}).`);
			const status = await response.json();
			await route.fulfill({ response, json: { ...status, ai_models_configured: true } });
		});
		await loginToTestAccount(page);
		await waitForChatReady(page);
		await expect.poll(() => page.evaluate(async () => {
			const state = await (window as any).__openmatesE2EChatConnectionState?.();
			return state?.online === true && state?.websocketConnected === true
				&& state?.cachePrimed === true && state?.contextSyncCompleted === true
				&& state?.teamContextActive === false;
		}), { timeout: 45_000 }).toBe(true);
		await page.evaluate(() => {
			sessionStorage.setItem('openmates:send-prep-timing', '1');
			(window as any).__openmatesSendPrepPhases = [];
			(window as any).__sendPrepLoadingNoticeSeen = false;
			const loadingNotice = 'Model selection is still loading. Send again in a moment.';
			new MutationObserver(() => {
				if ([...document.querySelectorAll('[data-testid="notification"]')]
					.some((item) => item.textContent?.includes(loadingNotice))) {
					(window as any).__sendPrepLoadingNoticeSeen = true;
				}
			}).observe(document.body, { childList: true, subtree: true, characterData: true });
		});
		let lookupRequests = 0;
		let admitBeforeDirectoryContinue = false;
		let directoryResponse: { status: number; rowsArray: boolean; rowCount: number } | null = null;
		const directoryPath = /\/v1\/connected-accounts(?:\?.*)?$/;
		await page.route(directoryPath, async (route: any) => {
			if (route.request().method() !== 'GET') return route.continue();
			lookupRequests += 1;
			if (lookupRequests === 1) {
				admitBeforeDirectoryContinue = await expect.poll(() =>
					queueWire.some((frame) => frame.type === 'chat_turn_admit'),
					{ timeout: 15_000 }).toBe(true).then(() => true).catch(() => false);
			}
			await route.continue();
		});
		page.on('response', (response: any) => {
			if (response.request().method() !== 'GET' || !directoryPath.test(response.url())) return;
			void response.json().then((payload: { rows?: unknown }) => {
				directoryResponse = {
					status: response.status(), rowsArray: Array.isArray(payload.rows),
					rowCount: Array.isArray(payload.rows) ? payload.rows.length : -1,
				};
			}).catch(() => { directoryResponse = { status: response.status(), rowsArray: false, rowCount: -1 }; });
		});
		await startNewChat(page);
		await waitForChatReady(page);
		await expect(page.getByTestId('message-user')).toHaveCount(0);
		try {
			await sendMessage(page, withMockMarker('Capital of Germany?', 'chat_flow_capital', 'instant'));
			await waitForAssistantMessage(page, { contains: 'Berlin', timeout: 60_000 });
			await expect(page.getByTestId('message-user')).toHaveCount(1);
			await expect(page.getByTestId('message-editor').last()).toHaveText('');
			await expect.poll(() => page.evaluate(() =>
				((window as any).__openmatesSendPrepPhases ?? []).some((entry: { phase: string }) =>
					entry.phase === 'connected_context_ready')),
			{ timeout: 15_000 }).toBe(true);
			const phases = await page.evaluate(() =>
				((window as any).__openmatesSendPrepPhases ?? []).map((entry: { phase: string }) => entry.phase));
			const sendBegin = await page.evaluate(() => {
				const entry = ((window as any).__openmatesSendPrepPhases ?? [])
					.find((item: { phase: string }) => item.phase === 'connected_context_begin');
				return entry ? performance.timeOrigin + entry.ms : null;
			});
			const userFrame = queueWire.find((frame) => frame.type === 'chat_turn_admit');
			const overlappingUncertain = userFrame && sendBegin !== null
				? queueWire.filter((frame) => frame.type === 'queued_messages_snapshot' && frame.uncertain
					&& frame.chatId === userFrame.chatId && frame.socket === userFrame.socket
					&& frame.at >= sendBegin && frame.at < userFrame.at)
				: [];
			const prematureHistory = userFrame && overlappingUncertain.length
				? queueWire.filter((frame) => frame.type === 'request_chat_content_batch'
					&& frame.chatId === userFrame.chatId && frame.socket === userFrame.socket
					&& frame.at >= overlappingUncertain[0].at && frame.at < userFrame.at)
				: [];
			await testInfo.attach('queue-snapshot-send-order', {
				body: JSON.stringify({ userFrameObserved: !!userFrame, overlappingUncertain: overlappingUncertain.length,
					prematureHistory: prematureHistory.length }),
				contentType: 'application/json',
			});
			expect(userFrame).toBeDefined();
			expect(queueWire.some((frame) => frame.type === 'server_capabilities'
				&& frame.socket === userFrame?.socket && frame.at <= userFrame.at
				&& frame.capabilities?.includes('chat_turn_admit_v1')
				&& frame.capabilities?.includes('chat_turn_context_v1'))).toBe(true);
			const v2Capability = queueWire.some((frame) => frame.type === 'server_capabilities'
				&& frame.socket === userFrame?.socket && frame.at <= userFrame.at
				&& frame.capabilities?.includes('chat_turn_context_selection_details_v2'));
			if (v2Capability) {
				await expect.poll(() => queueWire.filter((frame) => frame.type === 'chat_turn_context_ready'
					&& frame.chatId === userFrame?.chatId && frame.socket === userFrame?.socket).length,
				{ timeout: 15_000 }).toBeGreaterThanOrEqual(2);
				const contextFrames = queueWire.filter((frame) => frame.type === 'chat_turn_context_ready'
					&& frame.chatId === userFrame?.chatId && frame.socket === userFrame?.socket);
				const routing = contextFrames.find((frame) => frame.phase === 'routing');
				const details = contextFrames.find((frame) => frame.phase === 'details');
				expect(routing?.contextFields).toEqual(['project_focus_candidates']);
				expect(details?.contextFields).toEqual(expect.arrayContaining([
					'connected_account_directory', 'connected_account_token_refs',
					'custom_memory_documents', 'project_context_documents', 'project_focus_catalog',
					'project_focus_documents', 'related_task_candidates',
				]));
				expect(routing!.at).toBeLessThanOrEqual(details!.at);
			}
			expect(queueWire.filter((frame) => frame.chatId === userFrame?.chatId
				&& ['chat_turn_admit', 'chat_turn_preflight', 'chat_message_added'].includes(frame.type))
			).toHaveLength(1);
			expect(prematureHistory).toHaveLength(0);
			expect(admitBeforeDirectoryContinue).toBe(true);
			await expect.poll(() => directoryResponse, { timeout: 15_000 }).not.toBeNull();
			expect(directoryResponse).toEqual({ status: 200, rowsArray: true, rowCount: 0 });
			expect(lookupRequests).toBeGreaterThanOrEqual(1);
			expect(phases.indexOf('connected_lookup_started')).toBeGreaterThanOrEqual(0);
			expect(phases.indexOf('connected_lookup_started')).toBeLessThan(phases.indexOf('local_message_ready'));
			expect(phases.indexOf('local_message_ready')).toBeLessThan(phases.indexOf('user_frame_dispatched'));
			expect(phases.indexOf('user_frame_dispatched')).toBeLessThan(phases.indexOf('connected_lookup_ready'));
			expect(await page.evaluate(() => (window as any).__sendPrepLoadingNoticeSeen)).toBe(false);
		} catch (error) {
			const diagnostics = await page.evaluate(() => ({
				phases: ((window as any).__openmatesSendPrepPhases ?? []).map((entry: { phase: string; ms: number }) => entry),
				sendStep: (window as any).__openmatesLastSendDebug?.step ?? null,
				preflightStep: (window as any).__openmatesLastPreflightDebug?.step ?? null,
				loadingNoticeSeen: (window as any).__sendPrepLoadingNoticeSeen ?? false,
				userCount: document.querySelectorAll('[data-testid="message-user"]').length,
				lastUserStatus: [...document.querySelectorAll('[data-testid="message-user"]')].at(-1)?.getAttribute('data-status') ?? null,
			})).catch(() => null);
			await testInfo.attach('connected-lookup-overlap-diagnostics', {
				body: JSON.stringify({ diagnostics, lookupRequests, admitBeforeDirectoryContinue, directoryResponse }),
				contentType: 'application/json',
			});
			throw error;
		} finally {
			await page.unroute(directoryPath);
			await deleteActiveChat(page);
		}
	});
});
