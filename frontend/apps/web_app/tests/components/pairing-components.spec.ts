import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview

const background = '%23dbeafe';
const receiverPreview = (width: number) =>
	`/dev/preview/settings/security/SettingsSessionsPairInitiate?theme=light&background=${background}&width=${width}&chrome=0`;
const senderPreview = (width: number) =>
	`/dev/preview/settings/security/SettingsSessionsConfirmPair?theme=light&background=${background}&width=${width}&chrome=0`;

const fictionalPair = {
	protocol_version: 2,
	token: 'ABC346',
	session_id: 'preview-receiver-session',
	receiver_token_hash: 'a'.repeat(64),
	authorizer_user_id: '00000000-0000-4000-8000-000000000001',
	device_name: 'Preview laptop',
	ip_truncated: '192.0.2.x',
	country_code: 'US',
	city: 'Preview City'
};

function corsHeaders(origin: string) {
	return {
		'access-control-allow-origin': origin,
		'access-control-allow-credentials': 'true',
		'access-control-allow-methods': 'GET, POST, DELETE, OPTIONS',
		'access-control-allow-headers': 'content-type,x-openmates-pair-receiver'
	};
}

function trackPairStore(page: Page) {
	let sourceUrl = '';
	page.on('request', (request) => {
		if (request.url().includes('/src/stores/pairSessionStore.ts')) sourceUrl = request.url();
	});
	return async (token: string) => {
		expect(sourceUrl, 'preview must use the production pair handoff store').not.toBe('');
		await page.evaluate(
			async ({ sourceUrl, token }) => {
				const store = await import(/* @vite-ignore */ sourceUrl);
				store.pendingPairToken.set(token);
			},
			{ sourceUrl, token }
		);
	};
}

// contract-test: supporting surface=gui.web assertions=auth.pair-login.lifecycle,auth.pair-login.single-use-zk
test('mounted sender consumes a replacement token and ignores late expired request info', async ({
	page
}) => {
	const replaceToken = trackPairStore(page);
	let releaseOld!: () => void;
	const oldRequest = new Promise<void>((resolve) => {
		releaseOld = resolve;
	});
	let oldInfoStarted = false;
	await page.route('**/v1/auth/methods', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173'),
			body: JSON.stringify({ has_passkey: false, has_password: true, has_2fa: true })
		})
	);
	await page.route('**/v1/auth/pair/v2/**', async (route) => {
		const request = route.request(),
			path = new URL(request.url()).pathname;
		const headers = corsHeaders(request.headers().origin || 'http://localhost:5173');
		if (request.method() === 'OPTIONS') {
			await route.fulfill({ status: 204, headers });
			return;
		}
		if (path.endsWith('/info/ABC346')) {
			oldInfoStarted = true;
			await oldRequest;
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				headers,
				body: JSON.stringify({ ...fictionalPair, expires_at: 0 })
			});
		} else {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				headers,
				body: JSON.stringify({
					...fictionalPair,
					token: 'DEF468',
					session_id: 'replacement-receiver',
					device_name: 'Replacement laptop',
					expires_at: Math.floor(Date.now() / 1000) + 300
				})
			});
		}
	});
	await page.goto(senderPreview(390));
	await waitForComponentPreview(page);
	await expect.poll(() => oldInfoStarted).toBe(true);
	const timeOrigin = await page.evaluate(() => performance.timeOrigin);
	await replaceToken('DEF468');
	await expect(page.getByText('Replacement laptop')).toBeVisible();
	await expect(page.getByTestId('pair-allow-button')).toBeVisible();
	releaseOld();
	await expect(page.getByText('Replacement laptop')).toBeVisible();
	await expect(page.getByTestId('pair-allow-button')).toBeEnabled();
	expect(await page.evaluate(() => performance.timeOrigin)).toBe(timeOrigin);
});

