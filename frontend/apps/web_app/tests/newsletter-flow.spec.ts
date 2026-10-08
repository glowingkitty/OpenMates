/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Newsletter E2E — Full subscription lifecycle
 *
 * Tests the complete newsletter flow:
 *   1. Subscribe via Settings > Newsletter (unauthenticated user) — UI tested
 *   2. Receive confirmation email through the isolated inbox or Gmail
 *   3. Resolve the recipient link and extract its confirmation token
 *   4. Call confirm API directly — verify success response
 *   5. Receive "confirmed/welcome" email
 *   6. Resolve the recipient link and extract unsubscribe token
 *   7. Call unsubscribe API directly — verify success response
 *   8. Re-subscribe with same email — verifies the flow is repeatable (UI tested)
 *
 * Why direct API calls for confirm/unsubscribe (not deep-link UI navigation)?
 *   - The deep-link UI flow has a known double-call race condition: the SPA's
 *     hashchange handler opens Settings → newsletter component mounts → $effect
 *     fires once (succeeds, token deleted from Redis), then the component remounts
 *     due to the settings panel animation → $effect fires again (fails, token gone).
 *   - Recipient links may use the old app hash or the standalone confirmation path.
 *     We resolve tracking redirects without loading the token destination in a browser.
 *   - The subscribe UI step (step 1 and step 8) fully tests the user-facing path.
 *     The confirm/unsubscribe are backend operations triggered by email links; their
 *     API contracts are validated directly here.
 *
 * REQUIRED ENV VARS:
 *   SIGNUP_TEST_EMAIL_DOMAINS    — configured Gmail test domain
 *   GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN — Gmail API credentials (preferred)
 *   GMAIL_TEST_ADDRESS           — dedicated Gmail inbox used with aliases
 *
 * Runtime: ~5–8 minutes (email delivery waits dominate).
 */

const { test, expect } = require('./helpers/cookie-audit');
const { createHash, randomBytes } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { existsSync } = require('node:fs');
const path = require('node:path');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	createSignupEmailClient,
	checkSignupEmailQuota
} = require('./signup-flow-helpers');

// ---------------------------------------------------------------------------
// Env vars
// ---------------------------------------------------------------------------

