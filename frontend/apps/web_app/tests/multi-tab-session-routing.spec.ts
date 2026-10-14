/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { chromium } = require('@playwright/test');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// contract-test: direct surface=gui.web assertions=auth.session.lifecycle,auth.session.isolation
test('cloned auth storage gives three tabs independent WebSocket routes', async () => {
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const browser = await chromium.launch();
	const context = await browser.newContext({ baseURL });
	const installProbe = async (page: any, copiedSessionId?: string) => {
		await page.addInitScript((sessionId: string | undefined) => {
			if (sessionId) sessionStorage.setItem('session_id', sessionId);
			const NativeWebSocket = window.WebSocket;
			(window as any).__webSocketRouteProbe = { routeIds: [] as string[], socket: null as WebSocket | null };
			window.WebSocket = new Proxy(NativeWebSocket, {
				construct(target, args, newTarget) {
					const socket = Reflect.construct(target, args, newTarget) as WebSocket;
					const url = new URL(String(args[0]));
					if (url.pathname.endsWith('/v1/ws')) {
						const probe = (window as any).__webSocketRouteProbe;
						probe.routeIds.push(url.searchParams.get('sessionId'));
						probe.socket = socket;
					}
					return socket;
				}
			});
		}, copiedSessionId);
	};
	const routedId = async (page: any): Promise<string> => {
		await expect.poll(() => page.evaluate(() => {
			const probe = (window as any).__webSocketRouteProbe;
			return probe?.socket?.readyState === WebSocket.OPEN ? probe.routeIds.at(-1) : null;
		}), { timeout: 30000 }).not.toBeNull();
		return page.evaluate(() => (window as any).__webSocketRouteProbe.routeIds.at(-1));
	};
	// The existing read-only settings request is answered through
	// ConnectionManager.send_personal_message for this specific socket route.
	const readOnlyRouteRequest = async (page: any, requestId: string) => page.evaluate((id: string) => new Promise<void>((resolve, reject) => {
		const socket = (window as any).__webSocketRouteProbe.socket as WebSocket;
		const timer = window.setTimeout(() => { socket.removeEventListener('message', onMessage); reject(new Error('Routed settings response missing')); }, 15000);
		const onMessage = (event: MessageEvent) => {
			let frame: { type?: string; payload?: { request_id?: string } };
			try { frame = JSON.parse(String(event.data)); } catch { return; }
			if (frame.payload?.request_id !== id) return;
			window.clearTimeout(timer);
			socket.removeEventListener('message', onMessage);
			if (frame.type === 'email_notification_settings_snapshot') resolve();
			else reject(new Error(`Settings read failed: ${frame.type ?? 'unknown'}`));
		};
		socket.addEventListener('message', onMessage);
		socket.send(JSON.stringify({ type: 'email_notification_settings_get', payload: { request_id: id } }));
	}), requestId);

	try {
		const first = await context.newPage();
		await installProbe(first);
		await loginToTestAccount(first, () => {});
		const copiedSessionId = await first.evaluate(() => sessionStorage.getItem('session_id'));
		expect(copiedSessionId).toBeTruthy();

		const siblings = [];
		for (let index = 0; index < 2; index++) {
			const tab = await context.newPage();
			await installProbe(tab, copiedSessionId!);
			await tab.goto(getE2EDebugUrl('/'));
			await expect(tab.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 15000 });
			siblings.push(tab);
		}
		const tabs = [first, ...siblings];
		const routeIds = await Promise.all(tabs.map(routedId));
		expect(new Set(routeIds).size).toBe(3);
		for (const [index, tab] of tabs.entries()) {
			expect(await tab.evaluate(() => sessionStorage.getItem('session_id'))).toBe(copiedSessionId);
			await readOnlyRouteRequest(tab, `cloned-tab-route-${index}`);
		}
	} finally {
		await context.close();
		await browser.close();
	}
});
