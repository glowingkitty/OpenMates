/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// These helpers intentionally avoid external dependencies so they can run inside
// the Playwright Docker image without adding repo-wide test packages. We keep
// CommonJS exports to align with the existing Playwright test setup.

const fs = require('fs');
const path = require('path');
const nodeCrypto = require('crypto');

/**
 * Default artifacts locations for Playwright screenshot output.
 * We centralize this here so both signup tests keep a consistent output layout.
 */
const ARTIFACTS_DIRNAME = 'artifacts';
const PREVIOUS_RUN_DIRNAME = 'previous_run';
const MAILOSAUR_BASE_URL = 'https://mailosaur.com/api';

/**
 * Build a structured step logger for signup tests.
 * The counter is intentionally scoped per test to keep logs readable.
 */
function createSignupLogger(
	prefix: string = 'SIGNUP_FLOW'
): (message: string, metadata?: Record<string, unknown>) => void {
	let stepIndex = 1;
	return (message: string, metadata: Record<string, unknown> = {}): void => {
		const timestamp = new Date().toISOString();
		const step = String(stepIndex).padStart(2, '0');
		stepIndex += 1;
		const metaSuffix = Object.keys(metadata).length ? ` | meta=${JSON.stringify(metadata)}` : '';
		console.log(`[${prefix}][${step}][${timestamp}] ${message}${metaSuffix}`);
	};
}

/**
 * Move any existing screenshots into artifacts/previous_run at startup.
 * This preserves the last run's images while keeping the current run clean.
 */
async function archiveExistingScreenshots(
	logStep: (message: string, metadata?: Record<string, unknown>) => void,
	{
		artifactsDirname = ARTIFACTS_DIRNAME,
		previousRunDirname = PREVIOUS_RUN_DIRNAME
	}: {
		artifactsDirname?: string;
		previousRunDirname?: string;
	} = {}
): Promise<void> {
	const artifactsDir = path.resolve(process.cwd(), artifactsDirname);
	const previousRunDir = path.join(artifactsDir, previousRunDirname);

	await fs.promises.mkdir(artifactsDir, { recursive: true });

	const existingEntries = await fs.promises.readdir(artifactsDir, { withFileTypes: true });
	const existingScreenshots = existingEntries.filter((entry: any) => {
		return entry.isFile() && entry.name.toLowerCase().endsWith('.png');
	});

	if (existingScreenshots.length === 0) {
		logStep('No prior screenshots found to archive.', { artifactsDir });
		return;
	}

	await fs.promises.mkdir(previousRunDir, { recursive: true });

	const previousRunEntries = await fs.promises.readdir(previousRunDir, { withFileTypes: true });
	for (const entry of previousRunEntries) {
		if (!entry.isFile() || !entry.name.toLowerCase().endsWith('.png')) {
			continue;
		}
		try {
			await fs.promises.unlink(path.join(previousRunDir, entry.name));
		} catch (error: any) {
			if (error?.code !== 'ENOENT') {
				throw error;
			}
			logStep('Screenshot already removed during cleanup.', { filename: entry.name });
		}
	}

	for (const entry of existingScreenshots) {
		const sourcePath = path.join(artifactsDir, entry.name);
		const destinationPath = path.join(previousRunDir, entry.name);
		try {
			await fs.promises.rename(sourcePath, destinationPath);
		} catch (error: any) {
			if (error?.code !== 'ENOENT') {
				throw error;
			}
			logStep('Screenshot already moved during cleanup.', { filename: entry.name });
		}
	}

	logStep('Archived prior screenshots into previous_run.', {
		movedCount: existingScreenshots.length,
		previousRunDir
	});
}

/**
 * Build a screenshot helper that numbers each capture for easier ordering.
 * Using a per-test counter prevents filename collisions between runs.
 */
