/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');

const PROMPT =
	'Draft an email to my landlord at schmidt.verwaltung@proton.com about the broken heater at Lindenstrasse 42, 10969 Berlin. Ask for a repair update and a callback at +49 171 000 9111. Sign it as clara.meyer@posteo.de.';

const APP_URL = 'https://app.dev.openmates.org/?lang=en';

const CAPTURE_PATH =
	process.env.PRIVACY_VIDEO_CAPTURE_PATH ||
	'/home/superdev/projects/openmates-marketing/videos/remotion/public/captures/privacy-demo-input.webm';

test('record privacy video demo flow', async ({ browser }: { browser: any }) => {
	test.setTimeout(120000);

	const context = await browser.newContext({
		colorScheme: 'dark',
		deviceScaleFactor: 2,
		viewport: { width: 1440, height: 900 },
		recordVideo: {
			dir: path.dirname(CAPTURE_PATH),
			size: { width: 2880, height: 1800 }
		}
	});
	const recordingStartedAt = Date.now();

	await context.addInitScript(() => {
		window.localStorage.setItem('openmates.demoMode', 'privacy-video');
		window.localStorage.setItem('theme_mode', 'dark');
		window.localStorage.setItem('theme', 'dark');
		document.documentElement.setAttribute('data-theme', 'dark');

		const installDemoCursor = () => {
			if (document.getElementById('privacy-video-cursor')) return;
			const cursor = document.createElement('div');
			cursor.id = 'privacy-video-cursor';
			cursor.style.cssText = [
				'position: fixed',
				'left: 720px',
				'top: 450px',
				'width: 30px',
				'height: 38px',
				'background: #ffffff',
				'clip-path: polygon(0 0, 0 32px, 9px 24px, 15px 38px, 21px 35px, 15px 22px, 30px 22px)',
				'filter: drop-shadow(0 6px 10px rgba(0,0,0,0.42)) drop-shadow(0 0 0 #ff553b)',
				'pointer-events: none',
				'z-index: 2147483647',
				'transform: translate(-4px, -4px) scale(1)',
				'transition: transform 120ms ease'
			].join(';');
			document.documentElement.appendChild(cursor);

			window.addEventListener(
				'mousemove',
				(event) => {
					cursor.style.left = `${event.clientX}px`;
					cursor.style.top = `${event.clientY}px`;
				},
				{ passive: true }
			);
			window.addEventListener('mousedown', () => {
				cursor.style.transform = 'translate(-4px, -4px) scale(0.82)';
			});
			window.addEventListener('mouseup', () => {
				cursor.style.transform = 'translate(-4px, -4px) scale(1)';
			});
		};

		if (document.readyState === 'loading') {
			document.addEventListener('DOMContentLoaded', installDemoCursor, { once: true });
		} else {
			installDemoCursor();
		}

		const forceDemoSendButton = () => {
			document.querySelectorAll('button[data-action="buy-credits"]').forEach((button) => {
				button.setAttribute('data-action', 'send-message');
				button.setAttribute('aria-label', 'Send');
				button.textContent = 'Send';
			});
		};
		new MutationObserver(forceDemoSendButton).observe(document.documentElement, { childList: true, subtree: true });
		forceDemoSendButton();
	});

	const page = await context.newPage();
	await page.goto(APP_URL);
	await page.waitForLoadState('load');
	await page.waitForLoadState('networkidle');
	await page.evaluate(async () => {
		await document.fonts.ready;
	});

	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 30000 });
	await expect(page.getByTestId('header-login-signup-btn')).toBeHidden({ timeout: 10000 });
	await expect(page.getByText('Daily Inspiration')).toBeVisible({ timeout: 10000 });
	await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
	await page.addStyleTag({
			content: '.notification-container, .mic-permission-hint, .offline-banner { display: none !important; }'
	});
	await page.waitForTimeout(500);
	const captureStartedAt = Date.now();

	const editorBox = await messageEditor.boundingBox();
	if (!editorBox) throw new Error('Message editor bounding box unavailable');
	await page.mouse.move(editorBox.x + editorBox.width / 2, editorBox.y + editorBox.height / 2, { steps: 18 });
	await page.mouse.click(editorBox.x + editorBox.width / 2, editorBox.y + editorBox.height / 2);
	await page.waitForTimeout(2000);
	await page.keyboard.type(PROMPT, { delay: 10 });
	await page.waitForTimeout(1700);

	await expect(page.getByTestId('pii-warning-banner')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('banner-description')).toContainText('address', { timeout: 10000 });
	await expect(page.locator('button[data-action="send-message"]')).toContainText('Send', { timeout: 10000 });
	await expect(page.locator('button[data-action="buy-credits"]')).toHaveCount(0);
	await expect(page.locator('[data-testid="pii-highlight"]').first()).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(900);

	await page.keyboard.press('Enter');

	const assistantMessage = page.getByTestId('message-assistant').last();
	await expect(assistantMessage).toBeVisible({ timeout: 10000 });
	await expect(assistantMessage).toContainText('[PHONE_1_111]', { timeout: 10000 });
	await expect(page.getByText('Landlord repair email')).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(900);

	const piiToggle = page.getByTestId('chat-pii-toggle');
	await expect(piiToggle).toBeVisible({ timeout: 10000 });
	await expect(piiToggle).toHaveAttribute('data-pii-revealed', 'false');

	const toggleBox = await piiToggle.boundingBox();
	if (!toggleBox) throw new Error('PII toggle bounding box unavailable');
	await page.mouse.move(toggleBox.x + toggleBox.width / 2, toggleBox.y + toggleBox.height / 2, { steps: 24 });
	await page.mouse.click(toggleBox.x + toggleBox.width / 2, toggleBox.y + toggleBox.height / 2);
	await expect(piiToggle).toHaveAttribute('data-pii-revealed', 'true');
	await page.waitForTimeout(1300);

	await page.mouse.click(toggleBox.x + toggleBox.width / 2, toggleBox.y + toggleBox.height / 2);
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
	const trimSeconds = Math.max(0, (captureStartedAt - recordingStartedAt) / 1000);
	execFileSync(
		'ffmpeg',
		[
			'-y',
			'-ss',
			trimSeconds.toFixed(3),
			'-i',
			videoPath,
			'-c:v',
			'libvpx-vp9',
			'-b:v',
			'0',
			'-crf',
			'30',
			'-an',
			CAPTURE_PATH
		],
		{ stdio: 'inherit' }
	);
});
