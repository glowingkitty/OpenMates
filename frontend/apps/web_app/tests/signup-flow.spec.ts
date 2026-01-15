/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.
const { test, expect } = require('@playwright/test');
const nodeCrypto = require('crypto');

/**
 * Full signup flow test (password + 2FA + purchase) against a deployed web app.
 *
 * ARCHITECTURE NOTES:
 * - The test is intentionally self-contained: we avoid adding npm/pnpm deps by
 *   using built-in Node.js crypto for TOTP and Mailosaur's raw REST API via fetch.
 * - The email confirmation code and purchase confirmation email are fetched
 *   from Mailosaur (server + API key must be provided via env vars).
 * - We generate a unique signup email using SIGNUP_TEST_EMAIL_DOMAINS so the
 *   backend domain allowlist can be enforced while still allowing test signups.
 *
 * REQUIRED ENV VARS:
 * - SIGNUP_TEST_EMAIL_DOMAINS: Comma-separated list of allowed test domains.
 * - MAILOSAUR_API_KEY: Mailosaur API key for test mailbox access.
 * - MAILOSAUR_SERVER_ID: Mailosaur server ID used by the test domain.
 */

const MAILOSAUR_API_KEY = process.env.MAILOSAUR_API_KEY;
let MAILOSAUR_SERVER_ID = process.env.MAILOSAUR_SERVER_ID;
const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const MAILOSAUR_BASE_URL = 'https://mailosaur.com/api';
const STRIPE_TEST_CARD_NUMBER = '4000002760000016';

/**
 * Capture a screenshot for each major step in the signup flow.
 * We prefix an incrementing counter to keep the timeline clear in artifacts/.
 */
let signupStepScreenshotIndex = 1;
async function takeStepScreenshot(page: any, label: string): Promise<void> {
	const safeLabel = label.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-|-$/g, '');
	const filename = `${String(signupStepScreenshotIndex).padStart(2, '0')}-${safeLabel || 'step'}.png`;
	signupStepScreenshotIndex += 1;
	// Small delay to allow UI transitions to settle before capture.
	await page.waitForTimeout(1000);
	await page.screenshot({
		path: `artifacts/${filename}`,
		fullPage: true
	});
}

/**
 * Toggle helper to avoid viewport/visibility flakiness for compact signup forms.
 * We scroll into view first, then explicitly check/uncheck the input.
 */
async function setToggleChecked(toggleLocator: any, shouldBeChecked: boolean): Promise<void> {
	await toggleLocator.scrollIntoViewIfNeeded();
	try {
		if (shouldBeChecked) {
			await toggleLocator.check({ force: true });
		} else {
			await toggleLocator.uncheck({ force: true });
		}
	} catch {
		// Fallback: directly toggle the checkbox state if viewport constraints block clicks.
		// This keeps the test moving while still exercising the underlying change handler.
		await toggleLocator.evaluate((element: HTMLInputElement, desired: boolean) => {
			element.checked = desired;
			element.dispatchEvent(new Event('change', { bubbles: true }));
		}, shouldBeChecked);
	}
}

/**
 * Fill Stripe Payment Element card fields with a fallback for iframe layouts.
 * The element can render either a unified payment iframe or separate card frames.
 */
async function fillStripeCardDetails(page: any, cardNumber: string): Promise<void> {
	const paymentFrame = page.frameLocator('iframe[title="Secure payment input frame"]');
	try {
		const cardInput = paymentFrame.locator('input[name="cardNumber"], input[autocomplete="cc-number"]').first();
		await cardInput.waitFor({ state: 'visible', timeout: 30000 });
		await cardInput.fill(cardNumber);
		await paymentFrame.locator('input[name="cardExpiry"], input[autocomplete="cc-exp"]').fill('12/34');
		await paymentFrame.locator('input[name="cardCvc"], input[autocomplete="cc-csc"]').fill('123');
		return;
	} catch {
		// Fallback to the split Stripe iframe layout (card number/expiry/CVC separate).
	}

	const cardNumberFrame = page.frameLocator('iframe[title*="card number"]');
	const expFrame = page.frameLocator('iframe[title*="expiration"]');
	const cvcFrame = page.frameLocator('iframe[title*="security code"], iframe[title*="CVC"]');

	await cardNumberFrame.locator('input[name="cardNumber"], input[autocomplete="cc-number"]').fill(cardNumber);
	await expFrame.locator('input[name="cardExpiry"], input[autocomplete="cc-exp"]').fill('12/34');
	await cvcFrame.locator('input[name="cardCvc"], input[autocomplete="cc-csc"]').fill('123');
}

