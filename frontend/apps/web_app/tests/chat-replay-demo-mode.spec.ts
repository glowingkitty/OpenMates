/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Chat replay demo mode test.
 *
 * Verifies the UI-only replay command works on a hardcoded example chat and
 * automatically switches the app into generic demo mode for clean recordings.
 * This is intentionally unauthenticated: video capture uses existing/example
 * chats and must not send messages to the backend.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

test.describe('Chat replay demo mode', () => {
	test('replays an example chat and hides example-chat chrome in demo mode', async ({ page }: { page: any }) => {
		test.setTimeout(90000);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await page.waitForFunction(
			() => window.location.hash.includes('demo-for-everyone'),
			null,
			{ timeout: 15000 }
		);

		const exampleChatsGroup = page.getByTestId('example-chats-group');
		await exampleChatsGroup.scrollIntoViewIfNeeded({ timeout: 15000 });
		await expect(exampleChatsGroup).toBeVisible({ timeout: 10000 });

		const artemisCard = exampleChatsGroup.getByTestId('chat-embed-card').filter({
			hasText: /artemis/i
		}).first();
		await expect(artemisCard).toBeVisible({ timeout: 10000 });
		await artemisCard.click();

		await page.waitForFunction(
			() => window.location.hash.includes('example-artemis'),
			null,
			{ timeout: 10000 }
		);

		const activeChatContainer = page.getByTestId('active-chat-container');
		await expect(activeChatContainer).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('mate-message-content').first()).toBeVisible({ timeout: 10000 });

		const exampleBadge = page.getByTestId('example-chat-badge').first();
		await expect(exampleBadge).toBeVisible({ timeout: 10000 });

		await page.waitForFunction(
			() => typeof (window as any).chat_replay?.start === 'function',
			null,
			{ timeout: 10000 }
		);

		await page.evaluate(() => {
			(window as any).__chatReplayDone = (window as any).chat_replay.start({
				speed: 1.5,
				initialDelayMs: 1200,
				paragraphDelayMs: 900
			});
		});

		await page.waitForFunction(
			() => (window as any).chat_replay.status().running === true,
			null,
			{ timeout: 5000 }
		);

		await expect(page.getByTestId('profile-container')).toBeVisible({ timeout: 5000 });
		await expect(exampleBadge).toHaveCount(0, { timeout: 5000 });

		const demoModeStored = await page.evaluate(() => window.localStorage.getItem('demo_mode_enabled'));
		expect(demoModeStored).toBe('true');

		await expect(page.getByTestId('user-message-content').last()).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('mate-message-content').last()).toBeVisible({ timeout: 10000 });

		await page.evaluate(() => (window as any).__chatReplayDone);
		expect(await page.evaluate(() => (window as any).chat_replay.status().running)).toBe(false);
		await expect(page.getByTestId('example-chat-badge')).toHaveCount(0, { timeout: 5000 });
	});
});
