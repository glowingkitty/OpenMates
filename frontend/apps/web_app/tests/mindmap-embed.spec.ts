/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Mind Maps direct embed coverage.
 * Exercises the deterministic native .ommindmap import path and fullscreen
 * controls against deployed dev through the standard Playwright workflow.
 */

const path = require('path');
const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const MINDMAP_FIXTURE = path.join(__dirname, 'fixtures', 'launch-plan.ommindmap');
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function attachFile(page: any, filePath: string, logCheckpoint: (msg: string) => void): Promise<void> {
	const fileInput = page.locator('input[type="file"][multiple]');
	await expect(fileInput).toBeAttached({ timeout: 10000 });
	logCheckpoint(`Attaching file: ${filePath}`);
	await fileInput.setInputFiles(filePath);
}

async function stopActiveResponseIfNeeded(page: any): Promise<void> {
	const stopButton = page.getByTestId('stop-processing-button');
	if (await stopButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await stopButton.click();
		await expect(stopButton).not.toBeVisible({ timeout: 15000 });
	}
}

test('native mindmap upload renders preview and fullscreen controls', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('MINDMAP_EMBED_UPLOAD');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'mindmap-embed' });
	await archiveExistingScreenshots(log);

	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	await startNewChat(page, log);
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 10000 });
	await editor.click();
	await page.keyboard.type('Please keep this launch mind map attached.');

	await attachFile(page, MINDMAP_FIXTURE, log);
	const editorMindMap = editor.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="mindmaps-mindmap"]');
	await expect(editorMindMap).toBeVisible({ timeout: 20000 });
	await expect(editor).not.toContainText('```json');
	await screenshot(page, 'mindmap-editor-preview');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });

	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toBeVisible({ timeout: 20000 });
	const chatMindMap = userMessage.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="mindmaps-mindmap"]');
	await expect(chatMindMap).toBeVisible({ timeout: 20000 });

	await chatMindMap.scrollIntoViewIfNeeded();
	const chatMindMapPreview = chatMindMap.getByTestId('embed-preview');
	await expect(chatMindMapPreview).toBeVisible({ timeout: 10000 });
	await chatMindMapPreview.evaluate((element: HTMLElement) => element.click());
	const fullscreenOverlay = page.getByTestId('embed-fullscreen-overlay');
	await expect(fullscreenOverlay).toBeVisible({ timeout: 15000 });
	await expect(fullscreenOverlay.getByTestId('mindmap-fullscreen-canvas')).toBeVisible({ timeout: 10000 });
	await expect(fullscreenOverlay.getByTestId('embed-header-title')).toHaveText('Launch Plan', { timeout: 10000 });

	const stage = fullscreenOverlay.getByTestId('mindmap-fullscreen-stage');
	const beforeZoom = await stage.getAttribute('style');
	await fullscreenOverlay.getByTestId('mindmap-zoom-in').click();
	await expect(stage).not.toHaveAttribute('style', beforeZoom || '', { timeout: 5000 });
	await fullscreenOverlay.getByTestId('mindmap-zoom-reset').click();

	const nodesBeforeCollapse = await fullscreenOverlay.getByTestId('mindmap-node').count();
	await fullscreenOverlay.getByTestId('mindmap-collapse-toggle').first().click();
	await expect.poll(async () => fullscreenOverlay.getByTestId('mindmap-node').count()).toBeLessThan(nodesBeforeCollapse);

	const downloadPromise = page.waitForEvent('download');
	await fullscreenOverlay.getByRole('button', { name: /download/i }).click();
	const download = await downloadPromise;
	expect(download.suggestedFilename()).toMatch(/launch-plan.*\.ommindmap$/);

	await fullscreenOverlay.getByTestId('embed-minimize').click();
	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 10000 });

	await stopActiveResponseIfNeeded(page);
	await deleteActiveChat(page, log, screenshot, 'cleanup');
});