/**
 * Pick the first allowed test domain from SIGNUP_TEST_EMAIL_DOMAINS.
 * We keep this deterministic so the backend allowlist logic stays predictable.
 */
function getSignupTestDomain(): string | null {
	if (!SIGNUP_TEST_EMAIL_DOMAINS) {
		return null;
	}

	const domains = SIGNUP_TEST_EMAIL_DOMAINS.split(',')
		.map((domain) => domain.trim())
		.filter(Boolean);

	return domains.length > 0 ? domains[0] : null;
}

/**
 * Derive the Mailosaur server ID from the test domain when possible.
 * Mailosaur domains are typically <server-id>.mailosaur.net, so we can
 * parse the server ID if the env var is not set.
 */
function getMailosaurServerId(signupDomain: string): string | null {
	if (MAILOSAUR_SERVER_ID) {
		return MAILOSAUR_SERVER_ID;
	}

	const domainParts = signupDomain.split('.');
	const isMailosaurDomain = signupDomain.toLowerCase().endsWith('.mailosaur.net');
	if (isMailosaurDomain && domainParts.length > 2) {
		return domainParts[0];
	}

	return null;
}

/**
 * Build a time-based email local-part in the requested format: {MMM}{DD}{HH}{MM}.
 * Example: jan151333@testdomain.org.
 *
 * We keep this strict format to match backend allowlist tests and for easy
 * tracing in Mailosaur.
 */
function buildSignupEmail(domain: string): string {
	const now = new Date();
	const monthNames = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

	const month = monthNames[now.getMonth()];
	const day = String(now.getDate()).padStart(2, '0');
	const hour = String(now.getHours()).padStart(2, '0');
	const minute = String(now.getMinutes()).padStart(2, '0');

	return `${month}${day}${hour}${minute}@${domain}`;
}

/**
 * Build the Mailosaur basic auth header (API key as username, blank password).
 * This is required for all Mailosaur REST calls.
 */
function buildMailosaurAuthHeader(): string {
	const token = Buffer.from(`${MAILOSAUR_API_KEY}:`).toString('base64');
	return `Basic ${token}`;
}

/**
 * Call the Mailosaur REST API with basic error handling and JSON parsing.
 * We keep this generic so email confirmation and purchase checks can share it.
 */
async function mailosaurFetch(
	path: string,
	options: {
		method?: string;
		headers?: Record<string, string>;
		body?: Record<string, unknown>;
	} = {}
): Promise<any> {
	const response = await fetch(`${MAILOSAUR_BASE_URL}${path}`, {
		method: options.method || 'GET',
		headers: {
			Authorization: buildMailosaurAuthHeader(),
			'Content-Type': 'application/json',
			...(options.headers || {})
		},
		body: options.body ? JSON.stringify(options.body) : undefined
	});

	if (!response.ok) {
		const errorBody = await response.text();
		throw new Error(`Mailosaur API error (${response.status}): ${errorBody}`);
	}

	return response.json();
}

/**
 * Mailosaur message shape (minimal fields used in this test).
 */
interface MailosaurMessage {
	id?: string;
	_id?: string;
	subject?: string;
	text?: { body?: string };
	html?: { body?: string };
}

/**
 * Poll Mailosaur for a message that matches a recipient and optional subject.
 * We keep the polling explicit to avoid implicit SDK retries and to reduce
 * hidden test flakiness.
 */
async function waitForMailosaurMessage({
	sentTo,
	subjectContains,
	receivedAfter,
	timeoutMs = 120000,
	pollIntervalMs = 5000
}: {
	sentTo: string;
	subjectContains?: string;
	receivedAfter: string;
	timeoutMs?: number;
	pollIntervalMs?: number;
}): Promise<MailosaurMessage> {
	const deadline = Date.now() + timeoutMs;

	while (Date.now() < deadline) {
		const searchResponse = await mailosaurFetch(`/messages/search?server=${MAILOSAUR_SERVER_ID}`, {
			method: 'POST',
			body: {
				sentTo,
				subject: subjectContains || undefined,
				receivedAfter
			}
		});

		const items = searchResponse.items || [];
		if (items.length > 0) {
			const messageId = items[0].id || items[0]._id;
			return mailosaurFetch(`/messages/${messageId}`);
		}

		await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
	}

	throw new Error(`Timed out waiting for Mailosaur message sent to ${sentTo}`);
}

