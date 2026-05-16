/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

const PROMPT =
	'Create a polite email to my landlord about the broken heater at 42 Linden Street. Ask for a repair update and a callback at +49 171 000 9111. Send it from max@example.com to sophia@example.com.';

const CAPTURE_PATH =
	process.env.PRIVACY_VIDEO_CAPTURE_PATH ||
	'/home/superdev/projects/openmates-marketing/videos/remotion/public/captures/privacy-demo-input.webm';

test('record privacy video demo flow', async ({ browser }: { browser: any }) => {
	test.setTimeout(120000);

	const context = await browser.newContext({
		viewport: { width: 1080, height: 1080 },
		recordVideo: {
			dir: path.dirname(CAPTURE_PATH),
			size: { width: 1080, height: 1080 }
		}
	});

	await context.addInitScript(() => {
		window.localStorage.setItem('openmates.demoMode', 'privacy-video');
	});

	const page = await context.newPage();
	await page.goto('/?lang=en');
	await page.waitForLoadState('load');

	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 30000 });
	await page.waitForTimeout(700);

	await messageEditor.click();
	await page.keyboard.type(PROMPT, { delay: 10 });
	await page.waitForTimeout(1700);

	await expect(page.getByTestId('pii-warning-banner')).toBeVisible({ timeout: 10000 });
	await expect(page.locator('[data-testid="pii-highlight"]').first()).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(900);

	await page.keyboard.press('Enter');

	const assistantMessage = page.getByTestId('message-assistant').last();
	await expect(assistantMessage).toBeVisible({ timeout: 10000 });
	await expect(assistantMessage).toContainText('[PHONE_1_111]', { timeout: 10000 });
	await page.waitForTimeout(900);

	const piiToggle = page.getByTestId('chat-pii-toggle');
	await expect(piiToggle).toBeVisible({ timeout: 10000 });
	await expect(piiToggle).toHaveAttribute('data-pii-revealed', 'false');

	await piiToggle.click();
	await expect(piiToggle).toHaveAttribute('data-pii-revealed', 'true');
	await page.waitForTimeout(1300);

	await piiToggle.click();
	await expect(piiToggle).toHaveAttribute('data-pii-revealed', 'false');
	await expect(assistantMessage).toContainText('[PHONE_1_111]', { timeout: 10000 });
	await page.waitForTimeout(1300);

	const video = page.video();
	await context.close();

	if (!video) {
		throw new Error('Playwright did not create a video recording');
	}

	const videoPath = await video.path();
	await fs.mkdir(path.dirname(CAPTURE_PATH), { recursive: true });
	await fs.rm(CAPTURE_PATH, { force: true });
	await fs.rename(videoPath, CAPTURE_PATH);
});
