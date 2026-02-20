/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * Audio recording flow E2E tests.
 *
 * Tests the press-and-hold mic button interaction as an unauthenticated user
 * (no login needed — the demo chat has a message field).
 *
 * Chromium is launched with --use-fake-device-for-media-stream so that
 * getUserMedia() resolves with a fake audio stream (no real microphone needed).
 * Microphone permission is auto-granted via browser context settings.
 *
 * Test matrix:
 *   1. Single tap  → no recording overlay; inline "Press & hold" label highlights
 *   2. Press & hold (>500ms) → recording overlay appears with correct UI elements
 *   3. Press & hold then release → recording completes, audio embed inserted
 *   4. Press & hold then Escape → recording cancelled, no embed inserted
 */

import { test, expect } from '@playwright/test';

// Configure the browser to use a fake audio device and grant mic permission
test.use({
	launchOptions: {
		args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']
	},
	permissions: ['microphone']
});

const consoleLogs: string[] = [];

test.beforeEach(async ({ page }) => {
	consoleLogs.length = 0;

	// Collect console logs for debugging on failure
	page.on('console', (msg) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
});

test.afterEach(async (_fixtures, testInfo) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

/**
 * Helper: navigate to the app, wait for the page to be loaded, and focus the
 * message field editor so action buttons appear. Returns the message field locator.
 */
async function setupAndFocusMessageField(page: any) {
	await page.goto('/');

	// Wait for the page to fully load — demo chats need time to initialize
	await page.waitForTimeout(3000);

	// The message field should be visible for unauthenticated users (demo chat)
	const messageField = page.locator('.message-field');
	await expect(messageField).toBeVisible({ timeout: 20000 });

	// Click the editor content area to focus it — this sets isMessageFieldFocused=true
	// and makes ActionButtons visible via shouldShowActionButtons.
	// Use `.editor-content.prose` to target the main message input field specifically,
	// since demo chat messages also have `.editor-content` elements on the page.
	const editorContent = page.locator('.editor-content.prose');
	if (await editorContent.isVisible()) {
		await editorContent.click();
	} else {
		// Fallback: click the message field itself
		await messageField.click();
	}

	// Give time for focus state to propagate and action buttons to render
	await page.waitForTimeout(1000);

	return messageField;
}

/**
 * Helper: find the mic/record button. Uses aria-label as a stable selector.
 * Falls back to class selector if aria-label not found.
 */
function getMicButton(page: any) {
	return page.locator('.clickable-icon.icon_recordaudio');
}

/**
 * Helper: wait for mic button to be visible, with extended timeout and debug.
 */
async function waitForMicButton(page: any) {
	const micButton = getMicButton(page);

	// Check if action buttons wrapper exists at all
	const actionButtonsWrapper = page.locator('.action-buttons');
	const actionButtonsVisible = await actionButtonsWrapper.isVisible().catch(() => false);
	if (!actionButtonsVisible) {
		// Take screenshot for debugging
		await page.screenshot({ path: '/tmp/pw-results/debug-no-action-buttons.png' });
		console.log('[DEBUG] .action-buttons not visible. Dumping relevant DOM...');
		const html = await page
			.locator('.message-field')
			.innerHTML()
			.catch(() => 'NOT FOUND');
		console.log('[DEBUG] .message-field innerHTML (first 500 chars):', html.substring(0, 500));
	}

	await expect(micButton).toBeVisible({ timeout: 10000 });
	return micButton;
}

// ─────────────────────────────────────────────────────────────────────────────
// Test 1: Single tap shows "Press & hold" hint (no recording overlay)
// ─────────────────────────────────────────────────────────────────────────────
test('single tap on mic button does not start recording', async ({ page }) => {
	test.setTimeout(60000);

	await setupAndFocusMessageField(page);
	const micButton = await waitForMicButton(page);

	// Quick click (mousedown + mouseup within ~50ms) = single tap
	await micButton.click({ delay: 50 });

	// Recording overlay should NOT appear
	const overlay = page.locator('.record-overlay');
	await expect(overlay).not.toBeVisible({ timeout: 1000 });

	// The inline "Press & hold to record" label should be visible
	// (either already shown or force-shown via highlight)
	const pressHoldLabel = page.locator('.press-hold-label');
	await expect(pressHoldLabel).toBeVisible({ timeout: 2000 });

	console.log('[TEST] Single tap: no overlay, press-hold label visible');
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 2: Press & hold shows recording overlay with expected UI elements
// ─────────────────────────────────────────────────────────────────────────────
test('press and hold mic button shows recording overlay', async ({ page }) => {
	test.setTimeout(60000);

	await setupAndFocusMessageField(page);
	const micButton = await waitForMicButton(page);

	// Press and hold: mousedown, wait for overlay, then verify before releasing
	await micButton.dispatchEvent('mousedown', { button: 0 });

	// Wait for the recording overlay to appear (200ms hold threshold + mount time)
	const overlay = page.locator('.record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });

	// Verify overlay contains expected UI elements
	// 1. "Release to finish" heading
	const releaseText = overlay.locator('.release-text');
	await expect(releaseText).toBeVisible();

	// 2. Timer pill (showing 00:00 or 00:01)
	const timerPill = overlay.locator('.timer-pill');
	await expect(timerPill).toBeVisible();

	// 3. Cancel hint ("Slide left to cancel")
	const cancelHint = overlay.locator('.cancel-hint');
	await expect(cancelHint).toBeVisible();

	// 4. Green mic circle
	const micCircle = overlay.locator('.mic-button');
	await expect(micCircle).toBeVisible();

	console.log('[TEST] Press & hold: overlay visible with all UI elements');

	// Release to clean up
	await page.dispatchEvent('body', 'mouseup');
	await page.waitForTimeout(1000);
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 3: Press & hold then release → recording completes, audio embed inserted
// ─────────────────────────────────────────────────────────────────────────────
test('press hold and release creates audio embed', async ({ page }) => {
	test.setTimeout(60000);

	await setupAndFocusMessageField(page);
	const micButton = await waitForMicButton(page);

	// Count existing recording embeds before
	const embedCountBefore = await page.locator('.recording-preview').count();

	// Press and hold
	await micButton.dispatchEvent('mousedown', { button: 0 });

	// Wait for overlay to appear and recorder to start
	const overlay = page.locator('.record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });

	// Hold for a bit so some audio data is captured by the fake device
	await page.waitForTimeout(1500);

	// Release via document-level mouseup (simulating user releasing the button)
	await page.dispatchEvent('body', 'mouseup');

	// Overlay should disappear after release
	await expect(overlay).not.toBeVisible({ timeout: 5000 });

	// A recording embed should now be inserted in the editor.
	// Give it a moment for the embed insertion to complete.
	await page.waitForTimeout(2000);

	const embedCountAfter = await page.locator('.recording-preview').count();
	expect(embedCountAfter).toBeGreaterThan(embedCountBefore);

	console.log('[TEST] Press hold release: audio embed inserted');
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 4: Press & hold then Escape → recording cancelled, no embed
// ─────────────────────────────────────────────────────────────────────────────
test('press hold then escape cancels recording', async ({ page }) => {
	test.setTimeout(60000);

	await setupAndFocusMessageField(page);
	const micButton = await waitForMicButton(page);

	// Count existing recording embeds before
	const embedCountBefore = await page.locator('.recording-preview').count();

	// Press and hold
	await micButton.dispatchEvent('mousedown', { button: 0 });

	// Wait for overlay to appear
	const overlay = page.locator('.record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });

	// Hold briefly, then press Escape to cancel
	await page.waitForTimeout(500);
	await page.keyboard.press('Escape');

	// Overlay should disappear
	await expect(overlay).not.toBeVisible({ timeout: 5000 });

	// No new recording embed should have been inserted
	await page.waitForTimeout(1000);
	const embedCountAfter = await page.locator('.recording-preview').count();
	expect(embedCountAfter).toBe(embedCountBefore);

	console.log('[TEST] Press hold escape: recording cancelled, no embed');
});
