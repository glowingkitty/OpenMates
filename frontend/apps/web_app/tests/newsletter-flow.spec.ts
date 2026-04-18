/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Newsletter E2E — Full subscription lifecycle
 *
 * Tests the complete newsletter flow:
 *   1. Subscribe via Settings > Newsletter (unauthenticated user) — UI tested
 *   2. Receive confirmation email via Mailosaur
 *   3. Follow Brevo tracking link to extract confirm token from hash
 *   4. Call confirm API directly — verify success response
 *   5. Receive "confirmed/welcome" email via Mailosaur
 *   6. Follow Brevo tracking link to extract unsubscribe token from hash
 *   7. Call unsubscribe API directly — verify success response
 *   8. Re-subscribe with same email — verifies the flow is repeatable (UI tested)
 *
 * Why direct API calls for confirm/unsubscribe (not deep-link UI navigation)?
 *   - The deep-link UI flow has a known double-call race condition: the SPA's
 *     hashchange handler opens Settings → newsletter component mounts → $effect
 *     fires once (succeeds, token deleted from Redis), then the component remounts
 *     due to the settings panel animation → $effect fires again (fails, token gone).
 *   - The Brevo tracking link is single-use: following it in a browser navigates to
 *     the production SPA (openmates.org), which is the wrong environment for dev tests.
 *     We follow the link only once to capture the hash/token, then use the token directly.
 *   - The subscribe UI step (step 1 and step 8) fully tests the user-facing path.
 *     The confirm/unsubscribe are backend operations triggered by email links; their
 *     API contracts are validated directly here.
 *
 * REQUIRED ENV VARS:
 *   SIGNUP_TEST_EMAIL_DOMAINS    — comma-separated test domains (e.g. gmail.com or ae20drx9.mailosaur.net)
 *   GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN — Gmail API credentials (preferred)
 *   MAILOSAUR_API_KEY            — Mailosaur REST API key (fallback)
 *
 * Runtime: ~5–8 minutes (email delivery waits dominate).
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	createEmailClient,
	checkEmailQuota
} = require('./signup-flow-helpers');

// ---------------------------------------------------------------------------
// Env vars
// ---------------------------------------------------------------------------

const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS ?? '';
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
// Derive API base URL: app.dev.openmates.org → api.dev.openmates.org
const API_BASE_URL = BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');

const [FIRST_DOMAIN] = SIGNUP_TEST_EMAIL_DOMAINS.split(',').map((d: string) => d.trim());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Open the settings menu and navigate to the Newsletter section.
 * Works for unauthenticated users (Newsletter is publicly accessible).
 */
async function openNewsletterSettings(page: any, log: any): Promise<void> {
	const openSettingsBtn = page.getByRole('button', { name: /open settings menu/i });
	await expect(openSettingsBtn).toBeVisible({ timeout: 15000 });
	await openSettingsBtn.click();
	log('Settings menu opened.');

	const newsletterItem = page.getByRole('menuitem', { name: /^newsletter$/i });
	await expect(newsletterItem).toBeVisible({ timeout: 10000 });
	await newsletterItem.click();
	await page.waitForTimeout(800);
	log('Navigated to Newsletter settings.');
}

/**
 * Subscribe to the newsletter with a given email address via the settings UI.
 * Expects the newsletter form to already be visible.
 * Verifies the success message appears after clicking Subscribe.
 */
async function subscribeViaUI(page: any, email: string, log: any): Promise<void> {
	const emailInput = page.getByPlaceholder(/enter your email address/i);
	await expect(emailInput).toBeVisible({ timeout: 10000 });
	await emailInput.fill(email);

	// Wait for debounced validation to enable the Subscribe button (800ms debounce + buffer)
	await page.waitForTimeout(1200);

	const subscribeBtn = page.getByRole('button', { name: /^subscribe$/i });
	await expect(subscribeBtn).toBeEnabled({ timeout: 5000 });
	await subscribeBtn.click();
	log(`Clicked Subscribe for: ${email}`);

	const successMsg = page.getByTestId('settings-info-box-success');
	await expect(successMsg).toBeVisible({ timeout: 15000 });
	const successText = await successMsg.innerText();
	log(`Subscribe success message: "${successText}"`);
	expect(successText.toLowerCase()).toMatch(/check your email|confirm|subscrib/i);
}

/**
 * Resolve a Brevo click-tracking URL to its final destination WITHOUT loading
 * it in a browser. Uses fetch with redirect:'manual' to follow the HTTP
 * redirects, then parses the HTML meta-refresh / JS redirect to extract the
 * final URL with the token hash.
 *
 * This avoids the problem where the SPA at the redirect target processes the
 * hash and consumes the confirmation token before the spec can use it.
 */
