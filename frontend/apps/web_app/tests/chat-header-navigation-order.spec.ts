/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Regression guard for ChatHeader navigation order.
 *
 * The header controls navigate through the newest-first chat order rendered by
 * Chats.svelte. The right-side control and a right-to-left swipe move to the
 * previous recent chat (older item); the left-side control and reverse swipe
 * move back toward newer items.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { fillMessageEditor, focusMessageEditor, loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');

const INTRO_CHAT_TITLES = new Set(['Who develops OpenMates?']);

const SECURITY_REMINDER_TITLE = 'Security Reminder';

async function dismissSecurityReminder(page: any): Promise<void> {
	const reminder = page.getByTestId('notification').filter({ hasText: SECURITY_REMINDER_TITLE });
	if (!(await reminder.isVisible({ timeout: 2000 }).catch(() => false))) return;

	await expect(reminder.getByTestId('notification-progress')).toHaveAttribute('data-duration-ms', '7000');
	await reminder.getByTestId('notification-dismiss').click({ timeout: 5000 });
	await expect(reminder).not.toBeVisible({ timeout: 10000 });
}

async function ensureSidebarOpen(page: any): Promise<void> {
	const activityHistory = page.getByTestId('activity-history-wrapper');
	if (await activityHistory.isVisible().catch(() => false)) return;

	await page.getByTestId('sidebar-toggle').click();
	await expect(activityHistory).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(1000);
}

async function expectHeaderTitle(page: any, expectedTitle: string): Promise<void> {
	const headerTitle = page.getByTestId('chat-header-title');
	await expect(headerTitle).toBeVisible({ timeout: 12000 });
	await expect(headerTitle).toHaveText(expectedTitle, { timeout: 12000 });
	expect(await page.evaluate(() => window.location.hash.includes('chat-id='))).toBe(true);
}

async function expectFirstUserMessageId(page: any): Promise<string> {
	const firstUserMessage = page.getByTestId('message-user').first();
	await expect(firstUserMessage).toBeVisible({ timeout: 12000 });
	const messageId = await firstUserMessage.getAttribute('data-message-id');
	expect(messageId, 'Expected first user message to expose a message id').toBeTruthy();
	return messageId as string;
}

async function expectFirstUserMessageChanged(page: any, previousMessageId: string): Promise<string> {
	await page.waitForFunction(
		(before: string) => {
			const firstUserMessage = document.querySelector('[data-testid="message-user"]');
			return firstUserMessage?.getAttribute('data-message-id') !== before;
		},
		previousMessageId,
		{ timeout: 12000 }
	);
	return expectFirstUserMessageId(page);
}

async function swipeHeader(page: any, startX: number, endX: number): Promise<void> {
	const header = page.getByTestId('chat-header-banner');
	await expect(header).toBeVisible({ timeout: 10000 });
	await header.dispatchEvent('touchstart', {
		touches: [{ identifier: 1, clientX: startX, clientY: 80 }]
	});
	await header.dispatchEvent('touchmove', {
		touches: [{ identifier: 1, clientX: endX, clientY: 84 }]
	});
	await header.dispatchEvent('touchend', { touches: [] });
}

test.describe('ChatHeader follows Chats.svelte order', () => {
	// contract-test: direct surface=gui.web assertions=chat-navigation.draft-only.addressable,chat-navigation.order.sidebar-header-match,chat-navigation.empty-new-chat.excluded,drafts.draft-only.lifecycle,drafts.navigation.includes-draft-only,drafts.established-chat.presentation-unchanged,notifications.web.timed-dismissal
	test('navigates from a regular chat to the newest draft-only chat with the sidebar closed', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(120000);
		await page.setViewportSize({ width: 1280, height: 900 });
		await loginToTestAccount(page, () => undefined, async () => undefined, { waitForEditor: true });
		await dismissSecurityReminder(page);
		// Login can restore the account's last opened chat. Start from a fresh
		// composer so the typed text creates a draft-only chat shell.
		await startNewChat(page);
		await dismissSecurityReminder(page);

		const draftText = `Header navigation draft ${Date.now().toString(36).replace(/[0-9]/g, 'a')}`;
		const messageEditor = page.getByTestId('message-editor');
		await fillMessageEditor(page, messageEditor, draftText);
		await expect(page.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('daily-inspiration-area')).toHaveCount(0);
		const draftChatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
		expect(draftChatId).toBeTruthy();

		try {
			await startNewChat(page);
			await dismissSecurityReminder(page);
			const resumeDraftCard = page.getByTestId('resume-chat-draft-card').filter({ hasText: draftText });
			await expect(resumeDraftCard).toBeVisible({ timeout: 15000 });
			expect(await resumeDraftCard.getAttribute('data-chat-id')).toBe(draftChatId);
			await resumeDraftCard.dispatchEvent('click');
			await expect(page.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 15000 });
			expect(page.url()).toContain(`chat-id=${draftChatId}`);

			await page.setViewportSize({ width: 390, height: 844 });
			await messageEditor.click();
			await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
			await expect(messageEditor).toContainText(draftText, { timeout: 15000 });
			await expect(page.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 15000 });
			expect(page.url()).toContain(`chat-id=${draftChatId}`);

			await page.setViewportSize({ width: 1280, height: 900 });
			await ensureSidebarOpen(page);
			const draftSidebarItem = page
				.getByTestId('chat-item-wrapper')
				.filter({ hasText: draftText });
			await expect(draftSidebarItem).toBeVisible({ timeout: 15000 });
			await page
				.getByTestId('activity-history-wrapper')
				.getByRole('button', { name: /close/i })
				.click();
			await expect(page.getByTestId('activity-history-wrapper')).not.toBeVisible({ timeout: 10000 });

			await ensureSidebarOpen(page);
			const chatItems = page.getByTestId('chat-item-wrapper');
			const draftRowIndex = await chatItems.evaluateAll((rows: Element[], id: string) =>
				rows.findIndex((row) => row.getAttribute('data-chat-id') === id), draftChatId);
			expect(draftRowIndex, 'Expected the draft chat to be present in sidebar order').toBeGreaterThanOrEqual(0);
			const regularRowIndex = await chatItems.evaluateAll((rows: Element[], id: string) => {
				const index = rows.findIndex((row) => row.getAttribute('data-chat-id') === id);
				if (index < 0) return -1;
				for (let candidate = index + 1; candidate < rows.length; candidate += 1) {
					if (rows[candidate].querySelector('[data-testid="chat-with-profile"]')) return candidate;
				}
				return -1;
			}, draftChatId);
			expect(regularRowIndex, 'Expected a regular chat after the draft in sidebar order').toBeGreaterThan(draftRowIndex);
			const regularChatAfterDraft = chatItems.nth(regularRowIndex);
			await expect(regularChatAfterDraft).toBeVisible({ timeout: 15000 });
			await expect(regularChatAfterDraft.getByTestId('chat-with-profile')).toBeVisible({ timeout: 15000 });
			await regularChatAfterDraft.click();
			await expect(page.getByTestId('draft-chat-badge')).toHaveCount(0);

			if (await page.getByTestId('activity-history-wrapper').isVisible().catch(() => false)) {
				await page
					.getByTestId('activity-history-wrapper')
					.getByRole('button', { name: /close/i })
					.click();
			}
			await expect(page.getByTestId('activity-history-wrapper')).not.toBeVisible({ timeout: 10000 });
			for (let step = 0; step < regularRowIndex - draftRowIndex; step += 1) {
				const previousUrl = page.url();
				await page.getByTestId('chat-header-next').click();
				await page.waitForFunction((url: string) => window.location.href !== url, previousUrl, { timeout: 12000 });
				if (page.url().includes(`chat-id=${draftChatId}`)) break;
			}

			await expect(page.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 15000 });
			expect(page.url()).toContain(`chat-id=${draftChatId}`);
			await expect(page.getByTestId('chat-header-title')).toContainText(draftText);
		} finally {
			if (draftChatId && page.url().includes(draftChatId)) {
				await expect(messageEditor).toContainText(draftText, { timeout: 15000 });
				await focusMessageEditor(messageEditor);
				await page.keyboard.press('Control+A');
				await page.keyboard.press('Backspace');
				await expect.poll(async () => (
					await messageEditor.evaluate((editor: HTMLElement) => editor.innerText ?? '')
				).replace(/\s+/g, ' ').trim(), { timeout: 5000 }).toBe('');
				const dismissButton = page.getByTestId('input-dismiss-button');
				await expect(dismissButton).toBeVisible({ timeout: 5000 });
				await dismissButton.click();
				await expect(page.getByTestId('draft-chat-badge')).toHaveCount(0, { timeout: 15000 });
			}
		}
	});

	// contract-test: direct surface=gui.web assertions=chat-navigation.order.sidebar-header-match
	test('right control and right-to-left swipe navigate to previous sidebar chat', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);
		await page.setViewportSize({ width: 1280, height: 900 });
		await loginToTestAccount(page, () => undefined, async () => undefined, { waitForEditor: true });

		await ensureSidebarOpen(page);

		const chatItems = page.getByTestId('chat-item-wrapper');
		await expect(chatItems.nth(2)).toBeVisible({ timeout: 15000 });
		const orderedTitles = await chatItems
			.locator('[data-testid="chat-title"]')
			.evaluateAll((nodes: Element[]) =>
				nodes.map((node) => (node.textContent || '').trim()).filter(Boolean)
			);

		const selectedIndex = orderedTitles.findIndex((title: string, index: number, titles: string[]) => {
			if (index === 0 || index === titles.length - 1) return false;
			return [titles[index - 1], title, titles[index + 1]].every(
				(candidate) => !INTRO_CHAT_TITLES.has(candidate)
			);
		});

		expect(selectedIndex).toBeGreaterThan(0);
		const newerTitle = orderedTitles[selectedIndex - 1];
		const selectedTitle = orderedTitles[selectedIndex];
		const olderTitle = orderedTitles[selectedIndex + 1];

		await chatItems.nth(selectedIndex).click();
		await expectHeaderTitle(page, selectedTitle);
		const selectedFirstMessageId = await expectFirstUserMessageId(page);

		await page.getByTestId('chat-header-previous').click();
		await expectHeaderTitle(page, olderTitle);
		const olderFirstMessageId = await expectFirstUserMessageChanged(page, selectedFirstMessageId);

		await page.getByTestId('chat-header-next').click();
		await expectHeaderTitle(page, selectedTitle);
		await page.waitForFunction(
			(expected: string) => {
				const firstUserMessage = document.querySelector('[data-testid="message-user"]');
				return firstUserMessage?.getAttribute('data-message-id') === expected;
			},
			selectedFirstMessageId,
			{ timeout: 12000 }
		);

		await swipeHeader(page, 360, 240);
		await expectHeaderTitle(page, olderTitle);
		await page.waitForFunction(
			(expected: string) => {
				const firstUserMessage = document.querySelector('[data-testid="message-user"]');
				return firstUserMessage?.getAttribute('data-message-id') === expected;
			},
			olderFirstMessageId,
			{ timeout: 12000 }
		);

		await swipeHeader(page, 240, 360);
		await expectHeaderTitle(page, selectedTitle);
		await page.waitForFunction(
			(expected: string) => {
				const firstUserMessage = document.querySelector('[data-testid="message-user"]');
				return firstUserMessage?.getAttribute('data-message-id') === expected;
			},
			selectedFirstMessageId,
			{ timeout: 12000 }
		);

		await page.getByTestId('chat-header-next').click();
		await expectHeaderTitle(page, newerTitle);
		await expectFirstUserMessageChanged(page, selectedFirstMessageId);
	});
});
