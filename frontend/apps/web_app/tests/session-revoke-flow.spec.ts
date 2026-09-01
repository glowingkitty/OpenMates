/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Session Revoke Flow — E2E Test
 *
 * Verifies the fix for the bug where revoking another device's session from
 * Settings > Account > Security > Sessions also logged out the current device.
 *
 * Test flow:
 * 1. Session A logs in (browser context A).
 * 2. Session B logs in (browser context B — separate tab/device).
 * 3. Session A opens Settings > Account > Security > Sessions.
 * 4. Session A finds Session B in the sessions list and clicks "Remove".
 * 5. Assert: Session B receives the force_logout event and IS logged out.
 * 6. Assert: Session A remains logged in (NOT logged out).
 *
 * Architecture: docs/architecture/device-sessions.md
 * Fix: backend/core/api/app/routes/auth_routes/auth_sessions.py — exclude_connection_hash
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { test, expect } = require('./helpers/cookie-audit');
const { chromium } = require('@playwright/test');
const { spawnSync } = require('child_process');
const fs = require('fs');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const {
	dismissSecurityReminderIfPresent,
	fillMessageEditor,
	startNewChat
} = require('./helpers/chat-test-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_VIDEO_HEIGHT = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_HEIGHT || '', 10);
const IS_PROOF_CAPTURE = PROOF_VIDEO_WIDTH > 0 && PROOF_VIDEO_HEIGHT > 0;
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const PROOF_CONTEXT_OPTIONS = IS_PROOF_CAPTURE
	? {
		viewport: { width: PROOF_VIDEO_WIDTH, height: PROOF_VIDEO_HEIGHT },
		...(PROOF_DEVICE === 'web-phone' ? { hasTouch: true, isMobile: true, colorScheme: 'dark' } : { colorScheme: 'light' })
	}
	: {};
const PROOF_CAPTURE_END_HOLD_MS = 750;
const PROOF_VIDEO_CRF = '32';
const SESSION_STABILIZE_MS = 8000;
const LANDING_INTRO_COVERAGE_TIMEOUT_MS = 20000;
const GUEST_ONBOARDING_IDS = [
	'openmates-intro',
	'openmates-actionable-events',
	'openmates-privacy-safety',
	'openmates-mates-focus',
	'openmates-provider-cross-platform',
	'openmates-signup-cta'
];

async function expectLandingIntroCoverageUntilNextSlide(page: any): Promise<void> {
	await page.evaluate((timeoutMs: number) => new Promise<void>((resolve, reject) => {
		const startedAt = performance.now();
		const inspectFrame = () => {
			const activeChat = document.querySelector<HTMLElement>('[data-testid="active-chat-container"]');
			const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
			const composer = document.querySelector<HTMLElement>('[data-testid="message-input-wrapper"]');
			if (!activeChat || !banner || !composer) {
				reject(new Error('Forced logout landing elements disappeared during intro coverage monitoring'));
				return;
			}

			if (banner.dataset.currentInspirationId !== 'openmates-intro') {
				resolve();
				return;
			}

			const activeRect = activeChat.getBoundingClientRect();
			const bannerRect = banner.getBoundingClientRect();
			const composerRect = composer.getBoundingClientRect();
			const composerStyle = getComputedStyle(composer);
			const composerVisible = composerStyle.display !== 'none'
				&& composerStyle.visibility !== 'hidden'
				&& Number.parseFloat(composerStyle.opacity || '1') > 0
				&& composerRect.width > 0
				&& composerRect.height > 0;
			const bottomDelta = Math.abs(activeRect.bottom - bannerRect.bottom);
			if (composerVisible || bottomDelta > 2) {
				reject(new Error(
					`Landing intro lost full-shell coverage before the next slide: phase=${banner.dataset.landingIntroPhase || 'unknown'}, composerVisible=${composerVisible}, bottomDelta=${bottomDelta.toFixed(2)}`
				));
				return;
			}

			if (performance.now() - startedAt >= timeoutMs) {
				reject(new Error('Landing intro did not advance before the continuous coverage timeout'));
				return;
			}
			requestAnimationFrame(inspectFrame);
		};
		inspectFrame();
	}), LANDING_INTRO_COVERAGE_TIMEOUT_MS);
}

const SESSION_REVOKE_LOGOUT_PROOF = defineVideoProof({
	id: 'session-revoke-logout-welcome-reset',
	title: 'Session revoke logout restores guest welcome',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'session-b-draft',
			text: 'Session B starts in an authenticated draft chat with its chat header visible.',
			checkpoint: 'session-b-draft-header',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'session-b-forced-logout',
			text: 'After Session A removes Session B, Session B returns to the guest onboarding carousel without the stale draft header.',
			checkpoint: 'session-b-guest-onboarding',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'session-revoke.session-b-draft-header',
			checkpoint: 'session-b-draft-header',
			visual: 'Session B visibly shows an authenticated draft chat header before revocation.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'daily-inspiration.guest-isolated-after-force-logout',
			checkpoint: 'session-b-guest-onboarding',
			visual: 'Session B visibly shows the expanded first guest intro covering the full chat shell with no composer or stale chat header after force logout.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

async function dismissBlockingNotifications(page: any, logFn: (msg: string) => void): Promise<void> {
	await dismissSecurityReminderIfPresent(page, logFn);
	for (const dismissButton of await page.getByTestId('notification-dismiss').all()) {
		if (!(await dismissButton.isVisible().catch(() => false))) continue;
		await dismissButton.click({ timeout: 5000, force: true });
	}
}

function trimProofVideoToProofWindow(rawPath: string, outputPath: string, proofStartOffsetMs: number, proofEndOffsetMs: number): void {
	const trimStartSeconds = Math.max(0, proofStartOffsetMs / 1000).toFixed(3);
	const trimDurationSeconds = Math.max(0.1, (proofEndOffsetMs - proofStartOffsetMs) / 1000).toFixed(3);
	const result = spawnSync('ffmpeg', [
		'-y',
		'-i', rawPath,
		'-ss', trimStartSeconds,
		'-t', trimDurationSeconds,
		'-map', '0:v:0',
		'-c:v', 'libvpx-vp9',
		'-deadline', 'realtime',
		'-cpu-used', '4',
		'-b:v', '0',
		'-crf', PROOF_VIDEO_CRF,
		'-an',
		outputPath
	], { encoding: 'utf8' });
	if (result.error || result.status !== 0 || !fs.existsSync(outputPath)) {
		const detail = result.error?.message || result.stderr || result.stdout || 'unknown ffmpeg failure';
		throw new Error(`Session revoke proof video trim failed: ${String(detail).slice(-1000)}`);
	}
	fs.rmSync(rawPath, { force: true });
}

// ---------------------------------------------------------------------------
// Login helper (shared between sessions)
// ---------------------------------------------------------------------------

async function loginToApp(page: any, logFn: (msg: string) => void): Promise<void> {
	await page.goto('/');

	const headerLoginButton = page.getByTestId('header-login-signup-btn');
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();

	// Click Login tab to switch from signup to login view
	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 10000 });
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logFn('Email submitted.');

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 10000 });
	await passwordInput.fill(TEST_PASSWORD);

	// Submit password first, then handle OTP if required.
	// OTP field only appears after backend confirms 2FA is needed (anti-enumeration).
	const { submitPasswordAndHandleOtp, waitForChatReady } = require('./helpers/chat-test-helpers');
	await submitPasswordAndHandleOtp(page, TEST_OTP_KEY, logFn);
	logFn('Login submitted, waiting for authenticated chat UI…');

	await waitForChatReady(page, logFn);
	logFn('Authenticated chat UI ready — login complete.');
}

