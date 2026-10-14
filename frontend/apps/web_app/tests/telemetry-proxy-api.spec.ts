/**
 * frontend/apps/web_app/tests/telemetry-proxy-api.spec.ts
 *
 * Isolated HTTP smoke coverage for socket cancellation, proxy availability,
 * authentication, and the unchanged IP quota. The collector is absent here.
 * Deterministic ASGI unit coverage and isolated API log inspection establish
 * whether interrupted body reads are handled without an uncaught exception.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

import type { Page } from '@playwright/test';
const { test, expect } = require('@playwright/test');
const net = require('node:net');
const tls = require('node:tls');
const { workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { getTestAccount } = require('./signup-flow-helpers');

async function expectBrowserSessionRole(page: Page, api: URL, isAdmin: boolean): Promise<void> {
	const session = await page.evaluate(async (apiUrl: string) => {
		const sessionId = sessionStorage.getItem('session_id');
		if (!sessionId) throw new Error('Authenticated browser session ID is missing');
		const response = await fetch(`${apiUrl}/v1/auth/session`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ session_id: sessionId }),
			credentials: 'include'
		});
		const body = await response.json();
		return { status: response.status, success: body.success, isAdmin: body.user?.is_admin };
	}, api.origin);
	expect(session.status).toBe(200);
	expect(session.success, 'The role probe must use a valid authenticated browser session').toBe(
		true
	);
	expect(session.isAdmin, 'The disposable account must have its expected server role').toBe(
		isAdmin
	);
}

/** End a real upload before Content-Length is satisfied. */
async function interruptTraceUpload(api: URL, cookie: string): Promise<void> {
	await new Promise<void>((resolve, reject) => {
		const secure = api.protocol === 'https:';
		const connect = secure ? tls.connect : net.connect;
		const socket = connect({
			host: api.hostname,
			port: Number(api.port || (secure ? 443 : 80)),
			...(secure ? { servername: api.hostname } : {})
		});
		socket.setTimeout(5_000, () => socket.destroy(new Error('Telemetry upload socket timed out')));
		socket.once('error', reject);
		socket.on('data', () => {
			socket.destroy(
				new Error('Incomplete telemetry upload was rejected before its body was read')
			);
		});
		socket.once(secure ? 'secureConnect' : 'connect', () => {
			socket.write(
				`POST /v1/telemetry/traces HTTP/1.1\r\nHost: ${api.host}\r\n` +
					`Cookie: ${cookie}\r\n` +
					'Content-Type: application/json\r\nContent-Length: 4096\r\nConnection: close\r\n\r\n' +
					'{"resourceSpans":',
				() => {
					// Give the isolated proxy time to enter the streaming body read.
					setTimeout(() => socket.destroy(), 250);
				}
			);
		});
		socket.once('close', (hadError: boolean) => {
			if (!hadError) resolve();
		});
	});
}

test.describe('Browser telemetry proxy HTTP boundaries', () => {
	test.setTimeout(180_000);
	// contract-test: supporting surface=rest_api assertions=ai-request-observability.no-behavior-change,ai-request-observability.propagation.complete
	test('socket cancellation smoke preserves proxy availability, auth, and the 60-per-minute ceiling', async ({
		page
	}: { page: Page }, testInfo: {
		attach: (name: string, options: { body: string; contentType: string }) => Promise<void>;
	}) => {
		const api = new URL(workflowApiUrl());
		// This intentionally spends an IP quota. It must run on an isolated CI
		// runtime and must never touch the shared dev or production endpoint.
		expect(process.env.CI, 'Telemetry quota proof requires isolated GitHub CI').toBeTruthy();
		expect(api.origin, 'Telemetry fixture must use the isolated loopback API').toBe(
			'http://localhost:8000'
		);
		expect(api.hostname.endsWith('openmates.org'), 'Do not spend a shared public API quota').toBe(
			false
		);
		const unauthorized = await page.request.post(`${api.origin}/v1/telemetry/traces`, {
			data: { resourceSpans: [] }
		});
		expect(unauthorized.status()).toBe(403);
		const browser = page.context().browser();
		expect(browser).not.toBeNull();
		const ordinaryContext = await browser!.newContext({
			baseURL: process.env.PLAYWRIGHT_TEST_BASE_URL
		});
		try {
			const ordinaryPage = await ordinaryContext.newPage();
			await loginToTestAccount(ordinaryPage, undefined, undefined, {
				credentials: getTestAccount(2)
			});
			await expectBrowserSessionRole(ordinaryPage, api, false);
			const forbidden = await ordinaryPage.request.post(`${api.origin}/v1/telemetry/traces`, {
				data: { resourceSpans: [] }
			});
			expect(forbidden.status()).toBe(403);
		} finally {
			await ordinaryContext.close();
		}
		await loginToTestAccount(page);
		await expectBrowserSessionRole(page, api, true);
		const cookies = await page.context().cookies(api.origin);
		expect(cookies.some((cookie) => cookie.name === 'auth_refresh_token')).toBe(true);
		const cookieHeader = cookies.map((cookie) => `${cookie.name}=${cookie.value}`).join('; ');
		await interruptTraceUpload(api, cookieHeader);
		const statuses: number[] = [];
		for (let attempt = 0; attempt < 61; attempt++) {
			const response = await page.request.post(`${api.origin}/v1/telemetry/traces`, {
				data: { resourceSpans: [] },
				timeout: 15_000
			});
			statuses.push(response.status());
			if (response.status() === 429) break;
			expect([200, 202]).toContain(response.status());
			expect(['ok', 'dropped']).toContain((await response.json()).status);
		}
		expect(statuses.length, 'The isolated IP starts with available trace quota').toBeGreaterThan(1);
		expect(statuses.at(-1)).toBe(429);
		expect(statuses.slice(0, -1).length).toBeLessThanOrEqual(60);
		const limited = await page.request.post(`${api.origin}/v1/telemetry/traces`, {
			data: { resourceSpans: [] }
		});
		expect(limited.status()).toBe(429);
		const retryAfter = Number(limited.headers()['retry-after']);
		expect(retryAfter).toBeGreaterThanOrEqual(1);
		expect(retryAfter).toBeLessThanOrEqual(60);
		// OTLP exports cross-origin: the browser must be able to read the delay,
		// otherwise the SDK falls back to repeated 1–5 second retries.
		const browserLimited = await page.evaluate(async (apiOrigin: string) => {
			const response = await fetch(`${apiOrigin}/v1/telemetry/traces`, {
				method: 'POST', credentials: 'include',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ resourceSpans: [] })
			});
			return { status: response.status, retryAfter: response.headers.get('Retry-After') };
		}, api.origin);
		expect(browserLimited.status).toBe(429);
		expect(browserLimited.retryAfter).not.toBeNull();
		expect(Number(browserLimited.retryAfter)).toBeGreaterThanOrEqual(1);
		await testInfo.attach('telemetry-proxy-boundaries', {
			body: JSON.stringify({
				socketAborted: true,
				acceptedRequests: statuses.length - 1,
				quotaStatus: 429,
				browserRetryAfter: browserLimited.retryAfter
			}),
			contentType: 'application/json'
		});
	});
});
