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

const browserChannel = process.env.PLAYWRIGHT_BROWSER_CHANNEL;
if (browserChannel && browserChannel !== 'chrome') {
	throw new Error('PLAYWRIGHT_BROWSER_CHANNEL only supports "chrome" in this config.');
}

const videoMode = process.env.PLAYWRIGHT_VIDEO_MODE;
if (videoMode && videoMode !== 'on' && videoMode !== 'off') {
	throw new Error('PLAYWRIGHT_VIDEO_MODE only supports "on" or "off" in this config.');
}

const resolvedVideoMode = (videoMode || 'on') as 'on' | 'off';
const videoWidth = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const videoHeight = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_HEIGHT || '', 10);
if ((process.env.PLAYWRIGHT_VIDEO_WIDTH || process.env.PLAYWRIGHT_VIDEO_HEIGHT) && !(videoWidth > 0 && videoHeight > 0)) {
	throw new Error('PLAYWRIGHT_VIDEO_WIDTH and PLAYWRIGHT_VIDEO_HEIGHT must both be positive integers when set.');
}
const videoSize = videoWidth > 0 && videoHeight > 0 ? { width: videoWidth, height: videoHeight } : undefined;
const isPhoneProofProfile = videoWidth === 390 && videoHeight === 844;
const isLiveFixtureRecording = process.env.E2E_RECORD_LIVE_FIXTURES === '1';

const config: PlaywrightTestConfig = {
	use: {
		// Allow tests to call page.goto('/') and similar relative paths.
		baseURL,
		...(videoSize ? { viewport: videoSize } : {}),
		...(isPhoneProofProfile ? { hasTouch: true, isMobile: true } : {}),
		...(browserChannel ? { channel: browserChannel } : {}),
		// Capture artifacts for all tests — used by MD report generator
		// (test-results/reports/) to show inline screenshots per step.
		// Uploaded to GHA artifacts and synced to test-results/screenshots/.
		screenshot: 'on',
		// Keep a browser recording for every spec run in GitHub artifacts.
		// Videos stay in Actions storage; local/Obsidian processing stores links only.
		video: videoSize ? { mode: resolvedVideoMode, size: videoSize } : resolvedVideoMode,
		trace: 'off',
		launchOptions: {
			args: [
				// Suppress Chrome's in-page credential/password-manager overlays.
				// These appear after account creation and block clicks on the underlying UI.
				'--disable-save-password-bubble',
				'--disable-features=AutofillSaveCardInfoToAccountSignedIn,PasswordImport',
				'--use-mock-keychain'
			]
		}
	},
	testDir: 'tests',
	testMatch: /(.+\.)?(test|spec)\.[jt]s/,
	// Recording can spend provider budget, so it must never retry a browser send.
	// Replay and ordinary specs retain one retry for variable dev-server latency.
	retries: isLiveFixtureRecording ? 0 : 1
};

export default config;