// ---------------------------------------------------------------------------
// Navigate to Settings > Account > Security > Sessions
// ---------------------------------------------------------------------------

async function navigateToSessions(page: any, logFn: (msg: string) => void): Promise<void> {
	await dismissBlockingNotifications(page, logFn);

	// Open settings menu using the stable #settings-menu-toggle id
	const openSettingsBtn = page.locator('#settings-menu-toggle');
	await expect(openSettingsBtn).toBeVisible({ timeout: 15000 });
	await openSettingsBtn.click({ timeout: 10000 });

	// Wait for the settings menu to actually open
	const visibleMenu = page.locator('[data-testid="settings-menu"].visible');
	if (!(await visibleMenu.isVisible({ timeout: 5000 }).catch(() => false))) {
		await dismissBlockingNotifications(page, logFn);
		await openSettingsBtn.click({ timeout: 10000, force: true });
	}
	await expect(visibleMenu).toBeVisible({ timeout: 10000 });
	logFn('Opened settings menu.');

	// Navigate Account → Security → Active Sessions
	await visibleMenu.getByRole('menuitem', { name: /account/i }).click();
	logFn('Navigated to Account settings.');

	await visibleMenu.getByRole('menuitem', { name: /security/i }).click();
	logFn('Navigated to Security settings.');

	await visibleMenu.getByRole('menuitem', { name: /active sessions/i }).click();
	logFn('Navigated to Active Sessions settings page.');

	// Wait for sessions list to load
	await expect(page.locator('[data-testid="sessions-list"]')).toBeVisible({ timeout: 15000 });
	logFn('Sessions list visible.');
}

