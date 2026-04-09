/*
Purpose: End-to-end smoke test of the cold-boot signup journey on LIVE
         production. One unified flow per hourly tick:
           signup → gift card → first chat (PONG)
           → logout → login (no 2FA)
           → verify first chat history still loads (E2EE key restore)
           → second chat (PING)
           → delete account.
         Zero real money is burned because the gift card bypasses Stripe.
Architecture: Part of the hourly prod smoke suite (OPE-76). This is the ONLY
              auth+chat prod-smoke spec — it replaces the previous split of
              prod-smoke-signup-giftcard-chat + prod-smoke-login-chat, because
              covering signup, login, and chat-history decryption in one run
              gives us a cleaner single failure signature for alerting, and
              removes the need for a persistent prod test account.
              Relies on the reusable + allowed_email_domain extension to
              gift_cards — the card is locked to our specific Mailosaur server
              subdomain so no other Mailosaur user can redeem it.
Tests: N/A (this file is the Playwright E2E test entrypoint).

Required env vars:
- PLAYWRIGHT_TEST_BASE_URL         — prod base URL
- SIGNUP_TEST_EMAIL_DOMAINS        — comma-separated; first entry is used
                                     (must exactly match the card's
                                     allowed_email_domain — e.g.
                                     xyz9abc1.mailosaur.net)
- MAILOSAUR_API_KEY, MAILOSAUR_SERVER_ID
- PROD_SMOKE_GIFT_CARD_CODE        — the reusable card seeded once via the
                                     admin generate-gift-cards endpoint
*/
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('../helpers/cookie-audit');
const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-20).forEach((log) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	setToggleChecked,
	getSignupTestDomain,
	getMailosaurServerId,
	buildSignupEmail,
	createMailosaurClient,
	assertNoMissingTranslations,
	getE2EDebugUrl
} = require('../signup-flow-helpers');

const PROD_BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
const MAILOSAUR_API_KEY = process.env.MAILOSAUR_API_KEY;
const MAILOSAUR_SERVER_ID = process.env.MAILOSAUR_SERVER_ID;
const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const PROD_SMOKE_GIFT_CARD_CODE = process.env.PROD_SMOKE_GIFT_CARD_CODE;

test.beforeAll(() => {
	if (!PROD_BASE_URL) {
		throw new Error('PLAYWRIGHT_TEST_BASE_URL must be set for prod-smoke specs.');
	}
	if (/localhost|dev\./i.test(PROD_BASE_URL)) {
		throw new Error(
			`PLAYWRIGHT_TEST_BASE_URL looks like a dev URL (${PROD_BASE_URL}). ` +
				'Prod smoke specs must run against production.'
		);
	}
});

