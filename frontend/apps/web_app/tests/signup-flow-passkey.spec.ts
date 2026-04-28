/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. We avoid extra dependencies
// and keep the flow aligned with the existing password-based signup test.
const { test, expect } = require('./helpers/cookie-audit');
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
	fillStripeCardDetails,
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
 * - The virtual authenticator automatically handles PRF extension requests during credential creation.
 * - If PRF is not supported, the app will detect this and show the PRF error screen.
 *
 * REQUIRED ENV VARS:
 * - SIGNUP_TEST_EMAIL_DOMAINS: Comma-separated list of allowed test domains.
 * - GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN: Gmail API credentials (preferred).
 * - MAILOSAUR_API_KEY / MAILOSAUR_SERVER_ID: Mailosaur credentials (fallback).
 */

const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const STRIPE_TEST_CARD_NUMBER = '4000002760000016';

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
			transport: 'internal',
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

test('completes passkey signup flow with email + purchase', async ({
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
	// Allow extra time for passkey registration + purchase confirmation email.
	// GHA runners are slower — 240s was insufficient; 420s provides comfortable margin.
	test.setTimeout(420000);

	const logSignupCheckpoint = createSignupLogger('SIGNUP_PASSKEY');
	const takeStepScreenshot = createStepScreenshotter(logSignupCheckpoint, {
		filenamePrefix: 'passkey'
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
	const { waitForMailosaurMessage, extractSixDigitCode, extractRefundLink, extractMessageLinks } =
		emailClient!;

	// Grant clipboard permissions so "Copy" actions can be exercised reliably.
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	// Base URL comes from PLAYWRIGHT_TEST_BASE_URL or the default in config.
	await page.goto(getE2EDebugUrl('/'));
	await takeStepScreenshot(page, 'home');

	const { client, authenticatorId } = await setupVirtualPasskeyAuthenticator(context, page);
	try {
		logSignupCheckpoint('Virtual authenticator configured for passkey flow.');

		const signupEmail = buildSignupEmail(signupDomain);
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
		const githubLink = page.locator('a[href*="github.com"]');
		const instagramLink = page.locator('a[href*="instagram.com"]');
		await expect(githubLink.first()).toBeVisible();
		await expect(instagramLink.first()).toBeVisible();

		await page.getByRole('button', { name: /continue/i }).click();
		await takeStepScreenshot(page, 'basics-step');
		logSignupCheckpoint('Reached basics step.');

		// Basics step: fill email/username and exercise key toggles.
		const emailInput = page.locator('input[type="email"][autocomplete="email"]');
		const usernameInput = page.locator('input[autocomplete="username"]');
		await expect(emailInput).toBeVisible({ timeout: 10000 });
		await emailInput.fill(signupEmail);
		await usernameInput.fill(signupUsername);
		await takeStepScreenshot(page, 'basics-filled');

		// Toggle "Stay logged in" on (explicitly test toggle wiring).
		const stayLoggedInToggle = page.locator('#stayLoggedIn');
		await setToggleChecked(stayLoggedInToggle, true);
		await expect(stayLoggedInToggle).toBeChecked();

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
		await confirmEmailInput.fill(emailCode);

		// Secure account step: choose passkey-based setup.
		const passkeyOption = page.locator('#signup-passkey-option');
		await expect(passkeyOption).toBeVisible({ timeout: 10000 });
		await takeStepScreenshot(page, 'secure-account');
		await passkeyOption.click();
		logSignupCheckpoint('Selected passkey signup path.');

		// Recovery key step: wait for passkey registration to complete and the next step to appear.
		const recoveryDownloadButton = page.locator('#signup-recovery-key-download');
		await expect(recoveryDownloadButton).toBeVisible({ timeout: 10000 });
		await takeStepScreenshot(page, 'recovery-key');
		logSignupCheckpoint('Reached recovery key step after passkey registration.');

		// Recovery key step: download, copy, print, and confirm stored.
		const [recoveryDownload] = await Promise.all([
			page.waitForEvent('download'),
			recoveryDownloadButton.click()
		]);
		expect(await recoveryDownload.suggestedFilename()).toMatch(/recovery/i);
		logSignupCheckpoint('Downloaded recovery key.');

		const recoveryCopyButton = page.locator('#signup-recovery-key-copy');
		await recoveryCopyButton.click();

		const [printPage] = await Promise.all([
			context.waitForEvent('page'),
			page.locator('#signup-recovery-key-print').click()
		]);
		await printPage.close();
		await takeStepScreenshot(page, 'recovery-key-actions');
		logSignupCheckpoint('Completed recovery key actions.');

		const recoveryConfirmToggle = page.locator('#confirm-storage-toggle-step5');
		await setToggleChecked(recoveryConfirmToggle, true);
		await takeStepScreenshot(page, 'credits-step');
		logSignupCheckpoint('Reached credits step.');

		// Credits step: exercise gift card path (cancel) and navigation buttons.
		const giftCardButton = page.locator('#signup-credits-gift-card');
		await giftCardButton.scrollIntoViewIfNeeded();
		await giftCardButton.click();
		await takeStepScreenshot(page, 'credits-giftcard');
		await page.locator('#signup-gift-card-cancel').click();
		await takeStepScreenshot(page, 'credits-ready');
		logSignupCheckpoint('Completed credits step actions.');

		const moreButton = page.locator('#signup-credits-more');
		const lessButton = page.locator('#signup-credits-less');
		if (await moreButton.isVisible()) {
			await moreButton.click();
		}
		if (await lessButton.isVisible()) {
			await lessButton.click();
		}

		// Purchase credits to proceed to payment step.
		await page.getByTestId('credits-package').getByTestId('buy-button').first().click();
		await takeStepScreenshot(page, 'payment-consent');
		logSignupCheckpoint('Reached payment consent step.');

		// Payment step: consent to limited refund to reveal payment form.
		// Dismiss consent overlay BEFORE switching providers (it blocks pointer events).
		const consentToggle = page.locator('#limited-refund-consent-toggle');
		await setToggleChecked(consentToggle, true);
		logSignupCheckpoint('Payment consent accepted.');

		// GHA runners are in the US, so Stripe Managed Payments is auto-selected (non-EU IP).
		// Switch to Stripe EU card mode for this test — it specifically tests the Stripe payment flow.
		const switchToStripeBtn = page.getByTestId('switch-to-stripe');
		if (await switchToStripeBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
			await switchToStripeBtn.click();
			logSignupCheckpoint('Switched from Managed Payments to Stripe EU card payment.');
		}

		// Wait for Stripe Payment Element iframe to load after provider switch.
		const stripeIframe = page.frameLocator('iframe[title="Secure payment input frame"]');
		const cardInputWait = stripeIframe
			.locator('input[name="number"], input[name="cardNumber"], input[autocomplete="cc-number"]')
			.first();
		await cardInputWait.waitFor({ state: 'visible', timeout: 30000 });
		logSignupCheckpoint('Stripe Payment Element loaded.');

		await takeStepScreenshot(page, 'payment-form');

		// Fill Stripe payment element with the test card.
		await fillStripeCardDetails(page, STRIPE_TEST_CARD_NUMBER);
		logSignupCheckpoint('Filled Stripe card details.');

		// Wait for Stripe to validate the card (buy button enabled).
		const buyButton = page.getByTestId('payment-form').getByTestId('buy-button');
		await expect(buyButton).toBeEnabled({ timeout: 10000 });

		// Submit payment and wait for success.
		const paymentSubmittedAt = new Date().toISOString();
		await buyButton.click();
		await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 60000 });
		await takeStepScreenshot(page, 'payment-success');
		logSignupCheckpoint('Purchase completed successfully.');

		// Auto top-up step: finish setup and confirm redirect into the app.
		await page.getByTestId('signup-finish-setup').first().click();
		await page.waitForURL(/chat/);
		await takeStepScreenshot(page, 'chat');
		logSignupCheckpoint('Arrived in chat after passkey signup.');

		// Verify no missing translations on the main chat page after signup
		await assertNoMissingTranslations(page);
		logSignupCheckpoint('No missing translations detected.');

		// Purchase confirmation email: verify key content and refund link.
		logSignupCheckpoint('Waiting for purchase confirmation email.');
		const purchaseEmail = await waitForMailosaurMessage({
			sentTo: signupEmail,
			subjectContains: 'Purchase confirmation',
			receivedAfter: paymentSubmittedAt,
			timeoutMs: 180000
		});
		logSignupCheckpoint('Received purchase confirmation email.');

		const purchaseText = purchaseEmail.text?.body || '';
		expect(purchaseText).toMatch(/thanks for your purchase/i);
		expect(purchaseText).toMatch(/invoice/i);

		const refundLink = extractRefundLink(purchaseEmail);
		if (!refundLink) {
			const allLinks = extractMessageLinks(purchaseEmail);
			logSignupCheckpoint('Refund link missing from purchase email.', {
				linkCount: allLinks.length,
				links: allLinks.slice(0, 10),
				textSnippet: purchaseText.slice(0, 300)
			});
		}
		expect(refundLink, 'Expected a refund link in the purchase confirmation email.').toBeTruthy();
		if (!refundLink) {
			throw new Error('Refund link missing from purchase confirmation email.');
		}
		expect(() => new URL(refundLink)).not.toThrow();
		logSignupCheckpoint('Validated refund link from purchase email.', {
			refundLink: refundLink.slice(0, 120)
		});

		// Open settings to verify credit balance and delete the test account.
		const settingsMenuButton = page.getByTestId('profile-container');
		await settingsMenuButton.click();
		await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible();
		await takeStepScreenshot(page, 'settings-menu-open');
		logSignupCheckpoint('Opened settings menu for credit verification.');

		// Confirm credits reflect the purchase (should be non-zero after payment).
		const creditsAmount = page.getByTestId('credits-amount');
		await expect(creditsAmount).toBeVisible({ timeout: 10000 });
		const creditsText = (await creditsAmount.textContent()) || '';
		const creditsValue = Number.parseInt(creditsText.replace(/[^\d]/g, ''), 10);
		expect(creditsValue, 'Expected purchased credits to be visible in settings.').toBeGreaterThan(
			0
		);
		logSignupCheckpoint('Verified purchased credits in settings.', { creditsValue, creditsText });

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

		// Start deletion and complete passkey authentication (auto-starts).
		await page.getByTestId('delete-account-container').getByTestId('delete-button').click();
		const authModal = page.getByTestId('auth-modal');
		await expect(authModal).toBeVisible();
		await takeStepScreenshot(page, 'delete-account-auth');
		logSignupCheckpoint('Passkey auth modal opened for deletion.');

		// Wait for deletion success after passkey authentication completes.
		await expect(page.getByTestId('delete-account-container').getByTestId('success-message')).toBeVisible({
			timeout: 10000
		});
		await takeStepScreenshot(page, 'delete-account-success');
		logSignupCheckpoint('Account deletion confirmed via passkey.');

		// Confirm logout redirect to demo chat after deletion.
		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 10000
		});
		logSignupCheckpoint('Returned to demo chat after account deletion.');
	} finally {
		await teardownVirtualPasskeyAuthenticator(client, authenticatorId);
	}
});
