/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Published refresh grace against the disposable isolated CI backend. */
const { test, expect } = require('./helpers/cookie-audit');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

function expireIsolatedAccessWindow(token: string): void {
	const sourceRoot = process.env.OPENMATES_CI_SOURCE_ROOT;
	if (process.env.OPENMATES_CI_ISOLATED !== '1' || !sourceRoot) {
		throw new Error('Rotation fixture requires the disposable isolated CI backend.');
	}
	const composeFile = path.join(sourceRoot, 'test-results/ci-private/compose.json');
	if (!fs.existsSync(composeFile)) throw new Error('Isolated compose fixture is missing.');
	// Only the disposable session link changes. Neither the durable lifetime nor
	// any sibling session is modified; no credential goes into process arguments.
	const digest = createHash('sha256').update(token).digest('hex');
	const fixture = [
		'import json, os, re, sys, redis',
		'digest = sys.stdin.read().strip()',
		'assert re.fullmatch("[a-f0-9]{64}", digest)',
		'host, port = os.environ["DRAGONFLY_URL"].rsplit(":", 1)',
		'client = redis.Redis(host=host, port=int(port), password=os.environ["DRAGONFLY_PASSWORD"])',
		'key = "session:" + digest',
		'link = json.loads(client.get(key))',
		'assert link.get("user_id") and client.ttl(key) > 0',
		'link["token_expiry"] = 0',
		'assert client.set(key, json.dumps(link), xx=True, keepttl=True)'
	].join('\n');
	execFileSync('docker', ['compose', '-f', composeFile, 'exec', '-T', 'api', 'python', '-c', fixture], {
		input: digest, stdio: ['pipe', 'pipe', 'pipe'], timeout: 30000
	});
}

async function refreshCookie(context: any): Promise<string> {
	const cookie = (await context.cookies()).find((value: any) => value.name === 'auth_refresh_token');
	if (!cookie?.value) throw new Error('Authenticated refresh cookie is missing.');
	return cookie.value;
}

// contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement,auth.session.isolation
// contract-test: direct surface=gui.web assertions=auth.session.lifecycle
test('published rotation shares cookies, expires after grace, and respects revocation', async ({ page, playwright, browser }: any) => {
	test.setTimeout(120000);
	test.skip(process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the disposable isolated CI backend.');
	const credentials = getTestAccount();
	skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
	await loginToTestAccount(page, undefined, undefined, { waitForEditor: true, credentials });
	const apiUrl = process.env.OPENMATES_E2E_API_URL;
	if (!apiUrl || new URL(apiUrl).hostname !== 'localhost') {
		throw new Error('Rotation fixture requires the runner-local API.');
	}
	const sessionId = await page.evaluate(() => sessionStorage.getItem('session_id'));
	if (!sessionId) throw new Error('Browser session ID is missing.');
	const userAgent = await page.evaluate(() => navigator.userAgent);
	const origin = new URL(page.url()).origin;
	const clients: any[] = [];
	const siblingContext = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_TEST_BASE_URL, userAgent });
	const siblingPage = await siblingContext.newPage();
	async function holding(token: string): Promise<any> {
		const client = await playwright.request.newContext({
			baseURL: apiUrl, userAgent,
			extraHTTPHeaders: { Origin: origin, Cookie: `auth_refresh_token=${token}` }
		});
		clients.push(client);
		return client;
	}
	async function session(client: any): Promise<any> {
		return client.post(`${apiUrl}/v1/auth/session`, { data: { session_id: sessionId }, headers: { Origin: origin } });
	}
	try {
		await loginToTestAccount(siblingPage, undefined, undefined, { waitForEditor: true, credentials });
		const siblingClient = await holding(await refreshCookie(siblingContext));
		const original = await refreshCookie(page.context());
		expireIsolatedAccessWindow(original);
		const rotated = await session(page.context().request);
		expect(rotated.status()).toBe(200);
		expect((await rotated.json()).success).toBe(true);
		const successor = await refreshCookie(page.context());
		expect(successor !== original, 'A single issuer rotation must publish a successor cookie.').toBe(true);
		const oldClient = await holding(original);
		const [overlap, protectedRequest] = await Promise.all([
			session(oldClient), oldClient.get('/v1/auth/sessions')
		]);
		expect(overlap.status()).toBe(200);
		expect((await overlap.json()).success).toBe(true);
		expect(protectedRequest.status()).toBe(200);
		const provider = await oldClient.post('/v1/auth/2fa/setup/provider', {
			data: { provider: 'Isolated fixture authenticator' }
		});
		expect(provider.status()).toBe(200);
		expect((await provider.json()).success).toBe(true);
		expect((provider.headers()['set-cookie'] || '').includes(`auth_refresh_token=${successor}`),
			'A manual authentication route must publish the successor on its model response.').toBe(true);
		// fetch resolves at response headers, allowing a real SSE response to be
		// checked and cancelled without buffering its indefinite event body.
		const stream = await fetch(`${apiUrl}/v1/notifications/stream`, {
			headers: { Origin: origin, Cookie: `auth_refresh_token=${original}`, 'User-Agent': userAgent }
		});
		try {
			expect(stream.status).toBe(200);
			expect(stream.headers.getSetCookie().some((cookie) => cookie.includes(`auth_refresh_token=${successor}`)),
				'A streaming response must carry the guard-approved successor cookie.').toBe(true);
		} finally {
			await stream.body?.cancel();
		}
		const listing = await protectedRequest.json();
		expect(listing.sessions.filter((item: any) => item.is_current).length).toBe(1);
		const registered = await oldClient.post('/v1/auth/sessions/register-meta', {
			data: { encrypted_meta: Buffer.from('opaque isolated fixture').toString('base64') }
		});
		expect(registered.status()).toBe(200);
		const logoutOthers = await oldClient.post('/v1/auth/sessions/logout-others', { data: {} });
		expect(logoutOthers.status()).toBe(200);
		expect((await siblingClient.get('/v1/auth/sessions')).status()).toBe(401);
		expect((await oldClient.get('/v1/auth/sessions')).status()).toBe(200);
		for (const result of [overlap, protectedRequest]) {
			const cookie = result.headers()['set-cookie'] || '';
			expect(cookie.includes(`auth_refresh_token=${successor}`), 'Overlap must reuse the published cookie.').toBe(true);
		}
		await expect(page.locator('[data-authenticated="true"]')).toBeVisible();
		await expect(page.getByTestId('message-editor')).toBeVisible();

		// Allow the real server's 15-second result TTL to expire.
		await page.waitForTimeout(16000);
		expect((await session(oldClient)).status()).toBe(401);
		expect((await oldClient.get('/v1/auth/sessions')).status()).toBe(401);
		const activeClient = await holding(successor);
		expect((await session(activeClient)).status()).toBe(200);

		// A second rotation creates a fresh grace interval, then explicit logout
		// must deny both its retired source and its active successor immediately.
		expireIsolatedAccessWindow(successor);
		expect((await session(page.context().request)).status()).toBe(200);
		const next = await refreshCookie(page.context());
		expect(next !== successor).toBe(true);
		const nextClient = await holding(next);
		const logout = await activeClient.post('/v1/auth/logout', { data: {} });
		expect(logout.status()).toBe(200);
		expect((await logout.json()).success).toBe(true);
		expect((await activeClient.get('/v1/auth/sessions')).status()).toBe(401);
		expect((await nextClient.get('/v1/auth/sessions')).status()).toBe(401);
	} finally {
		await Promise.all(clients.map((client) => client.dispose()));
		await siblingContext.close();
	}
});