test('prod signup + gift card redemption + first chat + account delete', async ({
	page,
	context
}: {
	page: any;
	context: any;
}) => {
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		networkActivities.push(`[${new Date().toISOString()}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	// End-to-end signup + Mailosaur polling + gift card + first chat — plenty
	// of margin without being a timeout sink.
	test.setTimeout(600000);

	const logCheckpoint = createSignupLogger('PROD_SMOKE_SIGNUP_GIFTCARD');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'prod-smoke-signup'
	});
	await archiveExistingScreenshots(logCheckpoint);

	const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
	test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');
	test.skip(!MAILOSAUR_API_KEY, 'MAILOSAUR_API_KEY is required.');
	test.skip(!PROD_SMOKE_GIFT_CARD_CODE, 'PROD_SMOKE_GIFT_CARD_CODE must be set.');
	if (!signupDomain || !MAILOSAUR_API_KEY || !PROD_SMOKE_GIFT_CARD_CODE) {
		throw new Error('Missing required env vars after skip guards.');
	}

	const mailosaurServerId = getMailosaurServerId(signupDomain, MAILOSAUR_SERVER_ID);
	if (!mailosaurServerId) {
		throw new Error(
			'MAILOSAUR_SERVER_ID is missing and could not be derived from the signup domain.'
		);
	}

	const { waitForMailosaurMessage, extractSixDigitCode } = createMailosaurClient({
		apiKey: MAILOSAUR_API_KEY,
		serverId: mailosaurServerId
	});

	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	const signupEmail = buildSignupEmail(signupDomain);
	const signupUsername = signupEmail.split('@')[0];
	const signupPassword = 'ProdSmoke!2345Secure';
	logCheckpoint('Generated fresh signup email.', { signupEmail });

	// ─── STEP 1: Signup with email + password, skip 2FA ───────────────────
	await page.goto(getE2EDebugUrl('/'));
	await takeStepScreenshot(page, 'home');

	const headerLoginSignupButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginSignupButton).toBeVisible({ timeout: 15000 });
	await headerLoginSignupButton.click();

	const loginTabs = page.getByTestId('login-tabs');
	await expect(loginTabs).toBeVisible({ timeout: 10000 });
	await loginTabs.getByRole('button', { name: /sign up/i }).click();
	await takeStepScreenshot(page, 'signup-alpha');
	await assertNoMissingTranslations(page);

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'basics-step');

	const emailInput = page.locator('input[type="email"][autocomplete="email"]');
	const usernameInput = page.locator('input[autocomplete="username"]');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(signupEmail);
	await usernameInput.fill(signupUsername);

	const termsToggle = page.locator('#terms-agreed-toggle');
	const privacyToggle = page.locator('#privacy-agreed-toggle');
	await setToggleChecked(termsToggle, true);
	await setToggleChecked(privacyToggle, true);

	const emailRequestedAt = new Date().toISOString();
	await page.getByRole('button', { name: /create new account/i }).click();

	// Wait for the "open mail" link, which signals the confirmation email has
	// been dispatched.
	const openMailLink = page.getByRole('link', { name: /open mail app/i });
	await expect(openMailLink).toBeVisible({ timeout: 20000 });

	// Poll Mailosaur for the verification message. This is the slowest part of
	// the flow — budget up to 90s.
	const confirmEmailMessage = await waitForMailosaurMessage({
		sentTo: signupEmail,
		receivedAfter: emailRequestedAt
	});
	const emailCode = extractSixDigitCode(confirmEmailMessage);
	expect(emailCode, 'Expected a 6-digit email confirmation code.').toBeTruthy();

	const confirmEmailInput = page.locator('input[inputmode="numeric"][maxlength="6"]');
	await confirmEmailInput.fill(emailCode);
	logCheckpoint('Filled email confirmation code.');

	// Prefer the password path over passkey — simpler to automate on prod and
	// avoids WebAuthn virtual-authenticator CDP plumbing.
	const passwordOption = page.locator('#signup-password-option');
	await expect(passwordOption).toBeVisible({ timeout: 15000 });
	await passwordOption.click();

	const passwordInputs = page.locator('input[autocomplete="new-password"]');
	await expect(passwordInputs).toHaveCount(2);
	await passwordInputs.nth(0).fill(signupPassword);
	await passwordInputs.nth(1).fill(signupPassword);
	await page.locator('#signup-password-continue').click();

	// Skip 2FA setup.
	const skipForNowButton = page.locator('#signup-nav-skip');
	await expect(skipForNowButton).toBeVisible({ timeout: 20000 });
	await skipForNowButton.click();
	await expect(page.getByText(/be aware before skipping 2fa/i)).toBeVisible({ timeout: 15000 });
	const skipConsentToggle = page.locator('#skip-2fa-consent-toggle');
	await setToggleChecked(skipConsentToggle, true);
	await page.locator('#signup-skip-2fa-continue').click();
	logCheckpoint('Skipped 2FA.');

	// Recovery key step — download + confirm.
	const recoveryDownloadButton = page.locator('#signup-recovery-key-download');
	const [recoveryDownload] = await Promise.all([
		page.waitForEvent('download'),
		recoveryDownloadButton.click()
	]);
	expect(await recoveryDownload.suggestedFilename()).toMatch(/recovery/i);
	const recoveryConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(recoveryConfirmToggle, true);
	logCheckpoint('Recovery key downloaded and confirmed.');

	// ─── STEP 2: Redeem the gift card on the credits step ────────────────
	// The signup credits step has an "I have a gift card" button that swaps the
	// panel to the GiftCardRedeem component (see CreditsTopContent.svelte:159).
	// Redeeming the card fires an event that auto-completes the signup — no
	// Stripe interaction at all.
	await expect(page.getByTestId('credits-package').getByTestId('buy-button').first()).toBeVisible({
		timeout: 30000
	});

	const giftCardButton = page.locator('#signup-credits-gift-card');
	await expect(giftCardButton).toBeVisible({ timeout: 10000 });
	await giftCardButton.click();
	await takeStepScreenshot(page, 'gift-card-input');
	logCheckpoint('Opened gift card input on credits step.');

	// GiftCardRedeem.svelte renders a single text input for the code. Use an
	// input-type selector anchored to the visible gift card panel.
	const giftCardInput = page.locator('input[type="text"]').first();
	await expect(giftCardInput).toBeVisible({ timeout: 10000 });
	await giftCardInput.fill(PROD_SMOKE_GIFT_CARD_CODE);
	logCheckpoint('Entered gift card code.');

	// The redeem button shares the "buy-button" testid with the credits
	// package buy flow — GiftCardRedeem reuses the primary action style.
	// Fall back to a role selector matching the redeem text.
	const redeemButton = page.getByRole('button', { name: /redeem/i });
	await expect(redeemButton).toBeVisible({ timeout: 10000 });
	await redeemButton.click();
	logCheckpoint('Clicked redeem.');

	// After successful redemption the flow auto-advances to the payment step
	// with a "purchase successful" message, then signup finalizes. We wait for
	// the final chat URL as the definitive signal.
	await page.waitForURL(/chat/, { timeout: 120000 });
	logCheckpoint('Signup finalized after gift card redemption.');
	await takeStepScreenshot(page, 'chat-after-signup');

	// ─── STEP 3: Send the first chat and assert an AI response streams in ─
	// Use a deterministic no-tool-call prompt so the test only exercises the
	// LLM path, not skill routing / external APIs.
	const FIRST_PROMPT = 'Reply with just the word: PONG';
	const SECOND_PROMPT = 'Reply with just the word: PING';
	const { startNewChat, sendMessage, waitForAssistantResponse } = require('../helpers/chat-test-helpers');
	await startNewChat(page, (m: string) => logCheckpoint(m));
	await sendMessage(page, FIRST_PROMPT, (m: string) => logCheckpoint(m));
	const firstAssistantMessages = await waitForAssistantResponse(page, 120000);
	await expect(firstAssistantMessages.last()).toBeVisible({ timeout: 120000 });
	await expect(firstAssistantMessages.last()).not.toBeEmpty({ timeout: 60000 });
	logCheckpoint('First chat completed successfully.');
	await takeStepScreenshot(page, 'first-chat-done');

	// ─── STEP 4: Logout via profile menu ─────────────────────────────────
	// Exercises the full sign-out path — clears in-memory keys, closes the
	// websocket, redirects to the demo/marketing page.
	const logoutMenu = page.getByTestId('profile-container');
	await logoutMenu.click();
	await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible({ timeout: 10000 });
	const logoutItem = page.getByRole('menuitem', { name: /logout|abmelden/i });
	await expect(logoutItem).toBeVisible({ timeout: 10000 });
	await logoutItem.click();
	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 60000
	});
	logCheckpoint('Logged out successfully.');
	await takeStepScreenshot(page, 'logged-out');

	// ─── STEP 5: Log back in with email + password (no 2FA) ──────────────
	// Signup skipped 2FA, so login is email → password → authenticated.
	// This is the single most valuable assertion on prod: it proves that the
	// login pipeline works AND that the user's E2EE keys can be restored from
	// IndexedDB so their prior chat decrypts below.
	const loginSignupButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(loginSignupButton).toBeVisible({ timeout: 15000 });
	await loginSignupButton.click();

	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const reloginEmailInput = page.locator('#login-email-input, input[type="email"][name="username"]').first();
	await expect(reloginEmailInput).toBeVisible({ timeout: 15000 });
	await reloginEmailInput.fill(signupEmail);
	await page.getByRole('button', { name: /continue|next/i }).click();

	const reloginPasswordInput = page.locator('#login-password-input').first();
	await expect(reloginPasswordInput).toBeVisible({ timeout: 15000 });
	await reloginPasswordInput.fill(signupPassword);

	// No 2FA was set up, so the OTP input must NOT appear. Asserting its
	// absence catches regressions where a no-2FA account is accidentally
	// routed through the OTP-required code path.
	await expect(page.locator('#login-otp-input').first()).not.toBeVisible();

	const reloginSubmit = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(reloginSubmit).toBeVisible({ timeout: 15000 });
	await reloginSubmit.click();
	await page.waitForURL(/chat/, { timeout: 60000 });
	logCheckpoint('Re-login with password completed. No 2FA was requested.');
	await takeStepScreenshot(page, 'after-relogin');

	// ─── STEP 6: Verify the first chat is still there and decrypts ───────
	// Open the sidebar (closed by default at the test viewport), click the
	// most recent chat item, and assert the original user prompt is visible
	// in the chat view. A visible prompt means:
	//   (a) the chat row synced back from the server,
	//   (b) the user vault key was re-derived on login,
	//   (c) per-chat keys unwrapped successfully,
	//   (d) messages decrypted to plaintext in the DOM.
	// Any broken link in that chain fails this assertion.
	const sidebarToggle = page.getByTestId('sidebar-toggle');
	if (await sidebarToggle.isVisible({ timeout: 5000 }).catch(() => false)) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}
	const firstChatItem = page.locator('[data-testid="chat-item-wrapper"]').first();
	await expect(firstChatItem).toBeVisible({ timeout: 30000 });
	await firstChatItem.click();
	logCheckpoint('Clicked first chat from sidebar after re-login.');

	// The prompt text must appear in the rendered messages area. Scope the
	// check to avoid matching the sidebar chat title preview.
	const restoredPrompt = page.getByTestId('message-user').filter({ hasText: FIRST_PROMPT });
	await expect(restoredPrompt.first()).toBeVisible({ timeout: 30000 });
	logCheckpoint('First chat history restored and decrypted after re-login.');
	await takeStepScreenshot(page, 'history-restored');

	// ─── STEP 7: Start a second chat and confirm streaming still works ───
	await startNewChat(page, (m: string) => logCheckpoint(m));
	await sendMessage(page, SECOND_PROMPT, (m: string) => logCheckpoint(m));
	const secondAssistantMessages = await waitForAssistantResponse(page, 120000);
	await expect(secondAssistantMessages.last()).toBeVisible({ timeout: 120000 });
	await expect(secondAssistantMessages.last()).not.toBeEmpty({ timeout: 60000 });
	logCheckpoint('Second chat (post-relogin) completed successfully.');
	await takeStepScreenshot(page, 'second-chat-done');

	// ─── STEP 8: Delete the account via email OTP ────────────────────────
	// Best-effort: we don't want orphan users piling up on prod. This mirrors
	// the tail of signup-skip-2fa-flow.spec.ts.
	try {
		const settingsMenu = page.getByTestId('profile-container');
		await settingsMenu.click();
		await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible({ timeout: 10000 });
		await page.getByRole('menuitem', { name: /account/i }).click();
		await page.getByRole('menuitem', { name: /delete/i }).click();
		await expect(page.getByTestId('delete-account-container')).toBeVisible({ timeout: 15000 });

		const deleteConfirmToggle = page
			.getByTestId('delete-account-container')
			.locator('input[type="checkbox"]')
			.first();
		await setToggleChecked(deleteConfirmToggle, true);
		await page.getByTestId('delete-account-container').getByTestId('delete-button').click();

		const authModal = page.getByTestId('auth-modal');
		await expect(authModal).toBeVisible({ timeout: 15000 });
		const emailOtpSection = authModal.getByTestId('auth-email-otp');
		await expect(emailOtpSection).toBeVisible({ timeout: 10000 });

		const deleteEmailRequestedAt = new Date().toISOString();
		await emailOtpSection.getByTestId('auth-btn').click();
		const deleteOtpInput = emailOtpSection.locator('input.tfa-input');
		await expect(deleteOtpInput).toBeVisible({ timeout: 30000 });

		const deleteVerificationMessage = await waitForMailosaurMessage({
			sentTo: signupEmail,
			receivedAfter: deleteEmailRequestedAt
		});
		const deleteVerificationCode = extractSixDigitCode(deleteVerificationMessage);
		await deleteOtpInput.fill(deleteVerificationCode);

		await expect(
			page.getByTestId('delete-account-container').getByTestId('success-message')
		).toBeVisible({ timeout: 60000 });
		logCheckpoint('Test account deleted.');
	} catch (cleanupError) {
		// Non-fatal: leave an orphan user rather than failing the smoke test.
		// An orphan accumulation will be visible in prod user count and is
		// bounded to ~11 per day at worst.
		logCheckpoint(`Account cleanup failed (non-fatal): ${cleanupError}`);
	}
});
