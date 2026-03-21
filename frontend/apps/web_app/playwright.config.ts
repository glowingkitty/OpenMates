import type { PlaywrightTestConfig } from '@playwright/test';

/**
 * Playwright configuration for E2E tests that run against an already deployed
 * instance of the web app.
 *
 * IMPORTANT:
 * - We intentionally do NOT start a local dev/preview server here.
 * - Tests should always navigate using relative URLs (page.goto('/')) so that
 *   the baseURL can be swapped between environments using PLAYWRIGHT_TEST_BASE_URL.
 * - PLAYWRIGHT_TEST_BASE_URL must be set explicitly (via E2E_DEV_TEST_BASE_URL
 *   or E2E_PROD_TEST_BASE_URL in .env). No hardcoded default — a missing var
 *   throws immediately so misconfiguration is never silent.
 */
const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL;
if (!baseURL) {
	throw new Error(
		'PLAYWRIGHT_TEST_BASE_URL is not set. ' +
			'Set E2E_DEV_TEST_BASE_URL (or E2E_PROD_TEST_BASE_URL) in .env and ensure ' +
			'run-tests-worker.sh forwards it to the Docker container.'
	);
}

const config: PlaywrightTestConfig = {
	use: {
		// Allow tests to call page.goto('/') and similar relative paths.
		baseURL
	},
	testDir: 'tests',
	testMatch: /(.+\.)?(test|spec)\.[jt]s/,
	// Retry flaky tests once — the dev server has variable latency which causes
	// intermittent timeouts on login fields, message rendering, etc.
	retries: 1
};

export default config;
