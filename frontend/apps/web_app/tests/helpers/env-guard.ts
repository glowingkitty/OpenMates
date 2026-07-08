/**
 * Environment guard utilities for Playwright E2E tests.
 *
 * Consolidates per-test `test.skip(!VAR, ...)` calls into file-level guards.
 * Instead of 3 skip lines in every test, call one guard per describe block.
 *
 * Architecture: docs/contributing/guides/testing.md
 * Tests: Used by all credential-gated E2E specs
 */

export {};

type SkipCapableTest = {
	skip(condition: boolean, description: string): void;
};

type FeatureAvailabilityResponse = {
	disabled?: string[];
};

type PageWithRequest = {
	request: {
		get(url: string): Promise<{
			ok(): boolean;
			json(): Promise<FeatureAvailabilityResponse>;
		}>;
	};
};

function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') return 'https://api.openmates.org';
		if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
		if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return 'http://localhost:8000';
	} catch (error) {
		throw new Error(`PLAYWRIGHT_TEST_BASE_URL must be a valid URL when PLAYWRIGHT_TEST_API_URL is unset: ${String(error)}`);
	}
	throw new Error(`Cannot derive API URL from PLAYWRIGHT_TEST_BASE_URL=${baseUrl}. Set PLAYWRIGHT_TEST_API_URL explicitly.`);
}

/**
 * Skip all tests in the current suite if test account credentials are missing.
 * Replaces the per-test pattern:
 *   test.skip(!TEST_EMAIL, '...');
 *   test.skip(!TEST_PASSWORD, '...');
 *   test.skip(!TEST_OTP_KEY, '...');
 *
 * Usage (inside a test.describe or at top level):
 *   skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
 */
function skipWithoutCredentials(
	t: SkipCapableTest,
	email: string | undefined,
	password: string | undefined,
	otpKey: string | undefined
): void {
	t.skip(!email || !password || !otpKey, 'Test account credentials not configured (EMAIL/PASSWORD/OTP_KEY).');
}

/**
 * Skip all tests if Mailosaur credentials are missing.
 * For signup/email-verification specs that need the Mailosaur service.
 */
function skipWithoutMailosaur(
	t: SkipCapableTest,
	mailosaurApiKey: string | undefined,
	signupDomain?: string | undefined
): void {
	t.skip(!mailosaurApiKey, 'MAILOSAUR_API_KEY is required for email validation.');
	if (signupDomain !== undefined) {
		t.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');
	}
}

async function skipIfFeaturesDisabled(
	t: SkipCapableTest,
	page: PageWithRequest,
	featureIds: string[]
): Promise<void> {
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	const response = await page.request.get(`${apiUrl}/v1/features/availability`);
	if (!response.ok()) return;
	const availability = await response.json();
	const disabled = new Set<string>(availability.disabled ?? []);
	const blocked = featureIds.filter((featureId) => disabled.has(featureId));
	t.skip(blocked.length > 0, `Feature disabled on this server: ${blocked.join(', ')}`);
}

module.exports = { skipWithoutCredentials, skipWithoutMailosaur, skipIfFeaturesDisabled };