function createStepScreenshotter(
	logStep: (message: string, metadata?: Record<string, unknown>) => void,
	{
		filenamePrefix = '',
		artifactsDirname = ARTIFACTS_DIRNAME
	}: {
		filenamePrefix?: string;
		artifactsDirname?: string;
	} = {}
): (page: any, label: string) => Promise<void> {
	let screenshotIndex = 1;
	return async (page: any, label: string): Promise<void> => {
		const safeLabel = label
			.toLowerCase()
			.replace(/[^a-z0-9-]+/g, '-')
			.replace(/^-|-$/g, '');
		const prefix = filenamePrefix ? `${filenamePrefix}-` : '';
		const filename = `${prefix}${String(screenshotIndex).padStart(2, '0')}-${safeLabel || 'step'}.png`;
		screenshotIndex += 1;
		// Small delay to allow UI transitions to settle before capture.
		await page.waitForTimeout(1000);
		await page.screenshot({
			path: `${artifactsDirname}/${filename}`,
			fullPage: true
		});
		logStep('Captured step screenshot.', { label, filename });
	};
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
	// Stripe Payment Element uses a single iframe titled "Secure payment input frame".
	// Input field names vary: Stripe uses "number"/"expiry"/"cvc" in the Payment Element
	// and "cardNumber"/"cardExpiry"/"cardCvc" in the older Elements API.
	// We use pressSequentially (not fill) to fire keyboard events that Stripe's JS needs
	// to properly validate the card and enable the submit button.
	const paymentFrame = page.frameLocator('iframe[title="Secure payment input frame"]');
	try {
		const cardInput = paymentFrame
			.locator('input[name="number"], input[name="cardNumber"], input[autocomplete="cc-number"]')
			.first();
		await cardInput.waitFor({ state: 'visible', timeout: 30000 });
		await cardInput.click();
		await cardInput.pressSequentially(cardNumber, { delay: 30 });

		const expiryInput = paymentFrame.locator(
			'input[name="expiry"], input[name="cardExpiry"], input[autocomplete="cc-exp"]'
		);
		await expiryInput.click();
		await expiryInput.pressSequentially('1234', { delay: 30 });

		const cvcInput = paymentFrame.locator(
			'input[name="cvc"], input[name="cardCvc"], input[autocomplete="cc-csc"]'
		);
		await cvcInput.click();
		await cvcInput.pressSequentially('123', { delay: 30 });
		return;
	} catch {
		// Fallback to the split Stripe iframe layout (card number/expiry/CVC separate).
	}

	const cardNumberFrame = page.frameLocator('iframe[title*="card number"]');
	const expFrame = page.frameLocator('iframe[title*="expiration"]');
	const cvcFrame = page.frameLocator('iframe[title*="security code"], iframe[title*="CVC"]');

	const splitCardInput = cardNumberFrame.locator(
		'input[name="cardNumber"], input[autocomplete="cc-number"]'
	);
	await splitCardInput.click();
	await splitCardInput.pressSequentially(cardNumber, { delay: 30 });

	const splitExpInput = expFrame.locator('input[name="cardExpiry"], input[autocomplete="cc-exp"]');
	await splitExpInput.click();
	await splitExpInput.pressSequentially('1234', { delay: 30 });

	const splitCvcInput = cvcFrame.locator('input[name="cardCvc"], input[autocomplete="cc-csc"]');
	await splitCvcInput.click();
	await splitCvcInput.pressSequentially('123', { delay: 30 });
}

/**
 * Pick the first allowed test domain from the comma-separated env var.
 * We keep this deterministic so the backend allowlist logic stays predictable.
 */
function getSignupTestDomain(signupTestEmailDomains?: string): string | null {
	if (!signupTestEmailDomains) {
		return null;
	}

	const domains = signupTestEmailDomains
		.split(',')
		.map((domain) => domain.trim())
		.filter(Boolean);

	return domains.length > 0 ? domains[0] : null;
}

/**
 * Derive the Mailosaur server ID from the test domain when possible.
 * Mailosaur domains are typically <server-id>.mailosaur.net, so we can
 * parse the server ID if the env var is not set.
 */
