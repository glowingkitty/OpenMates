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

import type { TestType } from '@playwright/test';

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
	t: TestType<any, any>,
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
	t: TestType<any, any>,
	mailosaurApiKey: string | undefined,
	signupDomain?: string | undefined
): void {
	t.skip(!mailosaurApiKey, 'MAILOSAUR_API_KEY is required for email validation.');
	if (signupDomain !== undefined) {
		t.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');
	}
}

module.exports = { skipWithoutCredentials, skipWithoutMailosaur };