/**
 * Extract the first 6-digit code from a Mailosaur message body or subject.
 * This is used for the email verification step during signup.
 */
function extractSixDigitCode(message: MailosaurMessage): string | null {
	const candidateText = [
		message.subject || '',
		message.text?.body || '',
		message.html?.body || ''
	].join(' ');

	const match = candidateText.match(/\b(\d{6})\b/);
	return match ? match[1] : null;
}

/**
 * Extract a refund link from a purchase confirmation email.
 * We look for a URL that includes "refund" to align with the email template.
 */
function extractRefundLink(message: MailosaurMessage): string | null {
	const htmlBody = message.html?.body || '';
	const textBody = message.text?.body || '';
	const links: string[] = [];

	// Prefer explicit HTML hrefs when available.
	const hrefRegex = /href=["']([^"']+)["']/gi;
	let hrefMatch = hrefRegex.exec(htmlBody);
	while (hrefMatch) {
		links.push(hrefMatch[1]);
		hrefMatch = hrefRegex.exec(htmlBody);
	}

	// Fallback: extract raw URLs from text or HTML.
	const urlRegex = /https?:\/\/[^\s"'<>]+/gi;
	const textMatches = textBody.match(urlRegex) || [];
	const htmlMatches = htmlBody.match(urlRegex) || [];
	links.push(...textMatches, ...htmlMatches);

	// If Mailosaur provides parsed links, include them as well.
	const htmlLinks = (message.html as any)?.links;
	if (Array.isArray(htmlLinks)) {
		for (const link of htmlLinks) {
			if (typeof link?.href === 'string') {
				links.push(link.href);
			} else if (typeof link?.url === 'string') {
				links.push(link.url);
			}
		}
	}

	const refundLink = links.find((link) => /refund/i.test(link));
	return refundLink || null;
}

/**
 * Decode a base32-encoded secret (RFC 4648) into a raw byte buffer.
 * This is required for TOTP generation without external libraries.
 */
function decodeBase32(input: string): Buffer {
	const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
	const cleaned = input.toUpperCase().replace(/[^A-Z2-7]/g, '');
	let bits = '';

	for (const char of cleaned) {
		const value = alphabet.indexOf(char);
		if (value === -1) {
			continue;
		}
		bits += value.toString(2).padStart(5, '0');
	}

	const bytes = [];
	for (let i = 0; i + 8 <= bits.length; i += 8) {
		bytes.push(parseInt(bits.slice(i, i + 8), 2));
	}

	return Buffer.from(bytes);
}

/**
 * Generate a 6-digit TOTP using HMAC-SHA1 and a 30-second step.
 * This matches common authenticator behavior without extra dependencies.
 */
function generateTotp(secret: string, windowOffset: number = 0): string {
	const key = decodeBase32(secret);
	const timeStep = 30;
	const counter = Math.floor(Date.now() / 1000 / timeStep) + windowOffset;
	const counterBuffer = Buffer.alloc(8);
	counterBuffer.writeBigUInt64BE(BigInt(counter));

	const hmac = nodeCrypto.createHmac('sha1', key).update(counterBuffer).digest();
	const offset = hmac[hmac.length - 1] & 0x0f;
	const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1000000;

	return String(code).padStart(6, '0');
}

test('completes full signup flow with email + 2FA + purchase', async ({ page, context }: { page: any; context: any }) => {
	test.slow();
	test.setTimeout(180000);

	const signupDomain = getSignupTestDomain();
	test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');
	test.skip(!MAILOSAUR_API_KEY, 'MAILOSAUR_API_KEY is required for email validation.');
	if (!signupDomain) {
		throw new Error('Missing signup test domain after skip guard.');
	}
	const mailosaurServerId = getMailosaurServerId(signupDomain);
	if (!mailosaurServerId) {
		throw new Error('MAILOSAUR_SERVER_ID is missing and could not be derived from the signup domain.');
	}
	// Keep the derived server ID in the same variable the Mailosaur helpers use.
	// This avoids passing IDs around and keeps the test setup self-contained.
	MAILOSAUR_SERVER_ID = mailosaurServerId;

	// Grant clipboard permissions so "Copy" actions can be exercised reliably.
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	const signupEmail = buildSignupEmail(signupDomain);
	const signupUsername = signupEmail.split('@')[0];
	const signupPassword = 'SignupTest!234';

	// Base URL comes from PLAYWRIGHT_TEST_BASE_URL or the default in config.
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	// Open the login/signup dialog from the header.
	const headerLoginSignupButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginSignupButton).toBeVisible();
	await headerLoginSignupButton.click();
	await takeStepScreenshot(page, 'login-dialog');

	// Switch to the signup tab inside the login dialog.
	const loginTabs = page.locator('.login-tabs');
	await expect(loginTabs).toBeVisible();
	await loginTabs.getByRole('button', { name: /sign up/i }).click();
	await takeStepScreenshot(page, 'signup-alpha');

	// Alpha disclaimer: verify outbound links exist and continue.
	// Use href-based locators because link accessible names can vary by locale.
	const githubLink = page.locator('a[href*="github.com"]');
	const instagramLink = page.locator('a[href*="instagram.com"]');
	await expect(githubLink.first()).toBeVisible();
	await expect(instagramLink.first()).toBeVisible();

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'basics-step');

	// Basics step: fill email/username and exercise key toggles.
	const emailInput = page.locator('input[type="email"][autocomplete="email"]');
	const usernameInput = page.locator('input[autocomplete="username"]');
	await expect(emailInput).toBeVisible();
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
	await takeStepScreenshot(page, 'confirm-email');

	// Confirm email step: verify "Open mail app" link and enter OTP.
	const openMailLink = page.getByRole('link', { name: /open mail app/i });
	await expect(openMailLink).toHaveAttribute('href', /^mailto:/i);

	const confirmEmailMessage = await waitForMailosaurMessage({
		sentTo: signupEmail,
		receivedAfter: emailRequestedAt
	});
	const emailCode = extractSixDigitCode(confirmEmailMessage);
	expect(emailCode, 'Expected a 6-digit email confirmation code.').toBeTruthy();

	const confirmEmailInput = page.locator('input[inputmode="numeric"][maxlength="6"]');
	await confirmEmailInput.fill(emailCode);

	// Secure account step: choose password-based setup.
	const passwordOption = page.getByRole('button', { name: /password/i });
	await expect(passwordOption).toBeVisible();
	await takeStepScreenshot(page, 'secure-account');
	await passwordOption.click();
	await takeStepScreenshot(page, 'password-step');

	// Password step: fill and validate password fields.
	const passwordInputs = page.locator('input[autocomplete="new-password"]');
	await expect(passwordInputs).toHaveCount(2);
	await passwordInputs.nth(0).fill(signupPassword);
	await passwordInputs.nth(1).fill(signupPassword);
	await takeStepScreenshot(page, 'password-filled');

	// Password manager link should be present (no navigation needed).
	const passwordManagerLink = page.getByRole('link', { name: /password manager/i });
	await expect(passwordManagerLink).toHaveAttribute('href', /^https?:/i);

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'one-time-codes');

	// One-time codes step: show QR, copy secret, validate selectable secret input.
	const qrButton = page.getByRole('button', { name: /scan via 2fa app/i });
	await qrButton.click();
	await expect(page.locator('.qr-code')).toBeVisible();
	await takeStepScreenshot(page, 'one-time-codes-qr');
	await qrButton.click();
	await expect(page.locator('.qr-code')).toBeHidden();

	const copySecretButton = page.getByRole('button', { name: /copy secret/i });
	await copySecretButton.click();

	const secretInput = page.locator('input[aria-label="2FA Secret Key"]');
	await expect(secretInput).toBeVisible();
	await takeStepScreenshot(page, 'one-time-codes-secret');
	await secretInput.click();
	const secretInputSelected = await secretInput.evaluate((element: HTMLInputElement) => {
		const input = element as HTMLInputElement;
		return input.selectionStart === 0 && input.selectionEnd === input.value.length;
	});
	expect(secretInputSelected).toBe(true);

	const tfaSecret = await secretInput.inputValue();
	expect(tfaSecret, 'Expected a 2FA secret to be available after copy.').toBeTruthy();

	// Enter the generated TOTP to complete 2FA setup.
	const otpCode = generateTotp(tfaSecret);
	const otpInput = page.locator('#otp-code-input');
	await otpInput.fill(otpCode);

	// 2FA app reminder: pick an app name from suggestions and continue.
	const appNameInput = page.locator('input[placeholder*="app name"]');
	await appNameInput.click();
	await appNameInput.fill('Google');
	await takeStepScreenshot(page, 'tfa-app-reminder');
	const appResult = page.getByRole('button', { name: /google authenticator/i });
	await appResult.click();

	const tfaContinueButton = page.getByRole('button', { name: /continue/i });
	await tfaContinueButton.click();
	await takeStepScreenshot(page, 'backup-codes');

	// Backup codes step: download and confirm stored.
	const backupDownloadButton = page.getByRole('button', { name: /download/i }).first();
	const [backupDownload] = await Promise.all([
		page.waitForEvent('download'),
		backupDownloadButton.click()
	]);
	expect(await backupDownload.suggestedFilename()).toMatch(/backup/i);

	const backupConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(backupConfirmToggle, true);
	await takeStepScreenshot(page, 'backup-codes-confirmed');

	// Recovery key step: download, copy, print, and confirm stored.
	const recoveryDownloadButton = page.getByRole('button', { name: /download/i }).first();
	const [recoveryDownload] = await Promise.all([
		page.waitForEvent('download'),
		recoveryDownloadButton.click()
	]);
	await takeStepScreenshot(page, 'recovery-key');
	expect(await recoveryDownload.suggestedFilename()).toMatch(/recovery/i);

	const recoveryCopyButton = page.getByRole('button', { name: /^copy$/i });
	await recoveryCopyButton.click();

	const [printPage] = await Promise.all([
		context.waitForEvent('page'),
		page.getByRole('button', { name: /print/i }).click()
	]);
	await printPage.close();
	await takeStepScreenshot(page, 'recovery-key-actions');

	const recoveryConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(recoveryConfirmToggle, true);
	await takeStepScreenshot(page, 'credits-step');

	// Credits step: exercise gift card path (cancel) and navigation buttons.
	const giftCardButton = page.locator('.gift-card-button');
	await giftCardButton.scrollIntoViewIfNeeded();
	await giftCardButton.click();
	await takeStepScreenshot(page, 'credits-giftcard');
	await page.getByRole('button', { name: /cancel/i }).click();
	await takeStepScreenshot(page, 'credits-ready');

	const moreButton = page.getByRole('button', { name: /more/i });
	const lessButton = page.getByRole('button', { name: /less/i });
	if (await moreButton.isVisible()) {
		await moreButton.click();
	}
	if (await lessButton.isVisible()) {
		await lessButton.click();
	}

	// Purchase credits to proceed to payment step.
	await page.locator('.credits-package-container .buy-button').first().click();
	await takeStepScreenshot(page, 'payment-consent');

	// Payment step: consent to limited refund to reveal payment form.
	const consentToggle = page.locator('#limited-refund-consent-toggle');
	await setToggleChecked(consentToggle, true);
	await takeStepScreenshot(page, 'payment-form');

	// Payment security info button should open a Stripe privacy page (close immediately).
	const securityInfoButton = page.locator('.payment-form .text-button').first();
	await securityInfoButton.scrollIntoViewIfNeeded();
	const [securityInfoPage] = await Promise.all([
		context.waitForEvent('page'),
		securityInfoButton.click()
	]);
	await securityInfoPage.close();

	// Fill Stripe payment element with the test card.
	await fillStripeCardDetails(page, STRIPE_TEST_CARD_NUMBER);

	// Submit payment and wait for success.
	const paymentSubmittedAt = new Date().toISOString();
	await page.locator('.payment-form .buy-button').click();
	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 60000 });
	await takeStepScreenshot(page, 'payment-success');

	// Auto top-up step: finish setup and confirm redirect into the app.
	await page.getByRole('button', { name: /finish setup/i }).first().click();
	await page.waitForURL(/chat/);
	await takeStepScreenshot(page, 'chat');

	// Purchase confirmation email: verify key content and refund link.
	const purchaseEmail = await waitForMailosaurMessage({
		sentTo: signupEmail,
		subjectContains: 'Purchase confirmation',
		receivedAfter: paymentSubmittedAt,
		timeoutMs: 180000
	});

	const purchaseText = purchaseEmail.text?.body || '';
	expect(purchaseText).toMatch(/thanks for your purchase/i);
	expect(purchaseText).toMatch(/invoice/i);

	const refundLink = extractRefundLink(purchaseEmail);
	expect(refundLink, 'Expected a refund link in the purchase confirmation email.').toBeTruthy();
	if (!refundLink) {
		throw new Error('Refund link missing from purchase confirmation email.');
	}
	expect(() => new URL(refundLink)).not.toThrow();
});