function getMailosaurServerId(signupDomain: string, configuredServerId?: string): string | null {
	if (configuredServerId) {
		return configuredServerId;
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
 */
function buildSignupEmail(domain: string): string {
	const now = new Date();
	const monthNames = [
		'jan',
		'feb',
		'mar',
		'apr',
		'may',
		'jun',
		'jul',
		'aug',
		'sep',
		'oct',
		'nov',
		'dec'
	];

	const month = monthNames[now.getMonth()];
	const day = String(now.getDate()).padStart(2, '0');
	const hour = String(now.getHours()).padStart(2, '0');
	const minute = String(now.getMinutes()).padStart(2, '0');

	return `${month}${day}${hour}${minute}@${domain}`;
}

/**
 * Create a Mailosaur client wrapper with basic auth and polling helpers.
 * The goal is to keep mail polling logic consistent across signup tests.
 */
function createMailosaurClient({
	apiKey,
	serverId,
	baseUrl = MAILOSAUR_BASE_URL
}: {
	apiKey: string;
	serverId: string;
	baseUrl?: string;
}) {
	if (!apiKey) {
		throw new Error('Mailosaur API key is required for mail helper usage.');
	}
	if (!serverId) {
		throw new Error('Mailosaur server ID is required for mail helper usage.');
	}

	/**
	 * Build the Mailosaur basic auth header (API key as username, blank password).
	 * This is required for all Mailosaur REST calls.
	 */
	function buildMailosaurAuthHeader(): string {
		const token = Buffer.from(`${apiKey}:`).toString('base64');
		return `Basic ${token}`;
	}

	/**
	 * Call the Mailosaur REST API with basic error handling and JSON parsing.
	 * We keep this generic so email confirmation and purchase checks can share it.
	 */
	async function mailosaurFetch(
		mailPath: string,
		options: {
			method?: string;
			headers?: Record<string, string>;
			body?: Record<string, unknown>;
		} = {}
	): Promise<any> {
		const response = await fetch(`${baseUrl}${mailPath}`, {
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
	 * Mailosaur message shape (minimal fields used in signup tests).
	 */
	interface MailosaurMessage {
		id?: string;
		_id?: string;
		subject?: string;
		text?: { body?: string };
		html?: { body?: string };
	}

	/**
	 * Delete all messages from the Mailosaur server inbox.
	 *
	 * Use this before a test that relies on mail arrival to ensure no leftover
	 * emails from previous runs interfere with the current run. The Mailosaur
	 * DELETE /messages?server=<id> endpoint removes all messages in the server.
	 */
	async function deleteAllMessages(): Promise<void> {
		const response = await fetch(`${baseUrl}/messages?server=${serverId}`, {
			method: 'DELETE',
			headers: {
				Authorization: buildMailosaurAuthHeader()
			}
		});
		// 204 = success, 404 = already empty — both are acceptable
		if (!response.ok && response.status !== 404) {
			const errorBody = await response.text();
			throw new Error(`Mailosaur delete-all error (${response.status}): ${errorBody}`);
		}
	}

	/**
	 * Poll Mailosaur for a message that matches a recipient and optional subject.
	 * We keep the polling explicit to avoid implicit SDK retries and to reduce
	 * hidden test flakiness.
	 *
	 * Uses the GET /messages list endpoint (not POST /messages/search) because
	 * the search endpoint has a search-indexing delay that can cause fresh emails
	 * to not be found for several minutes after arrival. The list endpoint reflects
	 * real-time inbox state.
	 *
	 * Client-side filtering is applied for receivedAfter and subjectContains since
	 * the Mailosaur list API does not filter by these fields reliably.
	 *
	 * Best practice: call deleteAllMessages() before the test so no stale emails
	 * from previous runs interfere.
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
		const receivedAfterMs = new Date(receivedAfter).getTime();

		while (Date.now() < deadline) {
			let listResponse: any = null;
			const elapsed = Math.round((Date.now() - (deadline - timeoutMs)) / 1000);
			try {
				// Use GET /messages for real-time inbox listing (POST /search has indexing lag)
				listResponse = await mailosaurFetch(`/messages?server=${serverId}`);
			} catch (err: any) {
				// 404 = empty inbox — treat as no results
				if (err?.message?.includes('404')) {
					console.log(`[Mailosaur] ${elapsed}s: 404 (empty inbox)`);
					listResponse = { items: [] };
				} else {
					throw err; // Re-throw genuine errors
				}
			}

			const allItems: any[] = listResponse.items || [];
			console.log(
				`[Mailosaur] ${elapsed}s: GET /messages returned ${allItems.length} item(s)`,
				allItems.map((i: any) => `${i.received} — ${i.subject}`)
			);

			// Apply client-side filters: sentTo, receivedAfter, subjectContains
			const matching = allItems.filter((item: any) => {
				// sentTo: check the `to` array
				const toAddresses: any[] = item.to || [];
				const toMatch = toAddresses.some(
					(addr: any) => addr.email?.toLowerCase() === sentTo.toLowerCase()
				);
				if (!toMatch) {
					console.log(`[Mailosaur] Skipping — sentTo mismatch: ${JSON.stringify(toAddresses)}`);
					return false;
				}

				// receivedAfter: client-side time filter
				if (receivedAfterMs) {
					const receivedMs = new Date(item.received).getTime();
					if (receivedMs < receivedAfterMs) {
						console.log(`[Mailosaur] Skipping — too old: ${item.received} < ${receivedAfter}`);
						return false;
					}
				}

				// subjectContains: case-insensitive substring match
				if (subjectContains) {
					const subject: string = item.subject || '';
					if (!subject.toLowerCase().includes(subjectContains.toLowerCase())) {
						console.log(`[Mailosaur] Skipping — subject mismatch: "${subject}"`);
						return false;
					}
				}

				return true;
			});

			if (matching.length > 0) {
				console.log(
					`[Mailosaur] Found matching message: ${matching[0].received} — ${matching[0].subject}`
				);
				const messageId = matching[0].id || matching[0]._id;
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
	 * Extract all clickable links from a Mailosaur message payload.
	 * We consolidate hrefs, raw URLs, and Mailosaur-parsed links for debugging.
	 */
	function extractMessageLinks(message: MailosaurMessage): string[] {
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

		// De-duplicate to keep logs readable.
		return Array.from(new Set(links));
	}

	/**
	 * Extract a refund link from a purchase confirmation email.
	 * We look for a URL that includes "refund" to align with the email template.
	 */
	function extractRefundLink(message: MailosaurMessage): string | null {
		const links = extractMessageLinks(message);
		const htmlBody = message.html?.body || '';
		const textBody = message.text?.body || '';
		const refundKeyword = /refund/i;

		// Primary match: direct refund URL with the keyword in the link itself.
		const refundLink = links.find((link) => refundKeyword.test(link));
		if (refundLink) {
			return refundLink;
		}

		// Secondary match: URL appears near "refund" language in the text body.
		for (const link of links) {
			const linkIndex = textBody.indexOf(link);
			if (linkIndex === -1) {
				continue;
			}
			const contextStart = Math.max(0, linkIndex - 120);
			const contextEnd = Math.min(textBody.length, linkIndex + link.length + 120);
			const contextSlice = textBody.slice(contextStart, contextEnd);
			if (refundKeyword.test(contextSlice)) {
				return link;
			}
		}

		// Tertiary match: anchor text or surrounding HTML mentions refunds.
		const anchorRegex = /<a [^>]*href=["']([^"']+)["'][^>]*>(.*?)<\/a>/gis;
		let anchorMatch = anchorRegex.exec(htmlBody);
		while (anchorMatch) {
			const href = anchorMatch[1];
			const anchorText = anchorMatch[2].replace(/<[^>]*>/g, ' ');
			const anchorIndex = anchorMatch.index;
			const htmlContext = htmlBody.slice(
				Math.max(0, anchorIndex - 120),
				Math.min(htmlBody.length, anchorIndex + anchorMatch[0].length + 120)
			);
			if (refundKeyword.test(anchorText) || refundKeyword.test(htmlContext)) {
				return href;
			}
			anchorMatch = anchorRegex.exec(htmlBody);
		}

		// Fallback: some templates link to billing invoices without the explicit /refund suffix.
		// We treat those as valid refund entry points when the refund action is handled in-app.
		const invoiceLink = links.find(
			(link) =>
				/#settings\/billing\/invoices\//i.test(link) ||
				/\/settings\/billing\/invoices\//i.test(link)
		);
		return invoiceLink || null;
	}

	return {
		mailosaurFetch,
		deleteAllMessages,
		waitForMailosaurMessage,
		extractSixDigitCode,
		extractMessageLinks,
		extractRefundLink
	};
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

/**
 * Assert that no missing translation placeholders are visible on the page.
 *
 * Detects two failure modes:
 *   1. `[T:key.name]` — the i18n system's explicit placeholder when a key is missing.
 *   2. `[object Object]` — rendered when a translation key accidentally points to an
 *      intermediate YAML node (object) instead of a leaf string, or when any non-string
 *      value leaks into the DOM.
 *
 * Throws a descriptive error listing every unique occurrence found.
 *
 * Usage: call after the page has fully loaded and rendered its UI.
 *
 * @param page - Playwright page object
 */
async function assertNoMissingTranslations(page: any): Promise<void> {
	const body = await page.locator('body').innerText();
	const errors: string[] = [];

	// Check for missing translation placeholders: [T:some.key]
	const missingKeys = body.match(/\[T:[^\]]+\]/g);
	if (missingKeys) {
		const unique = [...new Set(missingKeys)];
		errors.push(`Missing translation keys:\n  ${unique.join('\n  ')}`);
	}

	// Check for [object Object] — indicates a non-string value leaked into the DOM,
	// typically from a translation key pointing to an object node instead of a string.
	const objectMatches = body.match(/\[object Object\]/g);
	if (objectMatches) {
		errors.push(
			`Found ${objectMatches.length} occurrence(s) of "[object Object]" in the DOM — likely a broken translation or non-string value rendered as text.`
		);
	}

	if (errors.length > 0) {
		throw new Error(`Translation issues detected:\n${errors.join('\n')}`);
	}
}

/**
 * Retrieve test account credentials for a given worker slot (1-5).
 *
 * The runner passes PLAYWRIGHT_WORKER_SLOT=1..5 to each container so that
 * parallel Playwright workers use separate accounts and avoid test collisions.
 *
 * Env var naming convention:
 *   Slot 1: OPENMATES_TEST_ACCOUNT_1_EMAIL  (or fallback: OPENMATES_TEST_ACCOUNT_EMAIL)
 *   Slot 2: OPENMATES_TEST_ACCOUNT_2_EMAIL
 *   ...
 *   Slot 5: OPENMATES_TEST_ACCOUNT_5_EMAIL
 *
 * When the numbered slot vars are not set (e.g. running a single test manually),
 * we fall back to the base OPENMATES_TEST_ACCOUNT_* vars for backward compatibility.
 */
function getTestAccount(slot?: number): {
	email: string | undefined;
	password: string | undefined;
	otpKey: string | undefined;
} {
	const s = slot ?? parseInt(process.env.PLAYWRIGHT_WORKER_SLOT || '1', 10);
	return {
		email:
			process.env[`OPENMATES_TEST_ACCOUNT_${s}_EMAIL`] || process.env.OPENMATES_TEST_ACCOUNT_EMAIL,
		password:
			process.env[`OPENMATES_TEST_ACCOUNT_${s}_PASSWORD`] ||
			process.env.OPENMATES_TEST_ACCOUNT_PASSWORD,
		otpKey:
			process.env[`OPENMATES_TEST_ACCOUNT_${s}_OTP_KEY`] ||
			process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY
	};
}

/**
 * Build the hash fragment params for E2E debug log forwarding.
 *
 * When E2E_DEBUG_TOKEN and E2E_RUN_ID are set (injected by run-tests-worker.sh),
 * returns a hash fragment that activates client-side log forwarding to OpenObserve.
 * This works pre-login so the full test flow — including the login page itself — is
 * captured and queryable via `debug.py logs --debug-id {runId}`.
 *
 * Usage in specs:
 *   await page.goto(getE2EDebugUrl('/'));
 *   await page.goto(getE2EDebugUrl('/#gift-card=CODE'));   // composable with other hashes
 *
 * When env vars are missing (local manual runs), returns the base URL unchanged.
 */
function getE2EDebugUrl(path: string = '/'): string {
	const token = process.env.E2E_DEBUG_TOKEN;
	const runId = process.env.E2E_RUN_ID;

	// Graceful degradation: if token or run ID is missing, just return the path unchanged.
	if (!token || !runId) return path;

	// Build the spec-scoped run ID so logs from individual specs are distinguishable.
	// Format: {runId}-{specName} where specName is derived from the test file or caller.
	const specName = process.env.PLAYWRIGHT_TEST_FILE
		? process.env.PLAYWRIGHT_TEST_FILE.replace(/^tests\//, '').replace(/\.spec\.ts$/, '')
		: 'unknown';
	const scopedRunId = `${runId}-${specName}`;

	// Parse the existing hash (if any) so we can compose the params
	const hashIndex = path.indexOf('#');
	const basePath = hashIndex >= 0 ? path.slice(0, hashIndex) : path;
	const existingHash = hashIndex >= 0 ? path.slice(hashIndex + 1) : '';

	// Merge e2e-debug params with any existing hash params using &
	const existingParams = existingHash ? `${existingHash}&` : '';
	const e2eParams = `e2e-debug=${encodeURIComponent(scopedRunId)}&e2e-token=${encodeURIComponent(token)}`;

	return `${basePath}#${existingParams}${e2eParams}`;
}

/**
 * Append a <<<TEST_MOCK:fixture_id>>> marker to a chat message when E2E_USE_MOCKS is set.
 *
 * When tests run with E2E_USE_MOCKS=1, the backend replays a pre-recorded fixture
 * instead of calling real LLM providers and external APIs. This eliminates inference
 * costs and makes tests deterministic.
 *
 * For multi-turn conversations, each message needs its own fixture ID (e.g., "code_gen_turn1",
 * "code_gen_turn2"). The fixture ID maps to a JSON file in backend/apps/ai/testing/fixtures/.
 *
 * An optional speed profile controls the simulated streaming speed:
 *   "slow"    (~60 tps)   — for testing streaming UX behavior
 *   "medium"  (~150 tps)  — realistic for most models
 *   "fast"    (~500 tps)  — simulates fast providers (Cerebras, Groq)
 *   "instant" (0ms delay) — default for CI, fastest execution
 *
 * @param message    The chat message text to send
 * @param fixtureId  Identifier for the fixture file (e.g., "chat_flow_capital")
 * @param speed      Optional speed profile override (default: uses fixture's speed_profile)
 * @returns          Message text, optionally with mock marker appended
 *
 * @example
 *   // Basic usage:
 *   await page.keyboard.type(withMockMarker('Capital of Germany?', 'chat_flow_capital'));
 *
 *   // With speed override for streaming UX tests:
 *   await page.keyboard.type(withMockMarker('Hello', 'chat_scroll_test', 'slow'));
 *
 *   // Multi-turn conversation:
 *   await page.keyboard.type(withMockMarker('Write a function', 'code_gen_turn1'));
 *   // ... wait for response ...
 *   await page.keyboard.type(withMockMarker('Add error handling', 'code_gen_turn2'));
 */
function withMockMarker(message: string, fixtureId: string, speed?: string): string {
	if (process.env.E2E_RECORD_FIXTURES) {
		// Record mode: run real LLMs but capture the response as a fixture file
		return `${message} <<<TEST_RECORD:${fixtureId}>>>`;
	}
	if (process.env.E2E_USE_MOCKS) {
		const speedSuffix = speed ? `:${speed}` : '';
		return `${message} <<<TEST_MOCK:${fixtureId}${speedSuffix}>>>`;
	}
	return message;
}

/**
 * Append a <<<TEST_RECORD:fixture_id>>> marker to a chat message.
 *
 * Used to record a real LLM response as a fixture file. The test runs normally
 * (hitting real APIs) but the backend captures all events and saves them as
 * a fixture JSON file in backend/apps/ai/testing/fixtures/{fixtureId}.json.
 *
 * After recording, the fixture can be replayed with withMockMarker().
 *
 * @param message    The chat message text to send
 * @param fixtureId  Identifier for the fixture file to create
 * @returns          Message text with record marker appended
 */
function withRecordMarker(message: string, fixtureId: string): string {
	return `${message} <<<TEST_RECORD:${fixtureId}>>>`;
}

/**
 * Append a <<<TEST_LIVE_MOCK:group_id>>> marker to a chat message when E2E_USE_LIVE_MOCKS is set.
 *
 * Unlike withMockMarker (which skips the entire pipeline and replays a fixture),
 * live mock mode runs the FULL processing pipeline (preprocessing, main inference,
 * postprocessing, billing) but intercepts external API calls (LLM providers, skill
 * HTTP requests) with cached record-and-replay responses. This tests everything
 * except the parts that cost money.
 *
 * The group_id namespaces cached responses so different test flows don't collide
 * (e.g., "web_search_flow", "travel_search_flow").
 *
 * @param message  The chat message text to send
 * @param groupId  Namespace for cached API responses (e.g., "web_search_flow")
 * @returns        Message text with live mock/record marker appended
 *
 * @example
 *   await page.keyboard.type(withLiveMockMarker('Search for flights to Paris', 'travel_search'));
 */
function withLiveMockMarker(message: string, groupId: string): string {
	if (process.env.E2E_RECORD_LIVE_FIXTURES) {
		// Record mode: run real APIs and cache responses for future replay
		return `${message} <<<TEST_LIVE_RECORD:${groupId}>>>`;
	}
	if (process.env.E2E_USE_LIVE_MOCKS) {
		// Replay mode: use cached API responses (zero cost)
		return `${message} <<<TEST_LIVE_MOCK:${groupId}>>>`;
	}
	// No env var set: send message without marker (real APIs, real costs)
	return message;
}

/**
 * Append a <<<TEST_LIVE_RECORD:group_id>>> marker to a chat message.
 *
 * Used to record real API responses for live mock replay. The test runs the full
 * pipeline with real APIs, but the backend caches all external API responses
 * (LLM calls, skill HTTP requests) as JSON files for future replay.
 *
 * After recording, the cached responses can be replayed with withLiveMockMarker().
 *
 * @param message  The chat message text to send
 * @param groupId  Namespace for cached API responses
 * @returns        Message text with live record marker appended
 */
function withLiveRecordMarker(message: string, groupId: string): string {
	return `${message} <<<TEST_LIVE_RECORD:${groupId}>>>`;
}

module.exports = {
	ARTIFACTS_DIRNAME,
	PREVIOUS_RUN_DIRNAME,
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	setToggleChecked,
	fillStripeCardDetails,
	getSignupTestDomain,
	getMailosaurServerId,
	buildSignupEmail,
	createMailosaurClient,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl,
	withMockMarker,
	withRecordMarker,
	withLiveMockMarker,
	withLiveRecordMarker,
};
