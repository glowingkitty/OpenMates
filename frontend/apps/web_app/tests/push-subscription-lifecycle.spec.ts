/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Exercises the real authenticated push registration routes in isolated CI. */
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { execFileSync } = require('node:child_process');
const { existsSync } = require('node:fs');
const path = require('node:path');
const { generateKeyPairSync, randomUUID } = require('node:crypto');

function apiUrl(): string {
	if (process.env.PLAYWRIGHT_TEST_API_URL) return process.env.PLAYWRIGHT_TEST_API_URL.replace(/\/$/, '');
	const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
	if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return 'http://localhost:8000';
	return `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

type PersistedOwner = { owner_id: string; targets: Array<Record<string, unknown>> };

/** Read only these two runner-provisioned accounts; all mutations use real REST. */
function readIsolatedPushTargets(emails: string[], deviceId: string): PersistedOwner[] {
	const root = path.resolve(__dirname, '../../../..');
	const compose = path.join(root, 'test-results/ci-private/compose.json');
	if (process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e' || !existsSync(compose)
		|| !deviceId.startsWith('e2e-installation-')) {
		throw new Error('Push persistence inspection requires the disposable GitHub E2E stack');
	}
	const script = `
import asyncio, base64, hashlib, json, logging, os, re, sys
logging.disable(logging.CRITICAL)
assert os.environ.get('CI') == 'true'
assert os.environ.get('OPENMATES_CI_ISOLATED') == '1'
assert os.environ.get('FRONTEND_URLS') == 'http://localhost:5173'
assert os.environ.get('CMS_URL') == 'http://cms:8055'
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.push_subscription_targets import normalize_push_subscription_targets

async def main():
    data = json.load(sys.stdin)
    emails = data['emails']
    allowed = {value for key, value in os.environ.items()
               if re.fullmatch(r'OPENMATES_TEST_ACCOUNT_CI_[0-9]+_EMAIL', key)}
    assert len(emails) == len(set(emails)) == 2
    assert all(email in allowed and re.fullmatch(r'ci-[a-z0-9-]+@example\\.com', email) for email in emails)
    assert data['deviceId'].startswith('e2e-installation-')
    directus = DirectusService()
    try:
        result = []
        for email in emails:
            digest = base64.b64encode(hashlib.sha256(email.strip().lower().encode()).digest()).decode()
            users = await directus.get_items('directus_users', params={
                'filter[hashed_email][_eq]': digest,
                'fields': 'id,hashed_email,push_notification_subscription', 'limit': 2,
            }, no_cache=True, admin_required=True, raise_on_error=True)
            assert isinstance(users, list) and len(users) == 1 and users[0]['hashed_email'] == digest
            owner = users[0]
            targets = [target for target in normalize_push_subscription_targets(owner.get('push_notification_subscription'))
                       if target.get('device_id') == data['deviceId']]
            result.append({'owner_id': owner['id'], 'targets': targets})
        print(json.dumps(result))
    finally:
        await directus.close()

asyncio.run(main())
`;
	const output = execFileSync('docker', [
		'compose', '-f', compose, 'exec', '-T', '-e', 'CI=true', '-e', 'OPENMATES_CI_ISOLATED=1',
		'api', 'python', '-c', script
	], { cwd: root, input: JSON.stringify({ emails, deviceId }), encoding: 'utf8', timeout: 45_000 });
	return JSON.parse(output.trim());
}

// contract-test: supporting surface=rest_api assertions=apple-notifications.registration.lifecycle,apple-notifications.payload.privacy-safe,apple-notifications.action.direct-reply
test('push routes register and unregister browser and native targets', async ({ page, browser }: { page: any; browser: any }) => {
	test.setTimeout(240_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the disposable isolated product stack');
	const primary = getTestAccount(1);
	const secondary = getTestAccount(2);
	if (!primary.email || !primary.password || !primary.otpKey
		|| !secondary.email || !secondary.password || !secondary.otpKey || primary.email === secondary.email) {
		throw new Error('Two distinct fresh isolated test accounts are required');
	}

	const api = apiUrl();
	const origin = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org').origin;
	const suffix = randomUUID();
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
	const nonce = randomUUID();
	const publicKey = generateKeyPairSync('x25519').publicKey.export({ type: 'spki', format: 'der' }).subarray(-32).toString('base64url');
	const encryptedTarget = {
		...nativeTarget, platform: 'ios', notification_public_key: publicKey,
		encryption_version: 'x25519-aesgcm-v1', reply_context_id: nonce, preview_enabled: false
	};
	const emails = [primary.email, secondary.email];
	const readTargets = () => readIsolatedPushTargets(emails, nativeTarget.device_id);
	const unauthenticated = await page.request.post(`${api}/v1/push/subscribe`, { data: browserTarget });
	expect(unauthenticated.status()).toBe(401);
	const deniedNative = await page.request.post(`${api}/v1/notifications/register-device`, {
		data: encryptedTarget, headers: { Origin: origin }
	});
	expect([401, 403]).toContain(deniedNative.status());
	expect(await deniedNative.json()).not.toHaveProperty('reply_context_id');

	await loginToTestAccount(page, () => {}, async () => undefined, { waitForEditor: false, credentials: primary });
	let browserRegistered = false;
	let nativeRegistered = false;
	let otherRegistered = false;
	let otherContext: any;
	let otherPage: any;
	try {
		const browserRegistration = await page.request.post(`${api}/v1/push/subscribe`, { data: browserTarget });
		expect(browserRegistration.status()).toBe(200);
		expect((await browserRegistration.json()).success).toBe(true);
		browserRegistered = true;

		const native = await page.request.post(`${api}/v1/notifications/register-device`, {
			data: nativeTarget, headers: { Origin: origin }
		});
		expect(native.status()).toBe(200);
		expect(await native.json()).toEqual({ success: true, message: 'Device registered' });
		nativeRegistered = true;
		let [owner, other] = readTargets();
		expect(owner.owner_id).not.toBe(other.owner_id);
		expect(owner.targets).toHaveLength(1);
		expect(owner.targets[0]).not.toHaveProperty('reply_context_id');
		expect(other.targets).toEqual([]);

		const bound = await page.request.post(`${api}/v1/notifications/register-device`, {
			data: { ...encryptedTarget, user_id: other.owner_id }, headers: { Origin: origin }
		});
		expect(bound.status()).toBe(200);
		expect(await bound.json()).toEqual({ success: true, message: 'Device registered', reply_context_id: nonce });
		[owner, other] = readTargets();
		expect(owner.targets).toHaveLength(1);
		expect(owner.targets[0]).toMatchObject({ reply_context_id: nonce, reply_context_owner_id: owner.owner_id, preview_enabled: false });
		expect(other.targets).toEqual([]);
		const persisted = owner.targets;
		for (const reply_context_id of ['invalid', 'ABCDEFAB-CDEF-4DEF-8DEF-ABCDEFABCDEF', '00000000-0000-0000-0000-000000000000']) {
			const invalid = await page.request.post(`${api}/v1/notifications/register-device`, {
				data: { ...encryptedTarget, reply_context_id }, headers: { Origin: origin }
			});
			expect(invalid.status()).toBe(400);
			expect(await invalid.json()).not.toHaveProperty('reply_context_id');
		}
		const invalidConsent = await page.request.post(`${api}/v1/notifications/register-device`, {
			data: { ...encryptedTarget, preview_enabled: 'false' }, headers: { Origin: origin }
		});
		expect(invalidConsent.status()).toBe(422);
		expect(readTargets()[0].targets).toEqual(persisted);

		// A second authenticated owner cannot redirect storage or unregister the
		// first owner's matching physical installation using a caller user_id.
		otherContext = await browser.newContext();
		otherPage = await otherContext.newPage();
		await loginToTestAccount(otherPage, () => {}, async () => undefined, { waitForEditor: false, credentials: secondary });
		const otherNonce = randomUUID();
		const otherBound = await otherPage.request.post(`${api}/v1/notifications/register-device`, {
			data: { ...encryptedTarget, reply_context_id: otherNonce, user_id: owner.owner_id }, headers: { Origin: origin }
		});
		expect(otherBound.status()).toBe(200);
		expect((await otherBound.json()).reply_context_id).toBe(otherNonce);
		otherRegistered = true;
		[owner, other] = readTargets();
		expect(owner.targets).toEqual(persisted);
		expect(other.targets).toHaveLength(1);
		expect(other.targets[0]).toMatchObject({ reply_context_id: otherNonce, reply_context_owner_id: other.owner_id });
		const removeOther = await otherPage.request.delete(`${api}/v1/notifications/unregister-device`, {
			data: { token: nativeTarget.token, device_id: nativeTarget.device_id, user_id: owner.owner_id }, headers: { Origin: origin }
		});
		expect(removeOther.status()).toBe(200);
		otherRegistered = false;
		[owner, other] = readTargets();
		expect(owner.targets).toEqual(persisted);
		expect(other.targets).toEqual([]);

		const removeBrowser = await page.request.delete(`${api}/v1/push/subscribe`);
		expect(removeBrowser.status()).toBe(200);
		expect((await removeBrowser.json()).success).toBe(true);
		browserRegistered = false;
		expect(readTargets()[0].targets).toEqual(persisted);
		const removeNative = await page.request.delete(`${api}/v1/notifications/unregister-device`, {
			data: { token: nativeTarget.token, device_id: nativeTarget.device_id }, headers: { Origin: origin }
		});
		expect(removeNative.status()).toBe(200);
		expect((await removeNative.json()).success).toBe(true);
		nativeRegistered = false;
		expect(readTargets()[0].targets).toEqual([]);
	} finally {
		if (browserRegistered) await page.request.delete(`${api}/v1/push/subscribe`);
		if (nativeRegistered) await page.request.delete(`${api}/v1/notifications/unregister-device`, {
			data: { token: nativeTarget.token, device_id: nativeTarget.device_id }, headers: { Origin: origin }
		});
		if (otherRegistered) await otherPage.request.delete(`${api}/v1/notifications/unregister-device`, {
			data: { token: nativeTarget.token, device_id: nativeTarget.device_id }, headers: { Origin: origin }
		});
		if (otherContext) await otherContext.close();
	}
});