// contract-test: supporting surface=gui.web assertions=auth.pair-login.lifecycle,auth.pair-login.single-use-zk
test('replacement sender cancels the old approval and fences its late poll response', async ({
	page
}) => {
	const replaceToken = trackPairStore(page);
	let releaseOld!: () => void;
	const oldPoll = new Promise<void>((resolve) => {
		releaseOld = resolve;
	});
	let oldPollStarted = false,
		replacementPolls = 0;
	const cancelled: string[] = [];
	await page.route('**/v1/auth/methods', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173'),
			body: JSON.stringify({ has_passkey: false, has_password: true, has_2fa: true })
		})
	);
	await page.route('**/v1/auth/pair/v2/**', async (route) => {
		const request = route.request(),
			path = new URL(request.url()).pathname;
		const headers = corsHeaders(request.headers().origin || 'http://localhost:5173');
		if (request.method() === 'OPTIONS') {
			await route.fulfill({ status: 204, headers });
			return;
		}
		const token = path.split('/').at(-1)!;
		if (request.method() === 'DELETE') {
			cancelled.push(token);
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				headers,
				body: JSON.stringify({ success: true })
			});
			return;
		}
		if (path.endsWith('/authorizer/ABC346')) {
			oldPollStarted = true;
			await oldPoll;
		}
		if (path.endsWith('/authorizer/DEF468')) replacementPolls++;
		const info = {
			...fictionalPair,
			token,
			session_id: `receiver-${token}`,
			device_name: token === 'DEF468' ? 'Replacement laptop' : 'Preview laptop',
			expires_at: Math.floor(Date.now() / 1000) + 300
		};
		const body = path.includes('/info/')
			? info
			: path.includes('/approve/')
				? {
						...info,
						auto_logout_minutes: request.postDataJSON().auto_logout_minutes,
						success: true
					}
				: { status: token === 'ABC346' ? 'cancelled' : 'approved' };
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers,
			body: JSON.stringify(body)
		});
	});
	await page.goto(senderPreview(390));
	await waitForComponentPreview(page);
	await page.getByTestId('pair-allow-button').click();
	await expect(page.getByTestId('pair-pin-display')).toBeVisible({ timeout: 20_000 });
	await expect.poll(() => oldPollStarted).toBe(true);
	await replaceToken('DEF468');
	await expect(page.getByText('Replacement laptop')).toBeVisible();
	await expect(page.getByTestId('pair-pin-display')).toHaveCount(0);
	await page.getByTestId('pair-allow-button').click();
	await expect(page.getByTestId('pair-pin-display')).toBeVisible({ timeout: 20_000 });
	const currentPIN = await page.getByTestId('pair-pin-display').textContent();
	releaseOld();
	await expect.poll(() => replacementPolls).toBeGreaterThan(0);
	await expect(page.getByTestId('pair-pin-display')).toHaveText(currentPIN!);
	expect(cancelled).toContain('ABC346');
	expect(cancelled).not.toContain('DEF468');
});

