/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: payment-data-minimization
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.

/**
 * Settings → Buy Credits — Stripe Managed Payments (Checkout Session) flow test.
 *
 * WHAT THIS TESTS:
 * - Logs in with a pre-existing test account.
 * - Opens Settings → Billing → Buy Credits.
 * - Selects a credit tier (first available).
 * - From a non-EU IP (GHA runners are in the US), the backend returns
 *   use_managed_payments=true → Stripe Embedded Checkout (initEmbeddedCheckout,
 *   ui_mode="embedded") loads inside #checkout div.
 * - Fills in the Stripe test card inside the Checkout iframe.
 * - After payment, onComplete fires in-page — NO page redirect.
 * - Verifies "purchase successful" message without page reload.
 * - Verifies managed payment confirmation row in Invoices.
 * - Verifies confirmation email and PDF attachment.
 * - Verifies unused-credit refund flow.
 *
 * ARCHITECTURE NOTES:
 * - Non-EU users are routed to Stripe Managed Payments (not Polar — Polar is removed).
 * - Payment.svelte calls stripe.initEmbeddedCheckout() and mounts into #checkout.
 * - After onComplete, SettingsBuyCreditsPayment waits for payment_completed WebSocket
 *   event, then navigates to confirmation screen.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL (or slot-based variant)
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - Email client credentials (GMAIL_* or MAILOSAUR_*)
 *
 * SKIP CONDITIONS:
 * - Test account env vars are not set.
 * - Email client credentials are not set.
 * - Email quota is reached.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	checkEmailQuota,
	createEmailClient,
	getTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

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
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const PDF_MAGIC_BYTES = '%PDF';

async function expectPdfAttachment(
	emailClient: any,
	message: any,
	filenamePattern: RegExp,
	label: string
): Promise<string> {
	const pdfAttachments = await emailClient.getPdfAttachments(message);
	const matchingPdf = pdfAttachments.find((attachment: any) =>
		filenamePattern.test(attachment.filename)
	);

	expect(matchingPdf, `${label} email must include a matching PDF attachment`).toBeTruthy();
	if (!matchingPdf) {
		throw new Error(`${label} email did not include a matching PDF attachment.`);
	}
	expect(matchingPdf.content.length, `${label} PDF must not be empty`).toBeGreaterThan(1000);
	expect(
		matchingPdf.content.subarray(0, 4).toString('utf-8'),
		`${label} attachment must be a PDF`
	).toBe(PDF_MAGIC_BYTES);
	return matchingPdf.filename;
}

// ---------------------------------------------------------------------------
// Test: Settings → Buy Credits → Stripe Managed Payments (Checkout Session)
// ---------------------------------------------------------------------------
// Runs from a US IP → backend returns use_managed_payments=true → Stripe
// Embedded Checkout (initEmbeddedCheckout, ui_mode="embedded") loads inside
// #checkout div. After payment, onComplete fires in-page — NO page redirect.
// ---------------------------------------------------------------------------

test('settings buy credits: completes Stripe Managed Payments (Checkout Session) flow without page reload', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(720000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);
	page.on('response', (res: any) =>
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`)
	);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const emailClient = createEmailClient(TEST_EMAIL);
	test.skip(!emailClient, 'Email credentials required (GMAIL_* or MAILOSAUR_*).');

	const quota = await checkEmailQuota(TEST_EMAIL);
	test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);

	const log = createSignupLogger('SETTINGS_BUY_CREDITS_MANAGED');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'settings-managed' });
	await archiveExistingScreenshots(log);

	const { deleteAllMessages, waitForMailosaurMessage } = emailClient!;

	// ─── Login ────────────────────────────────────────────────────────────────────
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(4000);

	// ─── Open Settings ───────────────────────────────────────────────────────────
	const profileContainer = page.getByTestId('profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 8000 });
	await expect(
		page.locator('[data-testid="settings-menu"].visible [data-testid="credits-row"]')
	).toBeVisible({ timeout: 15000 });

	// ─── Navigate: Settings → Billing → Buy Credits ───────────────────────────────
	const billingItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /billing/i });
	await billingItem.click();

	const buyCreditsItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /buy credits/i });
	await buyCreditsItem.click();
	log('Navigated to Buy Credits.');

	await expect(async () => {
		const tierItems = page.locator(
			'[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]'
		);
		expect(await tierItems.count()).toBeGreaterThanOrEqual(3);
	}).toPass({ timeout: 15000 });

	await deleteAllMessages();
	log('Email inbox prepared for managed payment messages.');

	// ─── Select first pricing tier ────────────────────────────────────────────────
	const firstTier = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.first();
	await firstTier.click();
	log('Selected first pricing tier.');
	await screenshot(page, 'tier-selected');

	// ─── Wait for Stripe Embedded Checkout to load ───────────────────────────────
	// From US geo the backend returns use_managed_payments=true → Payment.svelte
	// calls stripe.initEmbeddedCheckout() and mounts into #checkout.
	// The checkout renders as an iframe inside #checkout.
	// If there are no saved EU cards, Payment.svelte shows the checkout directly.
	// If the "Add payment method" button is visible first, click it.
	const addPaymentMethodBtn = page.getByRole('button', { name: /add payment method/i });
	const hasAddBtn = await addPaymentMethodBtn.isVisible({ timeout: 8000 }).catch(() => false);
	if (hasAddBtn) {
		await addPaymentMethodBtn.click();
		log('Clicked Add Payment Method to open checkout.');
	}

	// If the "switch to non-EU card" button is present (user has EU saved cards),
	// click it to force the managed payments Checkout Session.
	const switchToNonEuBtn = page.getByTestId('switch-to-non-eu');
	const hasSwitchBtn = await switchToNonEuBtn.isVisible({ timeout: 5000 }).catch(() => false);
	if (hasSwitchBtn) {
		await switchToNonEuBtn.click();
		log('Clicked "switch to non-EU card" to force managed payments.');
	}

	await screenshot(page, 'payment-screen');

	// Wait for the Stripe Checkout iframe to appear inside #checkout div.
	await page.waitForSelector('#checkout iframe', { state: 'attached', timeout: 30000 });
	log('Stripe Embedded Checkout iframe loaded.');
	await page.waitForTimeout(3000); // allow Checkout UI to fully render
	await screenshot(page, 'checkout-iframe-loaded');

	// ─── Fill test card in Stripe Checkout iframe ─────────────────────────────────
	// Stripe Checkout (embedded) renders the card form inside the #checkout iframe.
	// Use a generic US Visa test card (4242424242424242) — non-EU, passes Managed Payments.
	const checkoutFrame = page.frameLocator('#checkout iframe');

	// Stripe Checkout may show Link as default — dismiss it and switch to Card.
	// Link shows a phone number field; clicking "Pay with card instead" or a Card
	// tab switches to the card form.
	const linkPhoneField = checkoutFrame.getByPlaceholder(/phone/i);
	const isLinkShown = await linkPhoneField.isVisible({ timeout: 5000 }).catch(() => false);
	if (isLinkShown) {
		// Try "Pay with card instead" button first
		const payWithCardBtn = checkoutFrame.getByRole('button', { name: /pay with card/i });
		const hasPayWithCard = await payWithCardBtn.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasPayWithCard) {
			await payWithCardBtn.click();
			log('Dismissed Link — clicked "Pay with card instead".');
		} else {
			// Try clicking a Card radio/tab
			const cardOpt = checkoutFrame.getByRole('radio', { name: /card/i });
			if (await cardOpt.isVisible({ timeout: 3000 }).catch(() => false)) {
				await cardOpt.click();
				log('Dismissed Link — clicked Card radio tab.');
			}
		}
		await page.waitForTimeout(1500);
	}

	// Stripe Checkout may show "Link" or "Card" tabs — click Card if needed.
	const cardTabOption = checkoutFrame.getByRole('radio', { name: /card/i });
	const hasCardTab = await cardTabOption.isVisible({ timeout: 5000 }).catch(() => false);
	if (hasCardTab) {
		await cardTabOption.click();
		log('Selected Card payment method in Checkout.');
		await page.waitForTimeout(1000);
	}

	// Card number — Stripe Checkout uses a single iframe for card inputs.
	// Use getByPlaceholder/getByLabel for robustness (autocomplete attrs vary by Stripe version).
	try {
		const cardInput = checkoutFrame
			.locator('input[autocomplete="cc-number"], input[name="number"], input[name="cardNumber"]')
			.first();
		await cardInput.waitFor({ state: 'visible', timeout: 20000 });
		await cardInput.click();
		await cardInput.pressSequentially('4242424242424242', { delay: 30 });

		const expiryInput = checkoutFrame
			.locator('input[autocomplete="cc-exp"], input[name="expiry"], input[name="cardExpiry"]')
			.first();
		await expiryInput.click();
		await expiryInput.pressSequentially('1234', { delay: 30 });

		const cvcInput = checkoutFrame
			.locator('input[autocomplete="cc-csc"], input[name="cvc"], input[name="cardCvc"]')
			.first();
		await cvcInput.click();
		await cvcInput.pressSequentially('123', { delay: 30 });

		// Cardholder name — required. Match by placeholder shown in the UI ("Full name on card").
		const cardholderInput = checkoutFrame.getByPlaceholder(/full name on card/i);
		if (await cardholderInput.isVisible({ timeout: 3000 }).catch(() => false)) {
			await cardholderInput.click();
			await cardholderInput.pressSequentially('Test User', { delay: 30 });
		}

		// Billing address line 1 (City/ZIP/State appear in the Link interstitial AFTER Pay, not here)
		const addressInput = checkoutFrame.getByPlaceholder(/^address$/i);
		if (await addressInput.isVisible({ timeout: 3000 }).catch(() => false)) {
			await addressInput.click();
			await addressInput.pressSequentially('123 Test St', { delay: 30 });
			// Dismiss Google autocomplete
			await page.keyboard.press('Escape');
			await page.waitForTimeout(500);
		}

		// Postal code — may be present in initial form (US geo without Link)
		const postalInput = checkoutFrame
			.locator(
				'input[autocomplete="postal-code"], input[name="postalCode"], input[name="postal_code"]'
			)
			.first();
		if (await postalInput.isVisible({ timeout: 1000 }).catch(() => false)) {
			await postalInput.click();
			await postalInput.pressSequentially('10001', { delay: 30 });
		}
	} catch (e) {
		// Stripe Checkout may render card fields in nested iframes
		log(`Card input fallback triggered: ${e}`);
		const cardFrame = checkoutFrame.frameLocator('iframe[title*="card number"]');
		const cardInput = cardFrame.locator('input').first();
		await cardInput.waitFor({ state: 'visible', timeout: 15000 });
		await cardInput.pressSequentially('4242424242424242', { delay: 30 });
	}

	await screenshot(page, 'checkout-card-filled');
	log('Test card filled in Stripe Checkout.');

	// ─── Submit payment ───────────────────────────────────────────────────────────
	const payBtn = checkoutFrame
		.locator('button[type="submit"], button:has-text("Pay"), button:has-text("Subscribe")')
		.first();
	await expect(payBtn).toBeVisible({ timeout: 10000 });
	await expect(payBtn).toBeEnabled({ timeout: 10000 });
	const purchaseEmailAfter = new Date().toISOString();
	await payBtn.click();
	log('Clicked Pay in Stripe Checkout — waiting for onComplete and confirmation.');

	// Stripe Link may show a "save your payment info" interstitial after clicking Pay.
	// Detect it by the "Save my payment information" checkbox (unique to the Link interstitial).
	await page.waitForTimeout(3000);
	const linkSaveCheckbox = checkoutFrame.getByText(/save my payment information/i);
	const isLinkInterstitial = await linkSaveCheckbox.isVisible({ timeout: 3000 }).catch(() => false);
	if (isLinkInterstitial) {
		await screenshot(page, 'link-interstitial-before-fill');

		// Uncheck "Save my payment information" — when unchecked Stripe skips address
		// collection and processes the payment directly.
		const saveInfoCheckbox = checkoutFrame.locator('input[type="checkbox"]').first();
		const isChecked = await saveInfoCheckbox.isChecked({ timeout: 2000 }).catch(() => false);
		if (isChecked) {
			await saveInfoCheckbox.uncheck();
			log('Unchecked "Save my payment information" checkbox.');
			await page.waitForTimeout(1000);
		}

		// Fill City and ZIP if visible. Use placeholder-based selectors — consistent with
		// how City was located in earlier passes (getByPlaceholder is the most robust selector
		// for Stripe's input fields whose name/autocomplete attrs vary by version).
		const interstitialCity = checkoutFrame.getByPlaceholder(/^city$/i);
		if (await interstitialCity.isVisible({ timeout: 2000 }).catch(() => false)) {
			await interstitialCity.fill('New York');
			log('Filled City field in interstitial.');
		}
		const interstitialZip = checkoutFrame.getByPlaceholder(/^zip$/i);
		if (await interstitialZip.isVisible({ timeout: 2000 }).catch(() => false)) {
			await interstitialZip.fill('10001');
			log('Filled ZIP field in interstitial.');
		}

		// Wait for Stripe to validate the address and auto-populate State (ZIP 10001 = NY).
		// Skipping manual State selectOption — it triggers an iframe re-render that causes
		// subsequent frameLocator operations to hang indefinitely in Playwright.
		await page.waitForTimeout(5000);

		await screenshot(page, 'link-interstitial-after-fill');

		// Click Pay — skip toBeEnabled check (can hang on reloading frames).
		// Fall back to force click if the normal click is blocked.
		const interstitialPay = checkoutFrame
			.locator('button[type="submit"], button:has-text("Pay")')
			.first();
		try {
			await interstitialPay.click({ timeout: 8000 });
		} catch {
			await interstitialPay.click({ force: true, timeout: 5000 });
		}
		log('Clicked through Stripe Link save-payment interstitial Pay button.');
	}

	// ─── Verify purchase success WITHOUT page reload ──────────────────────────────
	// onComplete fires in Payment.svelte → dispatches paymentStateChange('processing')
	// → SettingsBuyCreditsPayment.svelte waits for payment_completed WebSocket event
	// → navigates to confirmation screen. No page reload should occur.
	//
	// Assert that the URL stays on the same page (no navigation to a different route).
	const urlBefore = page.url();
	await expect(page.getByText(/purchase successful/i).first()).toBeVisible({ timeout: 120000 });
	const urlAfter = page.url();

	// Strip query params when comparing — the URL should not have changed to a
	// redirect target (e.g. ?session_id=cs_xxx would indicate a page reload).
	expect(new URL(urlAfter).pathname).toBe(new URL(urlBefore).pathname);
	expect(urlAfter).not.toContain('session_id=');

	await screenshot(page, 'purchase-success');
	log('Managed Payments purchase confirmed — no page reload detected.');

	// ─── Verify managed payment document + refund flow ────────────────────────────
	// Managed Payments must create an OpenMates payment confirmation row (not an
	// invoice row) and still allow unused-credit refunds from Settings → Invoices.
	const doneButton = page.getByRole('button', { name: /^done$/i });
	await expect(doneButton).toBeVisible({ timeout: 10000 });
	await doneButton.click();
	log('Returned to Billing after purchase confirmation.');
	// The invoice task is asynchronous. Give it time to create the persisted row before
	// opening Invoices, because payment_completed may have fired before this page mounts.
	await page.waitForTimeout(30000);

	const invoicesItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /invoices/i });
	await expect(invoicesItem).toBeVisible({ timeout: 10000 });
	await invoicesItem.click();
	log('Opened Invoices after managed payment.');

	await expect
		.poll(
			async () => {
				const labels = await page.locator('[data-testid="settings-menu"].visible').innerText();
				return /payment confirmation/i.test(labels);
			},
			{ timeout: 120000, intervals: [3000, 5000, 10000] }
		)
		.toBe(true);
	await screenshot(page, 'managed-payment-confirmation-row');
	log('Managed payment confirmation row is visible.');

	const purchaseEmail = await waitForMailosaurMessage({
		sentTo: TEST_EMAIL,
		subjectContains: 'Purchase confirmation',
		receivedAfter: purchaseEmailAfter,
		timeoutMs: 240000,
		pollIntervalMs: 10000
	});
	expect(purchaseEmail?.subject, 'Managed payment email subject must confirm purchase').toMatch(
		/purchase confirmation/i
	);
	const purchasePdfFilename = await expectPdfAttachment(
		emailClient,
		purchaseEmail,
		/^openmates_payment_confirmation_.*\.pdf$/i,
		'Managed payment confirmation'
	);
	log('Managed payment confirmation email and PDF attachment verified.', {
		subject: purchaseEmail?.subject,
		pdf: purchasePdfFilename
	});

	const latestManagedInvoice = page
		.locator('[data-testid="invoice-item"]')
		.filter({ hasText: /payment confirmation/i })
		.first();
	await expect(latestManagedInvoice).toBeVisible({ timeout: 10000 });

	const refundButton = latestManagedInvoice.getByRole('button', { name: /refund/i });
	await expect(refundButton).toBeVisible({ timeout: 10000 });
	await expect(refundButton).toBeEnabled({ timeout: 10000 });
	const refundEmailAfter = new Date().toISOString();
	await refundButton.click();
	log('Requested refund for managed payment row.');

	await expect
		.poll(
			async () => {
				const labels = await page.locator('[data-testid="settings-menu"].visible').innerText();
				return /refund confirmation|generating/i.test(labels);
			},
			{ timeout: 120000, intervals: [3000, 5000, 10000] }
		)
		.toBe(true);
	await screenshot(page, 'managed-refund-confirmation-row');
	log('Managed refund flow updated the invoice row.');

	const refundEmail = await waitForMailosaurMessage({
		sentTo: TEST_EMAIL,
		subjectContains: 'Refund confirmation',
		receivedAfter: refundEmailAfter,
		timeoutMs: 240000,
		pollIntervalMs: 10000
	});
	expect(refundEmail?.subject, 'Managed refund email subject must confirm refund').toMatch(
		/refund confirmation/i
	);
	const refundPdfFilename = await expectPdfAttachment(
		emailClient,
		refundEmail,
		/\.pdf$/i,
		'Managed refund confirmation'
	);
	log('Managed refund confirmation email and PDF attachment verified.', {
		subject: refundEmail?.subject,
		pdf: refundPdfFilename
	});

	await assertNoMissingTranslations(page);
	log('Test complete.');
});
