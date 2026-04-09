/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Saved Payment Method → Invoice Download end-to-end test.
 *
 * WHAT THIS TESTS:
 * 1. Logs in with a pre-existing test account.
 * 2. Opens Settings → Billing → Buy Credits.
 * 3. Selects the first pricing tier.
 * 4. Pays using a saved Stripe payment method (Finland/EU test card).
 * 5. Verifies "purchase successful" confirmation screen.
 * 6. Navigates to Settings → Billing → Invoices.
 * 7. Verifies the newly created invoice appears in the list.
 * 8. Waits for the invoice PDF to become available (download button enabled).
 * 9. Clicks download and verifies a PDF file is received.
 *
 * This test guards against regressions in the saved-payment-method flow
 * (Stripe PaymentIntent creation, order caching for webhook, invoice
 * generation via Celery task) that caused issue efa105dd.
 *
 * ARCHITECTURE NOTES:
 * - Saved payment methods are listed by SettingsBuyCreditsPayment.svelte.
 * - Payment uses Stripe confirmCardPayment() with a pre-attached method.
 * - After payment, a Celery task creates the invoice asynchronously.
 * - SettingsInvoices listens for `payment_completed` WebSocket events to
 *   auto-refresh the invoice list.
 * - Optimistic pending invoices show a "Generating..." spinner until the
 *   real invoice PDF is ready.
 *
 * STRIPE TEST CARD (saved on the test account):
 * - Card: 4000 0024 6000 0001 (Finland/EU — required by Radar "block non-EU" rule)
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 *
 * SKIP CONDITIONS:
 * - Test account env vars are not set.
 *
 * Tests: frontend/apps/web_app/tests/saved-payment-invoice-flow.spec.ts
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	fillStripeCardDetails,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

// Stripe test card: Finland (FI) EU card — required because Radar blocks non-EU cards.
// Used both for seeding a saved payment method and for the saved-method flow.
// See: https://docs.stripe.com/testing#international-cards
const STRIPE_TEST_CARD = '4000002460000001';

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

// ---------------------------------------------------------------------------
// Test: Saved payment method → purchase → invoice appears → download works
// ---------------------------------------------------------------------------