const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS ?? '';
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
// Derive API base URL: app.dev.openmates.org → api.dev.openmates.org
const API_BASE_URL = (process.env.OPENMATES_E2E_API_URL || BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.')).replace(/\/$/, '');
const NEWSLETTER_RATE_WINDOW_MS = 60_000;
const NEWSLETTER_RATE_CLOCK_MARGIN_MS = 3_000;
let latestNewsletterSubscribeAttemptAt = 0;

const [FIRST_DOMAIN] = SIGNUP_TEST_EMAIL_DOMAINS.split(',').map((d: string) => d.trim());

// Both cases share the API's 2/minute IP quota. Record real browser POST attempts,
// then let the full quota window drain between cases. A retry starts a fresh
// worker, so its in-memory timestamp is unavailable and needs a full window.
test.describe.configure({ mode: 'serial' });
test.beforeEach(async ({ page }: { page: any }, testInfo: any) => {
	testInfo.setTimeout(900_000);
	const waitMs = testInfo.retry > 0
		? NEWSLETTER_RATE_WINDOW_MS + NEWSLETTER_RATE_CLOCK_MARGIN_MS
		: Math.max(0, latestNewsletterSubscribeAttemptAt + NEWSLETTER_RATE_WINDOW_MS + NEWSLETTER_RATE_CLOCK_MARGIN_MS - Date.now());
	if (waitMs > 0) await new Promise((resolve) => setTimeout(resolve, waitMs));
	page.on('request', (request: any) => {
		if (request.method() === 'POST' && new URL(request.url()).pathname === '/v1/newsletter/subscribe') {
			latestNewsletterSubscribeAttemptAt = Date.now();
		}
	});
});

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

/** Extract a recipient-held token without visiting its one-use destination. */
function tokenFromRecipientUrl(candidate: string, action: 'confirm' | 'unsubscribe'): string | null {
	const parsed = new URL(candidate.replaceAll('&amp;', '&'));
	const legacy = parsed.hash.match(new RegExp(`^#settings/newsletter/${action}/([^?&#]+)$`));
	const standalone = action === 'confirm'
		? parsed.pathname.match(/^\/newsletter\/confirm\/([^/]+)\/?$/)
		: null;
	const encoded = legacy?.[1] || standalone?.[1];
	return encoded ? decodeURIComponent(encoded) : null;
}

async function extractNewsletterToken(
	trackingUrl: string,
	action: 'confirm' | 'unsubscribe',
	log: any
): Promise<string | null> {
	let url = trackingUrl;
	for (let i = 0; i < 10; i++) {
		const token = tokenFromRecipientUrl(url, action);
		if (token) return token;
		const response = await fetch(url, { redirect: 'manual' });
		const location = response.headers.get('location');
		if (location) {
			url = new URL(location, url).href;
			continue;
		}
		const body = await response.text();
		for (const candidate of body.match(/https?:\/\/[^\s"'<>]+/g) ?? []) {
			try {
				const found = tokenFromRecipientUrl(candidate, action);
				if (found) return found;
			} catch { /* A non-URL fragment in tracking HTML is irrelevant. */ }
		}
		const legacy = body.match(new RegExp(`#settings/newsletter/${action}/([A-Za-z0-9_-]+)`));
		if (legacy) return legacy[1];
		if (action === 'confirm') {
			const standalone = body.match(/\/newsletter\/confirm\/([A-Za-z0-9_-]+)/);
			if (standalone) return standalone[1];
		}
		break;
	}
	log(`Could not resolve the ${action} recipient link without visiting its destination.`);
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
 * Extract the Brevo tracking URL for a specific anchor from a Gmail message.
 */
function extractNewsletterLink(message: any, anchorTextPattern: RegExp, log: any): string | null {
	const htmlBody: string = message.html?.body ?? '';
	const anchors = extractAnchors(htmlBody);
	for (const { text, href } of anchors) {
		if (anchorTextPattern.test(text)) {
			log(`Found newsletter recipient anchor "${text}".`);
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
	log('Calling confirm API with the recipient-held token.');
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
	log('Calling unsubscribe API with the recipient-held token.');
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

/** Read only the disposable subscriber's confirmed category row. */
function readIsolatedConfirmedCategories(email: string): Record<string, boolean> | null {
	if (process.env.OPENMATES_CI_ISOLATED !== '1' || process.env.OPENMATES_CI_MAILPIT_URL !== 'http://127.0.0.1:8025') {
		throw new Error('Newsletter category inspection requires isolated CI.');
	}
	const sourceRoot = process.env.OPENMATES_CI_SOURCE_ROOT || path.resolve(__dirname, '../../../..');
	const compose = path.join(sourceRoot, 'test-results/ci-private/compose.json');
	if (!existsSync(compose)) throw new Error('Isolated compose fixture is missing.');
	const hash = createHash('sha256').update(email.toLowerCase().trim()).digest('base64');
	const sql = "SELECT categories::text FROM public.newsletter_subscribers WHERE hashed_email = :'hashed_email' AND confirmed_at IS NOT NULL LIMIT 1;";
	const output = execFileSync('docker', [
		'compose', '-f', compose, 'exec', '-T', 'cms-database', 'sh', '-ec',
		'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -q -A -t -v ON_ERROR_STOP=1 -v hashed_email="$1" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -',
		'sh', hash
	], { cwd: sourceRoot, encoding: 'utf8', input: sql, timeout: 30_000 });
	return output.trim() ? JSON.parse(output.trim()) : null;
}

/** Wait for a fresh confirmation in the isolated inbox, excluding earlier mail for this address. */
async function waitForNextIsolatedConfirmation(email: string, previousToken: string, log: any): Promise<string> {
	const deadline = Date.now() + 120_000;
	while (Date.now() < deadline) {
		const response = await fetch('http://127.0.0.1:8025/api/v1/messages?limit=100', { signal: AbortSignal.timeout(10_000) });
		if (!response.ok) throw new Error(`Mailpit list failed (${response.status}).`);
		const listing = await response.json();
		for (const item of listing.messages || []) {
			if (!item.To?.some((to: { Address: string }) => to.Address?.toLowerCase() === email)) continue;
			const fullResponse = await fetch(`http://127.0.0.1:8025/api/v1/message/${encodeURIComponent(item.ID)}`, { signal: AbortSignal.timeout(10_000) });
			if (!fullResponse.ok) throw new Error(`Mailpit message read failed (${fullResponse.status}).`);
			const full = await fullResponse.json();
			const link = extractNewsletterLink({ html: { body: full.HTML || '' } }, /confirm/i, log);
			if (!link) continue;
			const token = await extractNewsletterToken(link, 'confirm', log);
			if (token && token !== previousToken) return token;
		}
		await new Promise((resolve) => setTimeout(resolve, 1000));
	}
	throw new Error('Timed out waiting for a new newsletter confirmation email.');
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

// contract-test: direct surface=gui.web assertions=newsletter.lifecycle.double-opt-in,newsletter.categories.default-and-migration,newsletter.surface.standalone-confirmation
test('landing newsletter confirms selected Apple beta and software preferences', async ({ page }: { page: any }) => {
	test.setTimeout(300_000);
	test.skip(process.env.OPENMATES_CI_ISOLATED !== '1' || process.env.OPENMATES_CI_MAILPIT_URL !== 'http://127.0.0.1:8025',
		'Requires the disposable isolated newsletter API and inbox.');
	const emailClient = createSignupEmailClient();
	if (!emailClient || emailClient.provider !== 'mailpit') throw new Error('Isolated Mailpit inbox is required.');
	const email = `ci-inbox+nl${randomBytes(6).toString('hex')}@example.com`;
	const initialChoices = { openmates_events: true, software_updates: true, apple_beta_updates: false };
	const choices = { openmates_events: true, software_updates: false, apple_beta_updates: true };
	const log = createSignupLogger('LANDING_NEWSLETTER');
	const requestedAfter = new Date(Date.now() - 5000).toISOString();
	await page.goto(new URL('/landing', BASE_URL).href);
	const form = page.getByTestId('landing-newsletter');
	await expect(form).toBeVisible();
	await expect(form.getByRole('checkbox', { name: /Apple app beta updates/ })).not.toBeChecked();
	await form.getByLabel('Email address').fill(email);
	const subscribed = page.waitForResponse((response: any) =>
		new URL(response.url()).pathname === '/v1/newsletter/subscribe' && response.request().method() === 'POST');
	await form.getByRole('button', { name: 'Subscribe', exact: true }).click();
	const response = await subscribed;
	expect(new URL(response.url()).origin).toBe(new URL(API_BASE_URL).origin);
	expect(response.request().postDataJSON().categories).toEqual(initialChoices);
	expect((await response.json()).success).toBe(true);
	await expect(form.getByTestId('newsletter-requested')).toBeVisible();
	expect(readIsolatedConfirmedCategories(email)).toBeNull();
	const message = await emailClient.waitForMessage({
		sentTo: email, subjectContains: 'confirm', receivedAfter: requestedAfter, timeoutMs: 120_000
	});
	const link = extractNewsletterLink(message, /confirm/i, log);
	if (!link) throw new Error('Confirmation recipient link is missing.');
	const token = await extractNewsletterToken(link, 'confirm', log);
	if (!token) throw new Error('Confirmation recipient token is missing.');
	const confirmed = await callConfirmApi(token, log);
	expect(confirmed.success).toBe(true);
	expect(readIsolatedConfirmedCategories(email)).toEqual(initialChoices);

	// A confirmed address must receive a fresh token, with preferences unchanged until it is used.
	await page.goto(new URL('/landing', BASE_URL).href);
	const updateForm = page.getByTestId('landing-newsletter');
	await expect(updateForm).toBeVisible();
	await updateForm.getByRole('checkbox', { name: 'Software updates', exact: true }).uncheck();
	await updateForm.getByRole('checkbox', { name: /Apple app beta updates/ }).check();
	await updateForm.getByLabel('Email address').fill(email);
	const updateRequested = page.waitForResponse((item: any) =>
		new URL(item.url()).pathname === '/v1/newsletter/subscribe' && item.request().method() === 'POST');
	await updateForm.getByRole('button', { name: 'Subscribe', exact: true }).click();
	const updateResponse = await updateRequested;
	expect(updateResponse.request().postDataJSON().categories).toEqual(choices);
	expect((await updateResponse.json()).success).toBe(true);
	expect(readIsolatedConfirmedCategories(email)).toEqual(initialChoices);
	const updateToken = await waitForNextIsolatedConfirmation(email, token, log);
	const updateConfirmed = await callConfirmApi(updateToken, log);
	expect(updateConfirmed.success).toBe(true);
	expect(readIsolatedConfirmedCategories(email)).toEqual(choices);
});

// contract-test: direct surface=gui.web assertions=newsletter.lifecycle.double-opt-in,newsletter.lifecycle.unsubscribe-resubscribe
test('newsletter: subscribe → confirm → unsubscribe → re-subscribe', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(900000); // 15 min ceiling

	test.skip(!SIGNUP_TEST_EMAIL_DOMAINS && !process.env.OPENMATES_CI_MAILPIT_URL,
		'A disposable inbox address or SIGNUP_TEST_EMAIL_DOMAINS is required.');

	const emailClient = createSignupEmailClient();
	test.skip(!emailClient, 'An isolated inbox or Gmail credentials are required.');

	const quota = await checkSignupEmailQuota();
	test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);

	const log = createSignupLogger('NEWSLETTER_FLOW');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	const { waitForMessage } = emailClient!;

	// Unique time-based Gmail alias.
	const now = new Date();
	const pad = (n: number) => String(n).padStart(2, '0');
	// Include seconds so two runs in the same minute get different addresses
	const localPart = `nl${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
	const gmailTestAddress = process.env.GMAIL_TEST_ADDRESS;
	const testEmail = emailClient?.provider === 'mailpit'
		? `ci-inbox+nl${randomBytes(6).toString('hex')}@example.com`
		: gmailTestAddress && gmailTestAddress.includes('@')
		? `${gmailTestAddress.split('@')[0]}+${localPart}@${gmailTestAddress.split('@')[1]}`
		: `${localPart}@${FIRST_DOMAIN}`;
	log(`Test email address: ${testEmail}`);

	if (emailClient?.provider === 'gmail') await emailClient.deleteAllMessages();

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
	// STEP 2: Receive confirmation email and extract its recipient link
	// -------------------------------------------------------------------------
	log('Waiting for confirmation email (up to 5 min)...');
	let confirmEmail: any;
	try {
		confirmEmail = await waitForMessage({
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
	// STEP 3: Resolve the recipient link without consuming the token
	// -------------------------------------------------------------------------
	log('Resolving confirmation recipient link...');
	const confirmToken = await extractNewsletterToken(confirmTrackingUrl, 'confirm', log);
	await screenshot(page, '04-after-brevo-follow');

	if (!confirmToken) {
		throw new Error('Could not extract the confirmation token from the email link.');
	}

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
	if (emailClient?.provider === 'gmail') await emailClient.deleteAllMessages();
	const sentAfterConfirm = new Date(Date.now() - 5000).toISOString();

	// -------------------------------------------------------------------------
	// STEP 5: Receive "confirmed/welcome" email with unsubscribe link
	// -------------------------------------------------------------------------
	log('Waiting for confirmed/welcome email (up to 5 min)...');
	let welcomeEmail: any;
	try {
		welcomeEmail = await waitForMessage({
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
	// STEP 6: Resolve the unsubscribe link without consuming the token
	// -------------------------------------------------------------------------
	log('Resolving unsubscribe recipient link...');

	// Navigate back to BASE_URL first so we're on the right domain before following the
	// Brevo link (which will redirect to openmates.org — that's fine, we only need the hash)
	await page.goto(BASE_URL);
	await page.waitForLoadState('networkidle');

	const unsubscribeToken = await extractNewsletterToken(unsubscribeTrackingUrl, 'unsubscribe', log);
	await screenshot(page, '05-after-unsubscribe-brevo-follow');

	if (!unsubscribeToken) {
		throw new Error('Could not extract the unsubscribe token from the email link.');
	}

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
	const sentAfterResubscribe = new Date(Date.now() - 5000).toISOString();
	await subscribeViaUI(page, testEmail, log);
	await screenshot(page, '07-resubscribe-success');

	// Verify a new confirmation email arrives
	if (emailClient?.provider === 'gmail') await emailClient.deleteAllMessages();
	log('Waiting for re-subscribe confirmation email (up to 5 min)...');
	let resubEmail: any;
	try {
		resubEmail = await waitForMessage({
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
