/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. We avoid extra dependencies
// and keep the flow aligned with the existing password-based signup test.
const { test, expect } = require('./helpers/cookie-audit');
const consoleLogs: string[] = [];
const networkActivities: string[] = [];
let signupEmailForCleanup: string | null = null;

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
	signupEmailForCleanup = null;
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
		await cleanupFailedSignupAccount(signupEmailForCleanup, console.log, {
			testFile: testInfo.file || 'signup-flow-passkey.spec.ts'
		});
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	setToggleChecked,
	validateSignupInviteIfRequired,
	cleanupFailedSignupAccount,
	getSignupTestDomain,
	buildSignupEmail,
	createEmailClient,
	checkEmailQuota,
	assertNoMissingTranslations,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { openSignupInterface } = require('./helpers/chat-test-helpers');

/**
 * Passkey signup flow test (email verification + passkey registration + purchase).
 *
 * ARCHITECTURE NOTES:
 * - Passkeys require WebAuthn PRF extension support for zero-knowledge encryption.
 * - We rely on Playwright's virtual authenticator via CDP to avoid manual prompts.
 * - The virtual authenticator uses USB transport so the flow covers roaming/security-key
 *   registration, which is the most relevant Linux compatibility path.
 * - The virtual authenticator automatically handles PRF extension requests during credential creation.
 * - If PRF is not supported, the app will detect this and show the PRF error screen.
 *
 * REQUIRED ENV VARS:
 * - SIGNUP_TEST_EMAIL_DOMAINS: Comma-separated list of allowed test domains.
 * - GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN: Gmail API credentials (preferred).
 * - MAILOSAUR_API_KEY / MAILOSAUR_SERVER_ID: Mailosaur credentials (fallback).
 */

const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const PASSKEY_STAY_LOGGED_IN_CASES = [true, false] as const;

/**
 * Attach a virtual authenticator so WebAuthn prompts are satisfied automatically.
 * This keeps the passkey flow fully automated inside Playwright's Chromium runtime.
 */
async function setupVirtualPasskeyAuthenticator(
	context: any,
	page: any
): Promise<{
	client: any;
	authenticatorId: string;
}> {
	const client = await context.newCDPSession(page);
	await client.send('WebAuthn.enable');
	const { authenticatorId } = await client.send('WebAuthn.addVirtualAuthenticator', {
		options: {
			protocol: 'ctap2',
			transport: 'usb',
			hasResidentKey: true,
			hasUserVerification: true,
			isUserVerified: true,
			automaticPresenceSimulation: true,
			// Enable PRF support in the virtual authenticator.
			hasPrf: true
		}
	});
	return { client, authenticatorId };
}

/**
 * Clean up the virtual authenticator after the test completes.
 * This ensures subsequent tests start with a clean WebAuthn state.
 */
async function teardownVirtualPasskeyAuthenticator(
	client: any,
	authenticatorId: string
): Promise<void> {
	if (!client || !authenticatorId) {
		return;
	}
	await client.send('WebAuthn.removeVirtualAuthenticator', { authenticatorId });
	await client.send('WebAuthn.disable');
}

/**
 * NOTE: PRF extension support is not advertised via getClientCapabilities in
 * Playwright's virtual authenticator environment. Instead, the virtual authenticator
 * automatically handles PRF extension requests during credential creation.
 *
 * If PRF is not supported at runtime, the signup flow will detect this and show
 * the PRF error screen, which is also valid behavior to test.
 */

