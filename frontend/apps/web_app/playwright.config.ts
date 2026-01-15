import type { PlaywrightTestConfig } from '@playwright/test';

/**
 * Playwright configuration for E2E tests that run against an already deployed
 * instance of the web app (for example https://app.dev.openmates.org).
 *
 * IMPORTANT:
 * - We intentionally do NOT start a local dev/preview server here.
 * - Tests should always navigate using relative URLs (page.goto('/')) so that
 *   the baseURL can be swapped between environments using PLAYWRIGHT_TEST_BASE_URL.
 */
const baseURL =
	process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';

const config: PlaywrightTestConfig = {
	use: {
		// Allow tests to call page.goto('/') and similar relative paths.
		baseURL
	},
	testDir: 'tests',
	testMatch: /(.+\.)?(test|spec)\.[jt]s/
};

export default config;