// contract-test: supporting surface=gui.web assertions=auth.pair-login.single-use-zk,auth.pair-login.lifecycle
test('receiver preview shows its code and handles cancellation on narrow and wide canvases', async ({
	page
}) => {
	let receiverStatus: 'waiting' | 'cancelled' = 'waiting';
	let initiateCount = 0;
	await page.route('**/v1/auth/pair/v2/**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		const origin = request.headers().origin || 'http://localhost:5173';
		if (request.method() === 'OPTIONS') {
			await route.fulfill({ status: 204, headers: corsHeaders(origin) });
			return;
		}
		let body: Record<string, unknown> = {};
		if (path.endsWith('/initiate')) {
			initiateCount++;
			const payload = request.postDataJSON();
			expect(payload.receiver_token_hash).toMatch(/^[0-9a-f]{64}$/);
			expect(payload).not.toHaveProperty('pin');
			body = {
				protocol_version: 2,
				token: 'ABC346',
				expires_at: Math.floor(Date.now() / 1000) + 300
			};
		} else if (path.includes('/receiver/')) {
			body = { status: receiverStatus, protocol_version: 2 };
		} else {
			body = { success: true };
		}
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: corsHeaders(origin),
			body: JSON.stringify(body)
		});
	});

	for (const width of [390, 768]) {
		receiverStatus = 'waiting';
		await page.goto(receiverPreview(width));
		const canvas = await waitForComponentPreview(page);
		await expect(page.getByTestId('pair-receiver-code')).toHaveText('ABC346');
		await expect(page.getByTestId('pair-receiver-pin-input')).toBeVisible();
		const geometry = await canvas.evaluate((element) => ({
			client: element.clientWidth,
			scroll: element.scrollWidth
		}));
		expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1);
	}

	receiverStatus = 'cancelled';
	await expect(page.getByTestId('pair-receiver-pin-input')).toHaveCount(0, { timeout: 10_000 });
	await expect(page.getByTestId('pair-receiver-refresh')).toBeVisible();
	await page.getByTestId('pair-receiver-refresh').click();
	await expect(page.getByTestId('pair-receiver-code')).toHaveText('ABC346');
	expect(initiateCount).toBeGreaterThanOrEqual(3);
});

// contract-test: supporting surface=gui.web assertions=auth.pair-login.single-use-zk,auth.pair-login.lifecycle
test('sender preview confirms device and keeps its locally generated PIN visible', async ({
	page
}) => {
	let approvedLifetime: unknown = null;
	await page.route('**/v1/auth/methods', async (route) => {
		const origin = route.request().headers().origin || 'http://localhost:5173';
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: corsHeaders(origin),
			body: JSON.stringify({ has_passkey: false, has_password: true, has_2fa: true })
		});
	});
	await page.route('**/v1/auth/pair/v2/**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		const origin = request.headers().origin || 'http://localhost:5173';
		if (request.method() === 'OPTIONS') {
			await route.fulfill({ status: 204, headers: corsHeaders(origin) });
			return;
		}
		const expires_at = Math.floor(Date.now() / 1000) + 300;
		if (path.includes('/approve/')) approvedLifetime = request.postDataJSON().auto_logout_minutes;
		const body = path.includes('/info/')
			? { ...fictionalPair, expires_at }
			: path.includes('/approve/')
				? { ...fictionalPair, expires_at, auto_logout_minutes: approvedLifetime, success: true }
				: { status: 'approved' };
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: corsHeaders(origin),
			body: JSON.stringify(body)
		});
	});

	await page.goto(senderPreview(390));
	const canvas = await waitForComponentPreview(page);
	await expect(page.getByText('Preview laptop')).toBeVisible();
	await expect(page.getByTestId('pair-allow-button')).toBeVisible();
	await page.locator('#confirm-pair-auto-logout').selectOption('30');
	await page.getByTestId('pair-allow-button').focus();
	await page.keyboard.press('Enter');
	const pin = page.getByTestId('pair-pin-display');
	await expect(pin).toBeVisible({ timeout: 20_000 });
	await expect(pin).toHaveText(/^[A-Z0-9]{3} [A-Z0-9]{3}$/);
	expect(approvedLifetime).toBe(30);
	const geometry = await canvas.evaluate((element) => ({
		client: element.clientWidth,
		scroll: element.scrollWidth
	}));
	expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1);
});

