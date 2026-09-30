/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Exercises the real authenticated push registration routes in isolated CI. */
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

function apiUrl(): string {
	if (process.env.PLAYWRIGHT_TEST_API_URL) return process.env.PLAYWRIGHT_TEST_API_URL.replace(/\/$/, '');
	const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
	if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return 'http://localhost:8000';
	return `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

// contract-test: supporting surface=rest_api assertions=apple-notifications.registration.lifecycle
test('push routes register and unregister browser and native targets', async ({ page }: { page: any }) => {
	test.setTimeout(150_000);
	const account = getTestAccount();
	test.skip(!account.email || !account.password || !account.otpKey, 'Test account credentials required.');

	const api = apiUrl();
	const origin = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org').origin;
	const suffix = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
	const browserTarget = {
		endpoint: `https://push.example.test/${suffix}`,
		keys: { p256dh: 'e2e-public-key', auth: 'e2e-auth-key' },
		expirationTime: null
	};
	const nativeTarget = {
		token: `e2e-native-${suffix}`,
		device_id: `e2e-installation-${suffix}`,
		platform: 'macos',
		environment: 'sandbox'
	};

	const unauthenticated = await page.request.post(`${api}/v1/push/subscribe`, { data: browserTarget });
	expect(unauthenticated.status()).toBe(401);

	await loginToTestAccount(page, () => {}, async () => undefined, { waitForEditor: false });
	let browserRegistered = false;
	let nativeRegistered = false;
	try {
		const browser = await page.request.post(`${api}/v1/push/subscribe`, { data: browserTarget });
		expect(browser.status()).toBe(200);
		expect((await browser.json()).success).toBe(true);
		browserRegistered = true;

		const native = await page.request.post(`${api}/v1/notifications/register-device`, {
			data: nativeTarget,
			headers: { Origin: origin }
		});
		expect(native.status()).toBe(200);
		expect((await native.json()).success).toBe(true);
		nativeRegistered = true;

		const removeBrowser = await page.request.delete(`${api}/v1/push/subscribe`);
		expect(removeBrowser.status()).toBe(200);
		expect((await removeBrowser.json()).success).toBe(true);
		browserRegistered = false;

		const removeNative = await page.request.delete(`${api}/v1/notifications/unregister-device`, {
			data: { token: nativeTarget.token, device_id: nativeTarget.device_id },
			headers: { Origin: origin }
		});
		expect(removeNative.status()).toBe(200);
		expect((await removeNative.json()).success).toBe(true);
		nativeRegistered = false;
	} finally {
		if (browserRegistered) await page.request.delete(`${api}/v1/push/subscribe`);
		if (nativeRegistered) await page.request.delete(`${api}/v1/notifications/unregister-device`, {
			data: { token: nativeTarget.token, device_id: nativeTarget.device_id },
			headers: { Origin: origin }
		});
	}
});
