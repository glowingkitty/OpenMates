/* eslint-disable @typescript-eslint/no-require-imports */
/** First-party composer hint and authenticated WebSocket warmup boundary. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials, skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady, focusMessageEditor } = require('./helpers/chat-test-helpers');

const { email, password, otpKey } = getTestAccount();
type WarmupFrame = { type: string; payload: Record<string, unknown> };

test.describe('Workflow metadata warmup WebSocket contract', () => {
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
					if (message.type === 'workflow_metadata_warmup') sentHints.push(message);
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
			const request = (socket: WebSocket, payload: Record<string, unknown>) =>
				new Promise<string[]>((resolve, reject) => {
					const statuses: string[] = [];
					const timeout = setTimeout(() => { socket.removeEventListener('message', receive); reject(new Error('Warmup result timed out')); }, 20_000);
					function receive(event: MessageEvent) {
						let message: WarmupFrame;
						try { message = JSON.parse(String(event.data)); } catch { return; }
						if (message.type !== 'workflow_metadata_warmup_result') return;
						const status = message.payload?.status;
						if (typeof status !== 'string') return;
						statuses.push(status);
						if (status === 'accepted') return;
						clearTimeout(timeout);
						socket.removeEventListener('message', receive);
						resolve(statuses);
					}
					socket.addEventListener('message', receive);
					socket.send(JSON.stringify({ type: 'workflow_metadata_warmup', payload }));
				});
			const forbiddenSocket = await openSocket();
			try {
				const forbidden = await request(forbiddenSocket, { team_id: '00000000-0000-4000-8000-000000000001' });
				const personalSocket = await openSocket();
				try {
					const personal = [];
					for (let index = 0; index < 4; index += 1) personal.push(await request(personalSocket, {}));
					return { forbidden, personal };
				} finally { personalSocket.close(); }
			} finally { forbiddenSocket.close(); }
		}, authenticatedUrl);
		expect(authenticated.forbidden).toEqual(['accepted', 'forbidden']);
		for (const result of authenticated.personal.slice(0, 3)) {
			expect(result[0]).toBe('accepted');
			expect(['ready', 'in_progress']).toContain(result[1]);
		}
		expect(authenticated.personal[3]).toEqual(['rate_limited']);

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
						socket.send(JSON.stringify({ type: 'workflow_metadata_warmup', payload: {} }));
					});
					socket.addEventListener('close', (event) => { clearTimeout(timeout); resolve({ opened, closeCode: event.code }); });
				});
			}, authenticatedUrl);
			expect(rejected.opened).toBe(false);
			expect([1008, 1006]).toContain(rejected.closeCode);
		} finally { await guestContext.close(); }
	});
});
