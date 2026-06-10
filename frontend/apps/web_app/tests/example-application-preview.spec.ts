/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Habit Garden example application preview E2E coverage.
 *
 * Runs against app.dev.openmates.org via scripts/run_tests.py. The spec proves
 * example application previews are auth-gated before billing and run through the
 * user-content gateway after login.
 */
export {};

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getE2EDebugUrl,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { closeFullscreen } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const fs = require('fs');
const path = require('path');

const HABIT_GARDEN_CHAT_ID = 'example-habit-garden-vite-app';
const HABIT_GARDEN_URL = `/#chat-id=${HABIT_GARDEN_CHAT_ID}`;
const HABIT_GARDEN_APPLICATION_EMBED_ID = '4020cf81-f490-4da8-bd42-c4ea456327f3';
const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';

async function openHabitGardenApplication(page: any): Promise<any> {
	await page.goto(getE2EDebugUrl(HABIT_GARDEN_URL), { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('load');
	const applicationEmbed = page.locator(
		`[data-testid="embed-preview"][data-embed-id="${HABIT_GARDEN_APPLICATION_EMBED_ID}"][data-status="finished"]`
	);
	await expect(applicationEmbed).toBeVisible({ timeout: 90_000 });
	await applicationEmbed.focus();
	await page.keyboard.press('Enter');
	const fullscreenOverlay = page.getByTestId('embed-fullscreen-overlay');
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10_000 });
	await page.waitForTimeout(500); // animation
	return fullscreenOverlay;
}

test.describe('Habit Garden example application preview', () => {
	test('application preview iframe preserves same-origin semantics for module scripts', async () => {
		const componentPath = path.resolve(
			__dirname,
			'../../../packages/ui/src/components/embeds/code/ApplicationEmbedFullscreen.svelte'
		);
		const source = fs.readFileSync(componentPath, 'utf8');
		expect(source).toContain('sandbox="allow-scripts allow-forms allow-modals allow-popups allow-same-origin"');
	});

	test('unauthenticated Start preview opens signup without starting a preview', async ({ page }: { page: any }) => {
		test.setTimeout(90_000);

		attachConsoleListeners(page);
		attachNetworkListeners(page);

		const fullscreenOverlay = await openHabitGardenApplication(page);
		let previewStartRequested = false;
		page.on('request', (request: any) => {
			if (request.url().includes('/v1/applications/') && request.url().includes('/preview/start')) {
				previewStartRequested = true;
			}
		});

		await fullscreenOverlay.getByTestId('application-start-preview').click();
		await expect(page.getByTestId('login-wrapper')).toBeVisible({ timeout: 10_000 });
		await expect(page.locator('[data-testid="tab-signup"].active')).toBeVisible({ timeout: 5_000 });
		expect(previewStartRequested, 'unauthenticated users must not call preview/start').toBe(false);
	});

	test('authenticated user starts Habit Garden through gateway and receives usage entry', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(420_000);

		attachConsoleListeners(page);
		attachNetworkListeners(page);

		const { email, password, otpKey } = getTestAccount();
		skipWithoutCredentials(test, email, password, otpKey);

		const logCheckpoint = createSignupLogger('example-application-preview');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'example-application-preview'
		});

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		const fullscreenOverlay = await openHabitGardenApplication(page);

		const previewStartResponse = page.waitForResponse(
			(response: any) => response.url().includes('/v1/applications/') && response.url().includes('/preview/start'),
			{ timeout: 90_000 }
		);
		const previewStartedAt = Math.floor(Date.now() / 1000);
		await fullscreenOverlay.getByTestId('application-start-preview').click();
		const response = await previewStartResponse;
		expect(response.ok(), `preview start failed with ${response.status()}`).toBe(true);

		const payload = await response.json();
		expect(payload.session_id).toBeTruthy();
		expect(payload.preview_url).toMatch(/^https:\/\/preview-[a-f0-9]{12}\.dev\.openmatesusercontent\.org\/t\//);
		expect(payload.preview_url).not.toContain('e2b.dev');
		expect(payload.preview_url).not.toContain('e2b.app');

		const iframe = fullscreenOverlay.getByTestId('application-preview-iframe');
		await expect(iframe).toBeVisible({ timeout: 180_000 });
		await expect(iframe).toHaveAttribute('src', /^https:\/\/preview-[a-f0-9]{12}\.dev\.openmatesusercontent\.org\/t\//, { timeout: 10_000 });
		await expect(iframe).toHaveAttribute('sandbox', /allow-same-origin/, { timeout: 10_000 });
		const frame = await iframe.contentFrame();
		expect(frame, 'application preview iframe should have a frame context').toBeTruthy();
		await expect(frame.locator('body')).not.toContainText(/Blocked request|not allowed/i, { timeout: 30_000 });
		await expect(frame.locator('body')).toContainText(/Habit Garden|Plant Habit/i, { timeout: 180_000 });

		const testHabitName = `Read OpenMates docs ${Date.now()}`;
		await frame.locator('#new-habit-input').fill(testHabitName);
		await frame.locator('#add-habit-btn').click();
		await expect(frame.locator('body')).toContainText(testHabitName, { timeout: 10_000 });

		await expect(fullscreenOverlay.getByTestId('application-stop-preview')).toBeVisible({ timeout: 10_000 });
		await fullscreenOverlay.getByTestId('application-stop-preview').click();
		await expect(fullscreenOverlay.getByTestId('application-preview-status')).toContainText(/stopped|failed|timeout/i, { timeout: 60_000 });

		await expect.poll(async () => {
			const usageResponse = await page.context().request.get(
				`${API_BASE_URL}/v1/settings/usage/chat-entries?chat_id=${encodeURIComponent(HABIT_GARDEN_CHAT_ID)}&limit=20`
			);
			if (!usageResponse.ok()) return false;
			const usage = await usageResponse.json();
			return (usage.entries || []).some((entry: any) =>
				entry.app_id === 'code' &&
				entry.skill_id === 'application_preview' &&
				entry.chat_id === HABIT_GARDEN_CHAT_ID &&
				entry.created_at >= previewStartedAt - 5 &&
				entry.credits >= 5
			);
		}, {
			message: 'application preview usage entry should be visible after stopping preview',
			timeout: 60_000,
			interval: 5_000
		}).toBe(true);

		await closeFullscreen(page, fullscreenOverlay);
	});
});