for (const stayLoggedIn of PASSKEY_STAY_LOGGED_IN_CASES) {
test(`completes passkey signup and account deletion with stay logged in ${stayLoggedIn ? 'enabled' : 'disabled'}`, async ({
	page,
	context
}: {
	page: any;
	context: any;
}) => {
	// Listen for console logs
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});

	// Listen for network requests
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});

	// Listen for network responses
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	// Allow extra time for passkey registration and account deletion.
	// GHA runners are slower — 240s was insufficient; 420s provides comfortable margin.
	test.setTimeout(420000);

	const caseLabel = stayLoggedIn ? 'STAY_LOGGED_IN' : 'SESSION_ONLY';
	const logSignupCheckpoint = createSignupLogger(`SIGNUP_PASSKEY_${caseLabel}`);
	const takeStepScreenshot = createStepScreenshotter(logSignupCheckpoint, {
		filenamePrefix: `passkey-${stayLoggedIn ? 'stay-logged-in' : 'session-only'}`
	});

	await archiveExistingScreenshots(logSignupCheckpoint);

	const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
	test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');

	const emailClient = createEmailClient();
	test.skip(!emailClient, 'Email credentials required (GMAIL_* or MAILOSAUR_*).');

	const quota = await checkEmailQuota();
	test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);

	if (!signupDomain) {
		throw new Error('Missing signup test domain after skip guard.');
	}
	const { waitForMailosaurMessage, extractSixDigitCode } = emailClient!;

	// Grant clipboard permissions so "Copy" actions can be exercised reliably.
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	// Base URL comes from PLAYWRIGHT_TEST_BASE_URL or the default in config.
	await page.goto(getE2EDebugUrl('/'));
	await takeStepScreenshot(page, 'home');

	const { client, authenticatorId } = await setupVirtualPasskeyAuthenticator(context, page);
	try {
		logSignupCheckpoint('Virtual authenticator configured for passkey flow.');

		const signupEmail = buildSignupEmail(signupDomain);
		signupEmailForCleanup = signupEmail;
		const emailLocal = signupEmail.split('@')[0];
		const signupUsername = emailLocal.includes('+') ? emailLocal.split('+')[1] : emailLocal;
		logSignupCheckpoint('Initialized passkey signup identity.', { signupEmail });

		// Open the login/signup dialog from the header.
		await openSignupInterface(page);
		await takeStepScreenshot(page, 'login-dialog');
		logSignupCheckpoint('Opened login dialog.');

		// Switch to the signup tab inside the login dialog.
		const loginTabs = page.getByTestId('login-tabs');
		await expect(loginTabs).toBeVisible();
		await loginTabs.getByRole('button', { name: /sign up/i }).click();
		await takeStepScreenshot(page, 'signup-alpha');

		// Alpha disclaimer: verify outbound links exist and continue.
		const githubLink = page.getByTestId('signup-alpha-github-link');
		const instagramLink = page.getByTestId('signup-alpha-instagram-link');
		await expect(githubLink).toBeVisible();
		await expect(instagramLink).toBeVisible();

		await page.getByRole('button', { name: /continue/i }).click();
		await takeStepScreenshot(page, 'basics-step');
		logSignupCheckpoint('Reached basics step.');

		await validateSignupInviteIfRequired(page, logSignupCheckpoint);

		// Basics step: fill email/username and exercise key toggles.
		const usernameInput = page.locator('input[autocomplete="username"]');
		await expect(usernameInput).toBeVisible({ timeout: 10000 });
		const emailInput = page.locator('input[type="email"][autocomplete="email"]');
		await expect(emailInput).toBeVisible({ timeout: 10000 });
		await emailInput.fill(signupEmail);
		await usernameInput.fill(signupUsername);
		await takeStepScreenshot(page, 'basics-filled');

		// Explicitly exercise both long-lived and session-only passkey signup.
		const stayLoggedInToggle = page.locator('#stayLoggedIn');
		await setToggleChecked(stayLoggedInToggle, stayLoggedIn);
		if (stayLoggedIn) {
			await expect(stayLoggedInToggle).toBeChecked();
		} else {
			await expect(stayLoggedInToggle).not.toBeChecked();
		}

		// Toggle newsletter on then off so we test the control without sending a subscription.
		const newsletterToggle = page.locator('#newsletter-subscribe-toggle');
		await setToggleChecked(newsletterToggle, true);
		await expect(newsletterToggle).toBeChecked();
		await setToggleChecked(newsletterToggle, false);
		await expect(newsletterToggle).not.toBeChecked();

		// Terms and privacy consent are required to proceed.
		const termsToggle = page.locator('#terms-agreed-toggle');
		const privacyToggle = page.locator('#privacy-agreed-toggle');
		await setToggleChecked(termsToggle, true);
		await setToggleChecked(privacyToggle, true);
		await expect(termsToggle).toBeChecked();
		await expect(privacyToggle).toBeChecked();

		// Submit signup basics and trigger the confirmation email.
		const emailRequestedAt = new Date().toISOString();
		await page.getByRole('button', { name: /create new account/i }).click();
		logSignupCheckpoint('Submitted signup basics, waiting for email confirmation.');

		// Confirm email step: wait for step transition and verify "Open mail app" link.
		// The step transition may take a moment, so we wait for the link to appear with a longer timeout.
		const openMailLink = page.getByRole('link', { name: /open mail app/i });
		await expect(openMailLink).toBeVisible({ timeout: 10000 });
		await takeStepScreenshot(page, 'confirm-email');
		await expect(openMailLink).toHaveAttribute('href', /^mailto:/i);

		logSignupCheckpoint('Polling Mailosaur for confirmation email.');
		const confirmEmailMessage = await waitForMailosaurMessage({
			sentTo: signupEmail,
			receivedAfter: emailRequestedAt,
			timeoutMs: 60000,
			pollIntervalMs: 3000
		});
		const emailCode = extractSixDigitCode(confirmEmailMessage);
		expect(emailCode, 'Expected a 6-digit email confirmation code.').toBeTruthy();
		logSignupCheckpoint('Received email confirmation code.');

		const confirmEmailInput = page.locator('input[inputmode="numeric"][maxlength="6"]');
		await expect(confirmEmailInput).toBeVisible({ timeout: 10000 });
		await confirmEmailInput.click();
		await confirmEmailInput.pressSequentially(emailCode);

		// Secure account step: choose passkey-based setup.
		const passkeyOption = page.locator('#signup-passkey-option');
		await expect(passkeyOption).toBeVisible({ timeout: 30000 });
		await takeStepScreenshot(page, 'secure-account');
		const passkeyInitiateResponsePromise = page.waitForResponse(
			(response: any) =>
				response.url().includes('/auth/passkey/registration/initiate') &&
				response.request().method() === 'POST'
		);
		await passkeyOption.click();
		const passkeyInitiateResponse = await passkeyInitiateResponsePromise;
		const passkeyInitiateOptions = await passkeyInitiateResponse.json();
		expect(passkeyInitiateOptions.authenticatorSelection?.authenticatorAttachment).toBeFalsy();
		expect(passkeyInitiateOptions.authenticatorSelection?.userVerification).toBe('required');
		logSignupCheckpoint('Selected passkey signup path.');

		// Signup now finishes immediately after account creation; security and billing setup live in Settings.
		await expect(page.getByTestId('profile-container')).toBeVisible({ timeout: 30000 });
		await takeStepScreenshot(page, 'chat');
		logSignupCheckpoint('Arrived in chat after passkey signup.');

		// Verify no missing translations on the main chat page after signup
		await assertNoMissingTranslations(page);
		logSignupCheckpoint('No missing translations detected.');

		// Open settings to delete the test account.
		const settingsMenuButton = page.getByTestId('profile-container');
		await settingsMenuButton.click();
		await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible();
		await takeStepScreenshot(page, 'settings-menu-open');
		logSignupCheckpoint('Opened settings menu for account deletion.');

		// Navigate to Account settings and open delete account flow.
		await page.getByRole('menuitem', { name: /account/i }).click();
		await expect(page.getByRole('menuitem', { name: /delete/i })).toBeVisible();
		await page.getByRole('menuitem', { name: /delete/i }).click();
		await expect(page.getByTestId('delete-account-container')).toBeVisible();
		await takeStepScreenshot(page, 'delete-account');
		logSignupCheckpoint('Opened delete account settings.');

		// Confirm data deletion checkbox to enable deletion.
		const deleteConfirmToggle = page
			.getByTestId('delete-account-container').locator('input[type="checkbox"]')
			.first();
		await expect(deleteConfirmToggle).toBeAttached({ timeout: 10000 });
		await setToggleChecked(deleteConfirmToggle, true);
		await takeStepScreenshot(page, 'delete-account-confirmed');
		logSignupCheckpoint('Confirmed delete account data warning.');

		const passkeyVerifyResponsePromise = page.waitForResponse(
			(response: any) =>
				response.url().includes('/auth/passkey/assertion/verify') &&
				response.request().method() === 'POST',
			{ timeout: 30000 }
		);
		const deleteAccountResponsePromise = page.waitForResponse(
			(response: any) =>
				response.url().includes('/settings/delete-account') &&
				response.request().method() === 'POST',
			{ timeout: 30000 }
		);

		// Start deletion and complete passkey authentication (auto-starts).
		await page.getByTestId('delete-account-container').getByTestId('delete-button').click();
		const authModal = page.getByTestId('auth-modal');
		await expect(authModal).toBeVisible();
		await takeStepScreenshot(page, 'delete-account-auth');
		logSignupCheckpoint('Passkey auth modal opened for deletion.');

		const passkeyVerifyResponse = await passkeyVerifyResponsePromise;
		expect(passkeyVerifyResponse.status()).toBe(200);
		const passkeyVerifyBody = await passkeyVerifyResponse.json();
		expect(passkeyVerifyBody.success).toBe(true);
		logSignupCheckpoint('Passkey assertion verified before account deletion.');

		const deleteAccountResponse = await deleteAccountResponsePromise;
		expect(deleteAccountResponse.status()).toBe(200);
		const deleteAccountBody = await deleteAccountResponse.json();
		expect(deleteAccountBody.success).toBe(true);
		logSignupCheckpoint('Delete account API accepted recent passkey proof.');

		// Wait for deletion success after passkey authentication completes.
		await expect(page.getByTestId('delete-account-container').getByTestId('success-message')).toBeVisible({
			timeout: 10000
		});
		await takeStepScreenshot(page, 'delete-account-success');
		logSignupCheckpoint('Account deletion confirmed via passkey.');

		// Confirm logout after deletion. Logged-out home now clears the chat hash instead of
		// forcing #chat-id=demo-for-everyone. The settings/profile button remains visible
		// as guest chrome, so the Login CTA is the unauthenticated-shell proof.
		await expect(page.getByRole('button', { name: /login/i })).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('profile-container')).toBeVisible({ timeout: 30000 });
		logSignupCheckpoint('Returned to logged-out home after account deletion.');
	} finally {
		await teardownVirtualPasskeyAuthenticator(client, authenticatorId);
	}
});
}
