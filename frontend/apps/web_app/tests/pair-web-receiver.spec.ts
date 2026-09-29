/* eslint-disable @typescript-eslint/no-require-imports */
/** Browser-to-browser pairing over the real v2 relay. No AI request is sent. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, openSignupInterface } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

function apiUrlFor(baseUrl: string): string {
	const url = new URL(baseUrl);
	if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') {
		return 'https://api.openmates.org';
	}
	if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
	if (url.hostname === 'localhost') return 'http://localhost:8000';
	throw new Error('Unable to derive the pairing API endpoint');
}

async function userIdFor(page: any, apiUrl: string): Promise<string> {
	return page.evaluate(async (endpoint: string) => {
		const sessionId = sessionStorage.getItem('session_id');
		if (!sessionId) throw new Error('Missing browser session ID');
		const response = await fetch(`${endpoint}/v1/auth/session`, {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ session_id: sessionId })
		});
		const data = await response.json().catch(() => ({}));
		if (!response.ok || data.success !== true || !data.user?.id) {
			throw new Error(`Browser session rejected with HTTP ${response.status}`);
		}
		return String(data.user.id);
	}, apiUrl);
}

// contract-test: direct surface=gui.web assertions=auth.pair-login.single-use-zk,auth.pair-login.session-grant,auth.session.isolation
test('pairing restores the receiving browser while the approving browser remains online', async ({
	page,
	browser
}: {
	page: any;
	browser: any;
}) => {
	test.setTimeout(180_000);
	skipWithoutCredentials(test, email, password, otpKey);
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
	const apiUrl = apiUrlFor(baseUrl);
	const receiverContext = await browser.newContext();
	const receiver = await receiverContext.newPage();
	const pairRequests: Array<{ url: string; body: string }> = [];
	for (const currentPage of [page, receiver]) {
		currentPage.on('request', (request: any) => {
			if (request.url().includes('/v1/auth/pair/')) {
				pairRequests.push({ url: request.url(), body: request.postData() || '' });
			}
		});
	}

	try {
		await loginToTestAccount(
			page,
			() => undefined,
			async () => undefined
		);
		const approvingUserId = await userIdFor(page, apiUrl);

		await receiver.goto(baseUrl);
		await openSignupInterface(receiver);
		await receiver.getByTestId('tab-login').click();
		await receiver.getByTestId('login-pair-button').click();
		const pairCode = receiver.getByTestId('pair-receiver-code');
		await expect(pairCode).toBeVisible({ timeout: 15_000 });
		const token = (await pairCode.textContent())?.trim() || '';
		expect(token).toMatch(/^[A-Z0-9]{6}$/);

		await page.goto(`${baseUrl}/#pair=${token}`);
		await page.getByTestId('pair-allow-button').click();
		const pinDisplay = page.getByTestId('pair-pin-display');
		await expect(pinDisplay).toBeVisible({ timeout: 15_000 });
		const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '').trim();
		expect(pin).toMatch(/^[A-Z0-9]{6}$/);
		await receiver.getByTestId('pair-receiver-pin-input').fill(pin);

		await expect(receiver.getByTestId('message-editor')).toBeVisible({ timeout: 45_000 });
		expect(await userIdFor(receiver, apiUrl)).toBe(approvingUserId);
		expect(await userIdFor(page, apiUrl)).toBe(approvingUserId);
		expect(pairRequests.some(({ url }) => url.includes('/v1/auth/pair/v2/complete/'))).toBe(true);
		expect(pairRequests.some(({ url }) => url.includes('/v1/auth/pair/v2/acknowledge/'))).toBe(
			true
		);
		expect(pairRequests.some(({ url }) => url.includes('/v1/auth/pair/complete/'))).toBe(false);
		for (const request of pairRequests) {
			expect(request.body, `Raw PIN leaked in ${new URL(request.url).pathname}`).not.toContain(pin);
		}
	} finally {
		await receiverContext.close();
	}
});