// contract-test: supporting surface=gui.web assertions=auth.pair-login.approval-assurance
test('sender without enrolled OTP verifies a password and one-use email code before approval', async ({
	page
}) => {
	let approveCalls = 0;
	let emailRequests = 0;
	let emailVerifications = 0;
	let legacyStepUpCalls = 0;
	let verified = false;
	let requestedSessionId: string | null = null;
	const challengeId = 'preview-pair-approval-challenge-123456';
	await page.route('**/v1/auth/methods', async (route) => {
		const origin = route.request().headers().origin || 'http://localhost:5173';
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: corsHeaders(origin),
			body: JSON.stringify({
				has_passkey: false,
				has_password: true,
				has_2fa: false,
				credential_version: 1
			})
		});
	});
	await page.route('**/v1/auth/sensitive/**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		const origin = request.headers().origin || 'http://localhost:5173';
		if (request.method() === 'OPTIONS') {
			await route.fulfill({ status: 204, headers: corsHeaders(origin) });
			return;
		}
		const payload = request.postDataJSON();
		if (path.endsWith('/email/request')) {
			emailRequests++;
			expect(payload).toEqual({
				purpose: 'pair_approval',
				email: 'pair-preview@example.test',
				session_id: expect.any(String)
			});
			requestedSessionId = payload.session_id;
			expect(requestedSessionId?.length).toBeGreaterThan(0);
			expect(request.postData()).not.toContain('PreviewPassword!');
			expect(payload).not.toHaveProperty('pin');
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				headers: corsHeaders(origin),
				body: JSON.stringify({
					success: true,
					challenge_id: challengeId,
					expires_in: 600
				})
			});
			return;
		}
		if (path.endsWith('/email/verify')) {
			emailVerifications++;
			expect(payload.purpose).toBe('pair_approval');
			expect(payload.challenge_id).toBe(challengeId);
			expect(payload.code).toBe('123456');
			expect(payload.hashed_email).toEqual(expect.any(String));
			expect(payload.lookup_hash).toEqual(expect.any(String));
			expect(payload.session_id).toBe(requestedSessionId);
			expect(payload).not.toHaveProperty('password_challenge_id');
			expect(payload).not.toHaveProperty('password_proof');
			expect(payload).not.toHaveProperty('pin');
			expect(request.postData()).not.toContain('PreviewPassword!');
			verified = true;
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				headers: corsHeaders(origin),
				body: JSON.stringify({
					success: true,
					expires_in: 300
				})
			});
			return;
		}
		await route.fulfill({ status: 404 });
	});
	await page.route('**/v1/auth/pair/v2/**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		const origin = request.headers().origin || 'http://localhost:5173';
		if (request.method() === 'OPTIONS') {
			await route.fulfill({ status: 204, headers: corsHeaders(origin) });
			return;
		}
		const expires_at = Math.floor(Date.now() / 1000) + 300;
		if (path.endsWith('/step-up')) legacyStepUpCalls++;
		if (path.includes('/approve/')) {
			approveCalls++;
			expect(request.postDataJSON()).not.toHaveProperty('pin');
			if (!verified) {
				await route.fulfill({
					status: 401,
					contentType: 'application/json',
					headers: corsHeaders(origin),
					body: JSON.stringify({ detail: 'Recent authentication required' })
				});
				return;
			}
		}
		const body = path.includes('/info/')
			? { ...fictionalPair, expires_at }
			: path.includes('/approve/')
				? { ...fictionalPair, expires_at, auto_logout_minutes: null, success: true }
				: { status: 'approved' };
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: corsHeaders(origin),
			body: JSON.stringify(body)
		});
	});

	await page.goto(senderPreview(390));
	await waitForComponentPreview(page);
	await page.getByTestId('pair-allow-button').click();
	await expect(page.getByTestId('password-input')).toBeVisible();
	await page.getByTestId('password-input').fill('PreviewPassword!');
	await page.getByTestId('auth-btn').click();
	await expect(page.getByTestId('auth-email-otp')).toBeVisible();
	await page.getByTestId('auth-email-otp').locator('input').fill('123456');
	await expect(page.getByTestId('pair-pin-display')).toBeVisible({ timeout: 20_000 });
	expect(approveCalls).toBe(2);
	expect(emailRequests).toBe(1);
	expect(emailVerifications).toBe(1);
	expect(legacyStepUpCalls).toBe(0);
});