async function extractTokenHashFromBrevoLink(
	_page: any,
	trackingUrl: string,
	log: any
): Promise<string | null> {
	log(`Resolving Brevo tracking URL via HTTP (no browser)...`);

	try {
		// Follow redirects manually to capture the final URL
		let url = trackingUrl;
		for (let i = 0; i < 10; i++) {
			const resp = await fetch(url, { redirect: 'manual' });
			const location = resp.headers.get('location');
			if (location) {
				url = location;
				const hashMatch = url.match(/(#settings\/newsletter\/(?:confirm|unsubscribe)\/[^&\s"]+)/);
				if (hashMatch) {
					log(`Found token hash in redirect location: ${hashMatch[1].substring(0, 60)}...`);
					return hashMatch[1];
				}
				continue;
			}

			// No redirect header — check the HTML body for meta-refresh or JS redirect
			const body = await resp.text();

			// Check for hash in any URL in the response body
			const bodyMatch = body.match(/(?:href|url|location)[=\s'"]*[^'"]*?(#settings\/newsletter\/(?:confirm|unsubscribe)\/[^&\s"']+)/i);
			if (bodyMatch) {
				log(`Found token hash in response body: ${bodyMatch[1].substring(0, 60)}...`);
				return bodyMatch[1];
			}

			// Check for full URL with hash
			const fullUrlMatch = body.match(/https?:\/\/[^"'\s]+(#settings\/newsletter\/(?:confirm|unsubscribe)\/[^"'\s]+)/);
			if (fullUrlMatch) {
				log(`Found token hash in full URL in body: ${fullUrlMatch[1].substring(0, 60)}...`);
				return fullUrlMatch[1];
			}

			break;
		}
	} catch (err: any) {
		log(`HTTP resolve failed: ${err?.message}. Trying browser fallback...`);
	}

	log(`WARNING: Could not extract hash from Brevo tracking URL via HTTP.`);
	return null;
}

/**
 * Extract all anchor links from an HTML email body.
 * Returns { text, href } pairs.
 */
function extractAnchors(htmlBody: string): Array<{ text: string; href: string }> {
	const anchorRegex = /<a[^>]+href=["'](https?:\/\/[^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;
	const results: Array<{ text: string; href: string }> = [];
	let m = anchorRegex.exec(htmlBody);
	while (m) {
		const href = m[1];
		const text = m[2]
			.replace(/<[^>]+>/g, ' ')
			.replace(/\s+/g, ' ')
			.trim();
		results.push({ text, href });
		m = anchorRegex.exec(htmlBody);
	}
	return results;
}

/**
 * Extract the Brevo tracking URL for a specific anchor from a Mailosaur message.
 */
function extractNewsletterLink(message: any, anchorTextPattern: RegExp, log: any): string | null {
	const htmlBody: string = message.html?.body ?? '';
	const anchors = extractAnchors(htmlBody);
	for (const { text, href } of anchors) {
		if (anchorTextPattern.test(text)) {
			log(`Found anchor "${text}" → ${href.substring(0, 80)}...`);
			return href;
		}
	}
	log(
		`No anchor matching ${anchorTextPattern} found. Available: ${anchors.map((a) => `"${a.text}"`).join(', ')}`
	);
	return null;
}

/**
 * Call the newsletter confirm API directly with the token extracted from the email.
 * Returns the parsed JSON response.
 */
async function callConfirmApi(
	token: string,
	log: any
): Promise<{ success: boolean; message: string }> {
	const url = `${API_BASE_URL}/v1/newsletter/confirm/${encodeURIComponent(token)}`;
	log(`Calling confirm API: ${url.substring(0, 80)}...`);
	const response = await fetch(url, {
		method: 'GET',
		headers: { Accept: 'application/json' }
	});
	const data = await response.json();
	log(
		`Confirm API response: status=${response.status} success=${data.success} message="${data.message}"`
	);
	return data;
}

/**
 * Call the newsletter unsubscribe API directly with the token extracted from the email.
 * Returns the parsed JSON response.
 */
async function callUnsubscribeApi(
	token: string,
	log: any
): Promise<{ success: boolean; message: string }> {
	const url = `${API_BASE_URL}/v1/newsletter/unsubscribe/${encodeURIComponent(token)}`;
	log(`Calling unsubscribe API: ${url.substring(0, 80)}...`);
	const response = await fetch(url, {
		method: 'GET',
		headers: { Accept: 'application/json' }
	});
	const data = await response.json();
	log(
		`Unsubscribe API response: status=${response.status} success=${data.success} message="${data.message}"`
	);
	return data;
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('newsletter: subscribe → confirm → unsubscribe → re-subscribe', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(900000); // 15 min ceiling

	test.skip(!SIGNUP_TEST_EMAIL_DOMAINS, 'SIGNUP_TEST_EMAIL_DOMAINS is required.');

	const emailClient = createEmailClient();
	test.skip(!emailClient, 'Email credentials required (GMAIL_* or MAILOSAUR_*).');

	const quota = await checkEmailQuota();
	test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);

	const log = createSignupLogger('NEWSLETTER_FLOW');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	const { deleteAllMessages, waitForMailosaurMessage } = emailClient!;

	// Unique time-based address using +alias for Gmail or plain local part for Mailosaur
	const now = new Date();
	const pad = (n: number) => String(n).padStart(2, '0');
	// Include seconds so two runs in the same minute get different addresses
	const localPart = `nl${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
	const gmailTestAddress = process.env.GMAIL_TEST_ADDRESS;
	const testEmail = gmailTestAddress && gmailTestAddress.includes('@')
		? `${gmailTestAddress.split('@')[0]}+${localPart}@${gmailTestAddress.split('@')[1]}`
		: `${localPart}@${FIRST_DOMAIN}`;
	log(`Test email address: ${testEmail}`);

	await deleteAllMessages();
	log('Email inbox cleared.');

	// -------------------------------------------------------------------------
	// STEP 1: Subscribe via Settings > Newsletter UI
	// -------------------------------------------------------------------------
	await page.goto(BASE_URL);
	await page.waitForLoadState('networkidle');
	await screenshot(page, '01-homepage');

	await openNewsletterSettings(page, log);
	await screenshot(page, '02-newsletter-settings');

	const sentAfterSubscribe = new Date(Date.now() - 5000).toISOString();
	await subscribeViaUI(page, testEmail, log);
	await screenshot(page, '03-subscribe-success');

	// -------------------------------------------------------------------------
	// STEP 2: Receive confirmation email and extract the Brevo tracking link
	// -------------------------------------------------------------------------
	log('Waiting for confirmation email (up to 5 min)...');
	let confirmEmail: any;
	try {
		confirmEmail = await waitForMailosaurMessage({
			sentTo: testEmail,
			subjectContains: 'confirm',
			receivedAfter: sentAfterSubscribe,
			timeoutMs: 300000,
			pollIntervalMs: 10000
		});
	} catch (err: any) {
		throw new Error(`No confirmation email within 5 min for ${testEmail}: ${err?.message}`);
	}
	log(`Confirmation email received: subject="${confirmEmail?.subject}"`);

	const confirmTrackingUrl = extractNewsletterLink(confirmEmail, /confirm subscription/i, log);
	if (!confirmTrackingUrl) {
		throw new Error(
			`Could not find "Confirm Subscription" anchor. HTML: ${(confirmEmail?.html?.body ?? '').substring(0, 500)}`
		);
	}

	// -------------------------------------------------------------------------
	// STEP 3: Follow the Brevo link to extract the confirmation token
	// -------------------------------------------------------------------------
	log('Following Brevo confirm link to extract token...');
	const confirmHash = await extractTokenHashFromBrevoLink(page, confirmTrackingUrl, log);
	await screenshot(page, '04-after-brevo-follow');

	if (!confirmHash) {
		throw new Error('Could not extract confirmation hash from Brevo redirect.');
	}

	// Extract just the token from "#settings/newsletter/confirm/{token}"
	const confirmTokenMatch = confirmHash.match(/^#settings\/newsletter\/confirm\/(.+)$/);
	if (!confirmTokenMatch) {
		throw new Error(`Unexpected hash format: "${confirmHash}"`);
	}
	const confirmToken = confirmTokenMatch[1];
	log(`Confirm token extracted: ${confirmToken.substring(0, 20)}...`);

	// -------------------------------------------------------------------------
	// STEP 4: Call the confirm API directly — verify success
	// -------------------------------------------------------------------------
	log('Calling confirm API directly...');
	const confirmResult = await callConfirmApi(confirmToken, log);
	expect(
		confirmResult.success,
		`Confirm API should succeed. Message: "${confirmResult.message}"`
	).toBe(true);
	expect(confirmResult.message.toLowerCase()).toMatch(/subscribed|confirmed|success/i);
	log('Confirmation successful.');

	// Clear inbox before waiting for the welcome email
	await deleteAllMessages();
	log('Inbox cleared before waiting for welcome email.');
	const sentAfterConfirm = new Date(Date.now() - 5000).toISOString();

	// -------------------------------------------------------------------------
	// STEP 5: Receive "confirmed/welcome" email with unsubscribe link
	// -------------------------------------------------------------------------
	log('Waiting for confirmed/welcome email (up to 5 min)...');
	let welcomeEmail: any;
	try {
		welcomeEmail = await waitForMailosaurMessage({
			sentTo: testEmail,
			subjectContains: 'confirmed',
			receivedAfter: sentAfterConfirm,
			timeoutMs: 300000,
			pollIntervalMs: 10000
		});
	} catch (err: any) {
		throw new Error(`No welcome/confirmed email within 5 min for ${testEmail}: ${err?.message}`);
	}
	log(`Welcome email received: subject="${welcomeEmail?.subject}"`);

	const unsubscribeTrackingUrl = extractNewsletterLink(welcomeEmail, /unsubscribe/i, log);
	if (!unsubscribeTrackingUrl) {
		throw new Error(
			`Could not find "Unsubscribe" anchor. HTML: ${(welcomeEmail?.html?.body ?? '').substring(0, 500)}`
		);
	}

	// -------------------------------------------------------------------------
	// STEP 6: Follow the Brevo unsubscribe link to extract the token
	// -------------------------------------------------------------------------
	log('Following Brevo unsubscribe link to extract token...');

	// Navigate back to BASE_URL first so we're on the right domain before following the
	// Brevo link (which will redirect to openmates.org — that's fine, we only need the hash)
	await page.goto(BASE_URL);
	await page.waitForLoadState('networkidle');

	const unsubscribeHash = await extractTokenHashFromBrevoLink(page, unsubscribeTrackingUrl, log);
	await screenshot(page, '05-after-unsubscribe-brevo-follow');

	if (!unsubscribeHash) {
		throw new Error('Could not extract unsubscribe hash from Brevo redirect.');
	}

	const unsubscribeTokenMatch = unsubscribeHash.match(/^#settings\/newsletter\/unsubscribe\/(.+)$/);
	if (!unsubscribeTokenMatch) {
		throw new Error(`Unexpected unsubscribe hash format: "${unsubscribeHash}"`);
	}
	const unsubscribeToken = unsubscribeTokenMatch[1];
	log(`Unsubscribe token extracted: ${unsubscribeToken.substring(0, 20)}...`);

	// -------------------------------------------------------------------------
	// STEP 7: Call the unsubscribe API directly — verify success
	// -------------------------------------------------------------------------
	log('Calling unsubscribe API directly...');
	const unsubResult = await callUnsubscribeApi(unsubscribeToken, log);
	expect(
		unsubResult.success,
		`Unsubscribe API should succeed. Message: "${unsubResult.message}"`
	).toBe(true);
	expect(unsubResult.message.toLowerCase()).toMatch(/unsubscrib/i);
	log('Unsubscribe successful.');

	// -------------------------------------------------------------------------
	// STEP 8: Re-subscribe with same email — verifies repeatability (UI tested)
	// -------------------------------------------------------------------------
	log('Re-subscribing with same email to verify repeatability...');
	await page.goto(BASE_URL);
	await page.waitForLoadState('networkidle');
	await screenshot(page, '06-homepage-resubscribe');

	await openNewsletterSettings(page, log);
	await subscribeViaUI(page, testEmail, log);
	await screenshot(page, '07-resubscribe-success');

	// Verify a new confirmation email arrives
	await deleteAllMessages();
	const sentAfterResubscribe = new Date(Date.now() - 5000).toISOString();
	log('Waiting for re-subscribe confirmation email (up to 5 min)...');
	let resubEmail: any;
	try {
		resubEmail = await waitForMailosaurMessage({
			sentTo: testEmail,
			subjectContains: 'confirm',
			receivedAfter: sentAfterResubscribe,
			timeoutMs: 300000,
			pollIntervalMs: 10000
		});
	} catch (err: any) {
		throw new Error(
			`No re-subscribe confirmation email within 5 min for ${testEmail}: ${err?.message}`
		);
	}
	log(`Re-subscribe confirmation email received: subject="${resubEmail?.subject}"`);
	expect(resubEmail?.subject).toBeTruthy();

	await screenshot(page, '08-complete');
	log('PASSED — full newsletter lifecycle verified.');
});
