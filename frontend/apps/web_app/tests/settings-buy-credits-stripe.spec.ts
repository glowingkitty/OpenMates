/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: payment-data-minimization
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.

/**
 * Settings → Buy Credits — Stripe (EU card) flow test.
 *
 * WHAT THIS TESTS:
 * - Logs in with a pre-existing test account.
 * - Opens Settings → Billing → Buy Credits.
 * - Selects a credit tier (first available).
 * - Handles geo-detection: Playwright runs from a US IP → API returns provider=polar.
 *   When the Polar Checkout iframe appears, clicks "Pay with an EU card instead" to
 *   switch the backend to Stripe. When running from EU geo, Stripe loads directly.
 * - Verifies the Stripe Payment Element iframe loads.
 * - Fills in the Stripe EU test card (4000 0024 6000 0001 Finland — passes Radar EU rule).
 * - Submits the Stripe payment form.
 * - Verifies "purchase successful" message on the main page.
 *
 * ARCHITECTURE NOTES:
 * - The settings buy-credits flow uses SettingsBuyCreditsPayment.svelte.
 * - The default provider is Stripe (EU geo-detection or fallback).
 * - After consent, Payment.svelte renders a Stripe Payment Element iframe
 *   (title="Secure payment input frame").
 * - Clicking "Pay" triggers POST /create-order → Stripe charges the card.
 * - On success, ProcessingPayment polls /poll-order until SUCCEEDED, then
 *   dispatches purchaseCompleted → "purchase successful" is shown.
 *
 * STRIPE TEST CARD (used here):
 * - Card: 4000 0024 6000 0001 (Finland/EU card — required by Radar "block non-EU" rule) | Expiry: 12/34 | CVC: 123
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL (or slot-based variant)
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 *
 * SKIP CONDITIONS:
 * - Test account env vars are not set.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	fillStripeCardDetails,
	getTestAccount,
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

// Stripe test card: Finland (FI) EU card — required because Radar blocks non-EU cards.
// See: https://docs.stripe.com/testing#international-cards
const STRIPE_TEST_CARD = '4000002460000001';

// ---------------------------------------------------------------------------
// Test: Settings → Buy Credits → Stripe (EU card) full checkout
// ---------------------------------------------------------------------------

test('settings buy credits: completes full Stripe (EU card) purchase flow', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	// Allow extra time for Stripe payment processing + polling loop.
	test.setTimeout(420000);

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

	const log = createSignupLogger('SETTINGS_BUY_CREDITS_STRIPE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'settings-stripe' });
	await archiveExistingScreenshots(log);

	// ─── Login ────────────────────────────────────────────────────────────────────

	await loginToTestAccount(page, log, screenshot);
	// Allow auth state + decryption to fully propagate before navigating to settings.
	await page.waitForTimeout(4000);

	// ─── Open Settings ───────────────────────────────────────────────────────────

	const profileContainer = page.getByTestId('profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();
	log('Opened settings menu.');

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 8000 });

	// Wait for credits balance — confirms authenticated state fully loaded.
	await expect(page.locator('[data-testid="settings-menu"].visible [data-testid="credits-row"]')).toBeVisible({
		timeout: 15000
	});
	await screenshot(page, 'settings-menu-open');

	// ─── Navigate: Settings → Billing → Buy Credits ───────────────────────────────

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

	// Verify pricing tiers are rendered
	await expect(async () => {
		const tierItems = page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]');
		const count = await tierItems.count();
		expect(count).toBeGreaterThanOrEqual(3);
	}).toPass({ timeout: 15000 });
	log('Pricing tiers visible.');
	await screenshot(page, 'pricing-tiers');

	// ─── Select first pricing tier ────────────────────────────────────────────────

	const firstTier = page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]').first();
	await expect(firstTier).toBeVisible({ timeout: 5000 });
	await firstTier.click();
	log('Selected first pricing tier.');
	await screenshot(page, 'tier-selected');

	// ─── Payment form ───────────────────────────────────────────────────────────
	// The Playwright Docker container runs from a US IP address. The API geo-detects
	// non-EU → sets provider=polar. We must force Stripe regardless of geo.
	//
	// Strategy:
	//   1. Click "Add Payment Method" (or wait for an iframe to appear).
	//   2. If the Polar Checkout iframe appears first, click the "Pay with an EU card
	//      instead" button inside it — this switches the flow to Stripe on the backend.
	//   3. Once the Stripe Payment Element iframe loads, fill the test card.
	//   4. Submit and wait for "purchase successful".
	//
	// We always use the new-card path (no saved method) to avoid saved-method Buy Now
	// triggering a Polar order via geo detection.

	// If there are saved payment methods, the component shows the saved methods list
	// with an "Add Payment Method" button. If there are none, the payment form shows
	// directly. Either path is valid — click the button when present, otherwise skip.
	const addPaymentMethodBtn = page.getByRole('button', { name: /add payment method/i });
	const hasAddBtn = await addPaymentMethodBtn.isVisible({ timeout: 15000 }).catch(() => false);
	if (hasAddBtn) {
		await addPaymentMethodBtn.click();
		log('Clicked Add Payment Method button.');
	} else {
		log('No saved cards — payment form shown directly.');
	}
	await screenshot(page, 'payment-screen');

	// Wait for either Stripe or Polar to initialise (either way an iframe appears).
	await page.waitForSelector('iframe', { state: 'attached', timeout: 20000 });

	// If the "Pay with an EU card instead" button is present (Polar flow from US geo),
	// use JavaScript dispatchEvent to click it. The button is in the main DOM but is
	// visually covered by the Polar Checkout iframe, so Playwright's click (even with
	// force=true) doesn't trigger the Svelte event handler. A programmatic dispatchEvent
	// bypasses the iframe overlay and fires the handler correctly.
	const euCardBtn = page.getByRole('button', { name: /pay with.*eu card instead/i });
	const isPolarFlow = await euCardBtn.isVisible({ timeout: 5000 }).catch(() => false);
	if (isPolarFlow) {
		await page.evaluate(() => {
			const buttons = document.querySelectorAll('button');
			for (const btn of buttons) {
				if (btn.textContent?.includes('EU card instead')) {
					btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
					btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
					btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
					break;
				}
			}
		});
		log('Polar flow detected. Dispatched JS click on "Pay with an EU card instead".');
		await page.waitForTimeout(3000);
		await screenshot(page, 'after-eu-switch');
	}

	// Now the Stripe Payment Element iframe should be present in the DOM.
	await page.waitForSelector('iframe[title="Secure payment input frame"]', {
		state: 'attached',
		timeout: 30000
	});
	log('Stripe Payment Element iframe loaded.');

	// Wait for the card input fields to become interactive.
	await page.waitForTimeout(2000);
	await screenshot(page, 'stripe-payment-form');

	await fillStripeCardDetails(page, STRIPE_TEST_CARD);
	await screenshot(page, 'stripe-card-filled');
	log('Stripe test card details filled.');

	const paymentSubmittedAt = new Date().toISOString();
	// The submit button is "Buy for X EUR" (exact text varies by tier).
	// Use type="submit" to avoid matching "Pay with a non-EU card" or "Payment" header.
	const stripePayButton = page
		.locator(
			'button[type="submit"].buy-button, button[type="submit"]:has-text("Buy for"), button[type="submit"]:has-text("Pay")'
		)
		.first();
	await expect(stripePayButton).toBeVisible({ timeout: 15000 });
	await expect(stripePayButton).toBeEnabled({ timeout: 10000 });
	await stripePayButton.click();
	log('Clicked Stripe Pay button — waiting for success confirmation.', {
		paymentSubmittedAt
	});

	// ─── Verify purchase success ──────────────────────────────────────────────────
	// ProcessingPayment polls /poll-order until status=SUCCEEDED, then emits
	// purchaseCompleted → Payment.svelte shows "purchase successful".

	await expect(page.getByText(/purchase successful/i).first()).toBeVisible({ timeout: 120000 });
	await screenshot(page, 'purchase-success');
	log('Purchase confirmed successful.');

	await assertNoMissingTranslations(page);
	log('Test complete.');
});

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
	test.setTimeout(420000);

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

	const log = createSignupLogger('SETTINGS_BUY_CREDITS_MANAGED');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'settings-managed' });
	await archiveExistingScreenshots(log);

	// ─── Login ────────────────────────────────────────────────────────────────────
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(4000);

	// ─── Open Settings ───────────────────────────────────────────────────────────
	const profileContainer = page.getByTestId('profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 8000 });
	await expect(page.locator('[data-testid="settings-menu"].visible [data-testid="credits-row"]')).toBeVisible({ timeout: 15000 });

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
		const tierItems = page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]');
		expect(await tierItems.count()).toBeGreaterThanOrEqual(3);
	}).toPass({ timeout: 15000 });

	// ─── Select first pricing tier ────────────────────────────────────────────────
	const firstTier = page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]').first();
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
		const cardInput = checkoutFrame.locator(
			'input[autocomplete="cc-number"], input[name="number"], input[name="cardNumber"]'
		).first();
		await cardInput.waitFor({ state: 'visible', timeout: 20000 });
		await cardInput.click();
		await cardInput.pressSequentially('4242424242424242', { delay: 30 });

		const expiryInput = checkoutFrame.locator(
			'input[autocomplete="cc-exp"], input[name="expiry"], input[name="cardExpiry"]'
		).first();
		await expiryInput.click();
		await expiryInput.pressSequentially('1234', { delay: 30 });

		const cvcInput = checkoutFrame.locator(
			'input[autocomplete="cc-csc"], input[name="cvc"], input[name="cardCvc"]'
		).first();
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
		const postalInput = checkoutFrame.locator(
			'input[autocomplete="postal-code"], input[name="postalCode"], input[name="postal_code"]'
		).first();
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
		// collection and processes the payment directly. This avoids needing to fill
		// City/ZIP/State fields (which vary by Stripe version).
		const saveInfoCheckbox = checkoutFrame.locator('input[type="checkbox"]').first();
		const isChecked = await saveInfoCheckbox.isChecked({ timeout: 2000 }).catch(() => false);
		if (isChecked) {
			await saveInfoCheckbox.uncheck();
			log('Unchecked "Save my payment information" checkbox.');
			await page.waitForTimeout(1000);
		}

		// If address fields are still visible after unchecking, fill them.
		// ZIP: use placeholder-based selector (same approach as City which works reliably).
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
		// State: find the first visible <select> in the checkout frame (only one in the interstitial).
		const interstitialState = checkoutFrame.locator('select').first();
		if (await interstitialState.isVisible({ timeout: 2000 }).catch(() => false)) {
			await interstitialState.selectOption('NY');
			log('Selected State NY in interstitial.');
		}

		await screenshot(page, 'link-interstitial-after-fill');

		const interstitialPay = checkoutFrame
			.locator('button[type="submit"], button:has-text("Pay")')
			.first();
		await expect(interstitialPay).toBeEnabled({ timeout: 5000 });
		await interstitialPay.click();
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

	await assertNoMissingTranslations(page);
	log('Test complete.');
});
