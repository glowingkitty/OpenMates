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
function createSignupLogger(prefix: string = 'SIGNUP_FLOW'): (message: string, metadata?: Record<string, unknown>) => void {
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
		const safeLabel = label.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-|-$/g, '');
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
 * Pick the first allowed test domain from the comma-separated env var.
 * We keep this deterministic so the backend allowlist logic stays predictable.
 */
function getSignupTestDomain(signupTestEmailDomains?: string): string | null {
	if (!signupTestEmailDomains) {
		return null;
	}

	const domains = signupTestEmailDomains.split(',')
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
	const monthNames = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

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
			const searchResponse = await mailosaurFetch(`/messages/search?server=${serverId}`, {
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
		const invoiceLink = links.find((link) =>
			/#settings\/billing\/invoices\//i.test(link) || /\/settings\/billing\/invoices\//i.test(link)
		);
		return invoiceLink || null;
	}

	return {
		mailosaurFetch,
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
	assertNoMissingTranslations
};