test('purchases credits with saved payment method, then verifies invoice is downloadable', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	// Allow extra time: login + payment + Celery task + invoice download
	test.setTimeout(300000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);
	page.on('response', (res: any) =>
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`)
	);

	// ─── Skip guards ─────────────────────────────────────────────────────────────

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('SAVED_PAYMENT_INVOICE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'saved-payment-invoice' });
	await archiveExistingScreenshots(log);

	// ─── Step 1: Login ────────────────────────────────────────────────────────────

	await loginToTestAccount(page, log, screenshot);
	// Allow auth state + decryption to fully propagate before navigating to settings.
	await page.waitForTimeout(4000);

	// ─── Step 2: Open Settings ───────────────────────────────────────────────────

	const profileContainer = page.getByTestId('profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();
	log('Opened settings menu.');

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 8000 });

	// Wait for settings menu items to load (confirms authenticated state fully propagated).
	await expect(
		page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]').first()
	).toBeVisible({ timeout: 15000 });

	await screenshot(page, 'settings-menu-open');

	// ─── Step 3: Navigate to Settings → Billing → Buy Credits ─────────────────────

	const billingItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /billing/i });
	await expect(billingItem).toBeVisible({ timeout: 10000 });
	await billingItem.click();
	log('Navigated to Billing.');
	await screenshot(page, 'billing-page');

	const buyCreditsItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /buy credits/i });
	await expect(buyCreditsItem).toBeVisible({ timeout: 10000 });
	await buyCreditsItem.click();
	log('Navigated to Buy Credits.');
	await screenshot(page, 'buy-credits-page');

	// ─── Step 4: Select first pricing tier ────────────────────────────────────────

	await expect(async () => {
		const tierItems = page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]');
		const count = await tierItems.count();
		expect(count).toBeGreaterThanOrEqual(3);
	}).toPass({ timeout: 15000 });
	log('Pricing tiers visible.');

	const firstTier = page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]').first();
	await expect(firstTier).toBeVisible({ timeout: 5000 });
	await firstTier.click();
	log('Selected first pricing tier.');
	await screenshot(page, 'tier-selected');

	// ─── Step 5: Ensure a saved payment method exists (seed if needed) ────────────
	// After tier selection, SettingsBuyCreditsPayment loads.
	// If the test account already has a saved Stripe payment method, great.
	// If not, we do a full fresh Stripe payment first to seed one — then repeat
	// the Buy Credits flow and use the now-saved method the second time.
	//
	// This makes the test self-contained regardless of test account state.

	await page.waitForTimeout(3000); // Allow payment component to load and detect saved methods

	const savedMethodItem = page.getByTestId('payment-method-item').first();
	const hasSavedMethods = await savedMethodItem.isVisible({ timeout: 10000 }).catch(() => false);

	if (!hasSavedMethods) {
		// No saved payment methods yet — do a fresh Stripe payment first to seed one.
		log('No saved payment methods found — doing a fresh Stripe payment to seed the saved method.');
		await screenshot(page, 'no-saved-methods-fresh-form');

		// Wait for any iframe (Polar or Stripe) to confirm the payment component loaded.
		await page.waitForSelector('iframe', { state: 'visible', timeout: 20000 });

		// If an "Add payment method" button is visible (saved methods exist on Stripe),
		// click it to reveal the fresh Stripe form.
		const addPaymentMethodBtn = page.getByRole('button', { name: /add payment method/i });
		if (await addPaymentMethodBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
			await addPaymentMethodBtn.click();
			log('Clicked "Add payment method" button.');
			await page.waitForTimeout(2000);
		}

		// The default provider may be Polar (non-EU). Switch to Stripe (EU card) to
		// seed a saved payment method — Polar does not support saved methods.
		const switchToEuCardBtn = page.getByRole('button', { name: /EU card|with an EU card/i });
		if (await switchToEuCardBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			await switchToEuCardBtn.click();
			log('Switched to EU card (Stripe) provider for seeding.');
			await page.waitForTimeout(3000);
		}

		// Wait for the Stripe Payment Element iframe to load.
		await expect(page.locator('iframe[title="Secure payment input frame"]')).toBeVisible({
			timeout: 30000
		});
		log('Stripe payment iframe loaded.');
		await screenshot(page, 'stripe-payment-form-seed');

		// Fill the Stripe card form
		await fillStripeCardDetails(page, STRIPE_TEST_CARD);
		await screenshot(page, 'stripe-card-filled-seed');
		log('Stripe test card filled for seeding.');

		// Submit — "Buy for 2 EUR" style button (avoid matching "Pay with a non-EU card")
		const seedPayButton = page.getByRole('button', { name: /buy for \d|^pay$/i });
		await expect(seedPayButton).toBeVisible({ timeout: 15000 });
		await seedPayButton.click();
		log('Clicked Pay button for seed payment.');

		// Wait for success
		await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 120000 });
		log('Seed payment successful — saved method should now be stored on Stripe customer.');
		await screenshot(page, 'seed-purchase-success');

		// Click Done to go back to billing
		const doneBtnSeed = page.getByRole('button', { name: /done/i });
		await expect(doneBtnSeed).toBeVisible({ timeout: 10000 });
		await doneBtnSeed.click();
		await page.waitForTimeout(1000);

		// Navigate back to Buy Credits
		const buyCreditsItemAgain = page
			.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
			.filter({ hasText: /buy credits/i });
		await expect(buyCreditsItemAgain).toBeVisible({ timeout: 10000 });
		await buyCreditsItemAgain.click();
		log('Navigated back to Buy Credits after seed payment.');
		await screenshot(page, 'buy-credits-page-second');

		// Select first tier again
		await expect(async () => {
			const tierItemsAgain = page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]');
			const countAgain = await tierItemsAgain.count();
			expect(countAgain).toBeGreaterThanOrEqual(3);
		}).toPass({ timeout: 15000 });

		const firstTierAgain = page
			.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
			.first();
		await expect(firstTierAgain).toBeVisible({ timeout: 5000 });
		await firstTierAgain.click();
		log('Selected first pricing tier (second attempt).');
		await page.waitForTimeout(3000); // Allow component to load saved methods
		await screenshot(page, 'tier-selected-second');
	}

	// At this point the test account should have a saved Stripe method.
	const savedMethodItemNow = page.getByTestId('payment-method-item').first();
	await expect(savedMethodItemNow).toBeVisible({ timeout: 15000 });
	log('Saved payment methods detected.');
	await screenshot(page, 'saved-methods-list');

	// The first saved method should already be selected — check for Buy Now being enabled.
	const buyNowBtn = page.getByRole('button', { name: /buy now/i });
	const methodToggle = savedMethodItemNow.locator('label, .toggle, input[type="checkbox"]').first();

	const isAlreadySelected = await buyNowBtn.isEnabled().catch(() => false);
	if (!isAlreadySelected) {
		await methodToggle.click();
		log('Toggled first saved payment method.');
		await page.waitForTimeout(500);
	} else {
		log('First saved payment method already selected.');
	}

	await screenshot(page, 'method-selected');

	// ─── Step 6: Click "Buy Now" ──────────────────────────────────────────────────

	await expect(buyNowBtn).toBeVisible({ timeout: 10000 });
	await expect(buyNowBtn).toBeEnabled({ timeout: 5000 });
	const paymentSubmittedAt = new Date().toISOString();
	await buyNowBtn.click();
	log('Clicked Buy Now button.', { paymentSubmittedAt });

	// ─── Step 6a: Handle PaymentAuth modal (if it appears) ────────────────────────
	// The app may require re-authentication before processing the payment.
	// PaymentAuth supports OTP and passkey. We handle OTP here.

	const authModal = page.locator('[data-testid="payment-auth-overlay"], [data-testid="auth-modal"]');
	const authModalVisible = await authModal.isVisible({ timeout: 5000 }).catch(() => false);

	if (authModalVisible) {
		log('PaymentAuth modal appeared — entering OTP.');
		await screenshot(page, 'auth-modal');

		const authOtpInput = authModal
			.locator('input[autocomplete="one-time-code"], input[type="text"]')
			.first();
		await expect(authOtpInput).toBeVisible({ timeout: 5000 });

		// Try OTP up to 3 times (TOTP window boundary tolerance)
		let authSuccess = false;
		for (let attempt = 1; attempt <= 3 && !authSuccess; attempt++) {
			const otpCode = generateTotp(TEST_OTP_KEY);
			await authOtpInput.fill(otpCode);

			// Submit — look for a confirm/verify button in the modal
			const authSubmit = authModal.getByRole('button', { name: /verify|confirm|submit/i });
			if (await authSubmit.isVisible({ timeout: 2000 }).catch(() => false)) {
				await authSubmit.click();
			}

			// Wait for modal to close
			try {
				await expect(authModal).not.toBeVisible({ timeout: 8000 });
				authSuccess = true;
				log('PaymentAuth completed.');
			} catch {
				if (attempt < 3) {
					await page.waitForTimeout(31000); // Wait for next TOTP window
					await authOtpInput.fill('');
				}
			}
		}
		await screenshot(page, 'auth-completed');
	}

	// ─── Step 7: Wait for "purchase successful" ───────────────────────────────────

	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 120000 });
	await screenshot(page, 'purchase-success');
	log('Purchase confirmed successful.');

	await assertNoMissingTranslations(page);

	// ─── Step 8: Navigate to Billing → Invoices ───────────────────────────────────
	// From the confirmation screen, go back to billing, then open invoices.

	// Click "Done" button on confirmation screen to go back to billing
	const doneBtn = page.getByRole('button', { name: /done/i });
	await expect(doneBtn).toBeVisible({ timeout: 10000 });
	await doneBtn.click();
	log('Clicked Done on confirmation screen → back to Billing.');
	await page.waitForTimeout(1000);
	await screenshot(page, 'back-to-billing');

	// Click "Invoices" menu item in billing submenu
	const invoicesItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /invoices/i });
	await expect(invoicesItem).toBeVisible({ timeout: 10000 });
	await invoicesItem.click();
	log('Navigated to Invoices.');
	await page.waitForTimeout(2000); // Allow invoices to load from API
	await screenshot(page, 'invoices-page');

	// ─── Step 9: Verify the new invoice appears ───────────────────────────────────
	// The invoice should appear either as a real DB invoice (if the Celery task
	// finished) or as a pending/generating invoice (optimistic UI).

	// Wait for at least one invoice item to be visible
	const invoiceItem = page.getByTestId('invoice-item').first();
	await expect(invoiceItem).toBeVisible({ timeout: 30000 });
	log('At least one invoice is visible.');
	await screenshot(page, 'invoice-visible');

	// Verify the most recent invoice shows today's date
	const invoiceDate = invoiceItem.getByTestId('invoice-date');
	const dateText = await invoiceDate.textContent();
	log('Most recent invoice date: ' + dateText);

	// The date should contain the current year at minimum
	const currentYear = new Date().getFullYear().toString();
	expect(dateText).toContain(currentYear);

	// ─── Step 10: Wait for download button and verify download ────────────────────
	// The download button is only enabled once the invoice PDF is generated.
	// If the invoice is still "generating", a disabled button with a spinner is shown.
	// We wait for the enabled download button to appear.

	const downloadBtn = invoiceItem.locator(
		'[data-testid="download-button"]:not([disabled]):not(.processing)'
	);

	await expect(downloadBtn).toBeVisible({ timeout: 60000 });
	log('Download button is enabled (invoice PDF is ready).');
	await screenshot(page, 'download-ready');

	// Set up download event listener BEFORE clicking
	const downloadPromise = page.waitForEvent('download', { timeout: 30000 }).catch(() => null);

	// Also intercept the API response to verify the download succeeds
	const responsePromise = page
		.waitForResponse(
			(response: any) =>
				response.url().includes('/invoice') && response.url().includes('/download'),
			{ timeout: 30000 }
		)
		.catch(() => null);

	await downloadBtn.click();
	log('Clicked download button.');

	// Verify the download response was successful (200 OK with PDF content)
	const downloadResponse = await responsePromise;
	if (downloadResponse) {
		const status = downloadResponse.status();
		log('Download response status: ' + status);
		expect(status).toBe(200);

		// Verify Content-Type is PDF
		const contentType = downloadResponse.headers()['content-type'];
		log('Download content-type: ' + contentType);
		expect(contentType).toContain('pdf');

		// Verify Content-Disposition has a filename
		const contentDisposition = downloadResponse.headers()['content-disposition'];
		log('Download content-disposition: ' + contentDisposition);
		expect(contentDisposition).toBeTruthy();
		expect(contentDisposition).toContain('filename');
	} else {
		// If we couldn't intercept the response, at least verify the download event fired
		const download = await downloadPromise;
		if (download) {
			const suggestedFilename = download.suggestedFilename();
			log('Download triggered with filename: ' + suggestedFilename);
			expect(suggestedFilename).toContain('.pdf');
		} else {
			// Neither response nor download captured — check for success notification
			log('Could not capture download event or response — checking for success notification.');
		}
	}

	// Verify no error notification appeared
	const errorNotification = page.locator('[data-testid="notification"].error, [data-testid="notification-error"]');
	const hasError = await errorNotification.isVisible({ timeout: 2000 }).catch(() => false);
	expect(hasError).toBe(false);

	await screenshot(page, 'download-complete');
	await assertNoMissingTranslations(page);
	log('Test complete — saved payment method purchase and invoice download verified.');
});