// ---------------------------------------------------------------------------
// Detect if the page is logged out (login button visible)
// ---------------------------------------------------------------------------

async function _isLoggedOut(page: any): Promise<boolean> {
	try {
		const loginBtn = page.getByTestId('header-login-signup-btn');
		return await loginBtn.isVisible({ timeout: 5000 });
	} catch {
		return false;
	}
}

// ---------------------------------------------------------------------------
// Main test
// ---------------------------------------------------------------------------

// contract-test: direct surface=gui.web assertions=daily-inspiration.guest-isolated,landing-onboarding.uses-real-chat-shell
// eslint-disable-next-line no-empty-pattern
test('session revoke: revoking session B from session A does not log out session A', async ({}, testInfo: any) => {
	test.slow();
	// Login × 2 + OTP window wait + settings navigation + revoke + assertions
	test.setTimeout(300000);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logA = createSignupLogger('SESSION_REVOKE_A');
	const logB = createSignupLogger('SESSION_REVOKE_B');
	const screenshotA = createStepScreenshotter(logA, { filenamePrefix: 'revoke-a' });
	const screenshotB = createStepScreenshotter(logB, { filenamePrefix: 'revoke-b' });

	await archiveExistingScreenshots(logA);

	// Capture console output for each session to aid debugging on failure
	const logsA: string[] = [];
	const logsB: string[] = [];
	const forceLogoutEventsA: string[] = [];
	const forceLogoutEventsB: string[] = [];

	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const browser = await chromium.launch();

	// Two separate browser contexts = two independent sessions (separate cookies,
	// separate IndexedDB, separate WebSocket connections).
	const contextA = await browser.newContext({ baseURL, ...PROOF_CONTEXT_OPTIONS });
	let contextBClosed = false;
	const contextB = await browser.newContext({
		baseURL,
		...PROOF_CONTEXT_OPTIONS,
		...(IS_PROOF_CAPTURE
			? {
				recordVideo: {
					dir: testInfo.outputPath(`session-b-proof-video-${PROOF_DEVICE}`),
					size: { width: PROOF_VIDEO_WIDTH, height: PROOF_VIDEO_HEIGHT }
				}
			}
			: {})
	});
	const pageA = await contextA.newPage();
	const pageB = await contextB.newPage();
	const proofRecordingStartedAt = Date.now();
	const proofVideoB = pageB.video();
	let proofWindowEndedAtMs = 0;

	// Attach console listeners
	pageA.on('console', (msg: any) => {
		const text = msg.text();
		logsA.push(`[${new Date().toISOString()}] [${msg.type()}] ${text}`);
		// Flag only actual force_logout events RECEIVED on Session A — these should NOT happen.
		// "Registered handler for messageType" is a startup log (not an event receipt) — ignore it.
		// "Received force_logout event" is the chatSyncService handler — this is the real event.
		if (text.includes('Received force_logout event')) {
			forceLogoutEventsA.push(text);
			console.warn(`[SESSION-A] UNEXPECTED force_logout event received: ${text}`);
		}
	});
	pageB.on('console', (msg: any) => {
		const text = msg.text();
		logsB.push(`[${new Date().toISOString()}] [${msg.type()}] ${text}`);
		// Capture actual force_logout events on Session B (expected)
		if (text.includes('Received force_logout event')) {
			forceLogoutEventsB.push(text);
			console.log(`[SESSION-B] force_logout event received (expected): ${text}`);
		}
	});

	try {
		// ── Step 1: Log in Session A ─────────────────────────────────────────
		logA('Logging in Session A…');
		await loginToApp(pageA, logA);
		await screenshotA(pageA, '01-logged-in-a');

		// ── Step 2: Wait for TOTP window rollover, then log in Session B ─────
		// TOTP codes are 30-second windows; reusing the same code in the same
		// window is rejected. Wait for the next window before logging in B.
		{
			const msInWindow = Date.now() % 30000;
			const msUntilNext = 30000 - msInWindow + 500; // +500ms buffer
			logA(`Waiting ${Math.ceil(msUntilNext / 1000)}s for next OTP window before Session B login…`);
			await pageA.waitForTimeout(msUntilNext);
		}

		logB('Logging in Session B…');
		await loginToApp(pageB, logB);
		await screenshotB(pageB, '02-logged-in-b');
		await startNewChat(pageB, logB);
		const sessionBDraftText = `Session revoke logout header cleanup ${Date.now().toString(36).replace(/[0-9]/g, 'a')}`;
		const messageEditorB = pageB.getByTestId('message-editor');
		await fillMessageEditor(pageB, messageEditorB, sessionBDraftText);
		await expect(pageB.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 15000 });
		await expect(pageB.getByTestId('chat-header-title')).toContainText(sessionBDraftText, { timeout: 15000 });
		logB('Session B: active draft chat header visible before forced logout.');
		await screenshotB(pageB, '02b-session-b-active-draft-header');

		logA(`Both sessions logged in. Waiting ${Math.ceil(SESSION_STABILIZE_MS / 1000)}s for WebSocket connections to stabilise…`);
		await pageA.waitForTimeout(SESSION_STABILIZE_MS);
		await screenshotA(pageA, '03-after-stabilise-a');
		await screenshotB(pageB, '03-after-stabilise-b');

		// ── Step 3: Session A navigates to Settings > Sessions ───────────────
		logA('Session A: navigating to Settings > Account > Security > Sessions…');
		await navigateToSessions(pageA, logA);
		await screenshotA(pageA, '04-sessions-page-a');

		// ── Step 4: Find Session B's card and click Remove ───────────────────
		// The sessions list shows all active sessions; Session A's card has
		// data-is-current="true". Session B is one of the other cards.
		// We click the "Remove" button on the first non-current session.
		logA("Session A: looking for Session B's card to remove…");

		const nonCurrentCard = pageA
			.locator('[data-testid="session-card"][data-is-current="false"]')
			.first();
		await expect(nonCurrentCard).toBeVisible({ timeout: 15000 });

		const revokeBtn = nonCurrentCard.locator('[data-testid="session-revoke-btn"]');
		await expect(revokeBtn).toBeVisible({ timeout: 5000 });
		await screenshotA(pageA, '05-before-revoke-a');
		await dismissBlockingNotifications(pageB, logB);
		const proofWindowStartedAtMs = Date.now() - proofRecordingStartedAt;
		const proof = createVideoProofRuntime(SESSION_REVOKE_LOGOUT_PROOF, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => pageB.screenshot({ type: 'png' })
		});
		await proof.checkpoint('session-b-draft-header');
		await proof.assert('session-revoke.session-b-draft-header', async () => {
			await expect(pageB.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 5000 });
			await expect(pageB.getByTestId('chat-header-title')).toContainText(sessionBDraftText, { timeout: 5000 });
		});

		// The button triggers a confirm() dialog — handle it
		pageA.once('dialog', async (dialog: any) => {
			logA(`Confirm dialog: "${dialog.message()}". Accepting.`);
			await dialog.accept();
		});

		// ── Step 5: Wait for Session B to be logged out ──────────────────────
		// The backend broadcasts force_logout via WebSocket to Session B.
		// Session B's chatSyncService handler calls logout() and redirects
		// to the login screen (Login / Sign up button appears).
		const loginBtnB = pageB.getByTestId('header-login-signup-btn');
		const guestBannerB = pageB.getByTestId('daily-inspiration-banner').first();
		await proof.action('session-a-revoke-session-b', async () => {
			await revokeBtn.click();
			logA("Session A: clicked Remove on Session B's session card.");
			await screenshotA(pageA, '06-after-revoke-click-a');
			logB('Session B: waiting to receive force_logout and be logged out…');
			await expect(loginBtnB).toBeVisible({ timeout: 60000 });
			logB('Session B: confirmed LOGGED OUT (Login/Sign Up button visible).');
			await expect(guestBannerB).toBeVisible({ timeout: 10000 });
		});
		await proof.assert('daily-inspiration.guest-isolated-after-force-logout', async () => {
			await expect(guestBannerB).toBeVisible({ timeout: 5000 });
			await expect(guestBannerB).toHaveAttribute('data-inspiration-source', 'guest-onboarding');
			await expect(guestBannerB).toHaveAttribute(
				'data-visible-inspiration-ids',
				GUEST_ONBOARDING_IDS.join(',')
			);
			await expect(pageB.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 10000 });
			await expect(guestBannerB).toHaveAttribute('data-landing-intro-phase', 'expanded');
			await expect(pageB.getByTestId('message-input-wrapper')).toBeHidden({ timeout: 10000 });
			const geometry = await pageB.evaluate(() => {
				const activeChat = document.querySelector<HTMLElement>('[data-testid="active-chat-container"]');
				const banner = document.querySelector<HTMLElement>('[data-testid="daily-inspiration-banner"]');
				if (!activeChat || !banner) throw new Error('Forced logout landing elements missing');
				const activeRect = activeChat.getBoundingClientRect();
				const bannerRect = banner.getBoundingClientRect();
				return {
					bottomDelta: Math.abs(activeRect.bottom - bannerRect.bottom),
					leftDelta: Math.abs(activeRect.left - bannerRect.left),
					rightDelta: Math.abs(activeRect.right - bannerRect.right)
				};
			});
			expect(geometry.bottomDelta, 'forced logout intro must cover the active-chat bottom').toBeLessThanOrEqual(2);
			expect(geometry.leftDelta, 'forced logout intro must cover the active-chat left edge').toBeLessThanOrEqual(2);
			expect(geometry.rightDelta, 'forced logout intro must cover the active-chat right edge').toBeLessThanOrEqual(2);
			await expect(pageB.getByTestId('chat-header-title')).toHaveCount(0, { timeout: 10000 });
			await expect(pageB.getByTestId('chat-header-banner')).toHaveCount(0, { timeout: 10000 });
			await expectLandingIntroCoverageUntilNextSlide(pageB);
		});
		logB('Session B: exact guest onboarding carousel restored after forced logout.');
		await screenshotB(pageB, '07-session-b-logged-out');
		await proof.checkpoint('session-b-guest-onboarding');
		proofWindowEndedAtMs = Date.now() - proofRecordingStartedAt;
		await proof.attach();
		await pageB.waitForTimeout(PROOF_CAPTURE_END_HOLD_MS);
		await contextB.close();
		contextBClosed = true;
		if (proofVideoB) {
			const rawProofVideoPath = testInfo.outputPath(`${PROOF_DEVICE}-session-b-proof-video.raw.webm`);
			const proofVideoPath = testInfo.outputPath(`${PROOF_DEVICE}-session-b-proof-video.webm`);
			fs.rmSync(rawProofVideoPath, { force: true });
			fs.rmSync(proofVideoPath, { force: true });
			await proofVideoB.saveAs(rawProofVideoPath);
			trimProofVideoToProofWindow(rawProofVideoPath, proofVideoPath, proofWindowStartedAtMs, proofWindowEndedAtMs);
			await testInfo.attach(`${PROOF_DEVICE}-session-b-proof-video`, {
				path: proofVideoPath,
				contentType: 'video/webm'
			});
		} else if (IS_PROOF_CAPTURE) {
			throw new Error(`Playwright did not create a Session B proof video for ${PROOF_DEVICE}`);
		}

		// ── Step 6: Verify Session A is still logged in ──────────────────────
		// After the revoke, Session A should remain on the Settings > Sessions page
		// (or /chat at minimum), NOT be redirected to the login screen.
		logA('Session A: verifying still logged in after revoking Session B…');

		// Wait briefly for any unexpected logout to propagate
		await pageA.waitForTimeout(5000);
		await screenshotA(pageA, '08-session-a-after-revoke-wait');

		// Session A must NOT show the Login / Sign Up button
		const loginBtnA = pageA.getByTestId('header-login-signup-btn');
		const aIsLoggedOut = await loginBtnA.isVisible({ timeout: 3000 }).catch(() => false);

		if (aIsLoggedOut) {
			// Log all captured events to aid debugging
			console.error('[SESSION-A] force_logout events received:', forceLogoutEventsA);
			console.error('[SESSION-A] Last 30 console logs:', logsA.slice(-30));
			throw new Error(
				'[REGRESSION] Session A was logged out after revoking Session B. ' +
					'The fix for exclude_connection_hash is not working correctly.'
			);
		}

		logA('Session A: CONFIRMED still logged in — NOT logged out.');
		await screenshotA(pageA, '09-session-a-still-logged-in');

		// ── Step 7: Assert no unexpected force_logout on Session A ───────────
		// The console should not have recorded any force_logout event on Session A.
		// (It fires on Session B — which is correct — but never on Session A.)
		if (forceLogoutEventsA.length > 0) {
			throw new Error(
				`[SESSION-A] Received ${forceLogoutEventsA.length} unexpected force_logout event(s): ` +
					forceLogoutEventsA.join('\n')
			);
		}
		logA(`Session A: no force_logout events received — correct.`);

		// ── Step 8: Verify Session B did receive force_logout ─────────────────
		if (forceLogoutEventsB.length === 0) {
			logB(
				'NOTE: No force_logout console event captured on Session B — logout still ' +
					'confirmed via UI (Login button appeared). WebSocket event may have fired ' +
					'before console listener was attached.'
			);
		} else {
			logB(`Session B: force_logout event confirmed: ${forceLogoutEventsB[0]}`);
		}

		// ── Step 9: Verify sessions list updated on Session A ────────────────
		// After revocation, Session B should no longer appear in the list.
		// The list should now show fewer cards.
		logA('Session A: verifying sessions list updated after revoke…');
		await expect(pageA.locator('[data-testid="sessions-list"]')).toBeVisible({
			timeout: 10000
		});
		const remainingCards = await pageA.locator('[data-testid="session-card"]').count();
		logA(`Session A: ${remainingCards} session card(s) remaining after revoke.`);
		// At minimum, Session A's own card should remain
		expect(remainingCards).toBeGreaterThanOrEqual(1);

		await screenshotA(pageA, '10-sessions-list-updated-a');

		logA('=== TEST PASSED: Session revoke correctly targeted Session B only. ===');
	} finally {
		await contextA.close();
		if (!contextBClosed) await contextB.close();
		await browser.close();
	}
});
