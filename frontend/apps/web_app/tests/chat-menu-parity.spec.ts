/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed
/**
 * Chat action menus: the open chat's header More menu offers the same chat
 * actions as the sidebar right-click menu, and actions the user picks are
 * ranked first in the right-click menu (usage stored in encrypted settings).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, withMockMarker, assertNoMissingTranslations } = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	waitForAssistantMessage,
	setChatSidebarOpen,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const CHAT_ACTIONS = [
	'add-to-project',
	'create-project',
	'move-to-project',
	'open-new-tab',
	'download',
	'copy',
	'hide',
	'pin',
	'mark-unread',
	'delete'
];

// contract-test: direct surface=gui.web assertions=chat-navigation.menu.parity-ranked
test('open chat More menu offers the right-click chat actions and ranks used ones first', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await loginToTestAccount(page);
	await startNewChat(page);
	await sendMessage(page, withMockMarker('What is the boiling point of water at sea level?', 'chat_flow_capital', 'instant'));
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30000 });
	await waitForAssistantMessage(page, { which: 'last', timeout: 60000 });

	// The open chat's More menu lists the same chat actions as the context menu.
	await page.getByTestId('chat-more-button').click();
	const moreMenu = page.getByTestId('chat-more-actions');
	await expect(moreMenu).toBeVisible({ timeout: 5000 });
	for (const id of CHAT_ACTIONS) {
		await expect(moreMenu.getByTestId(`chat-header-${id}`)).toHaveCount(1);
	}

	// Delete needs a second tap: the first tap keeps the menu open.
	await moreMenu.getByTestId('chat-header-delete').click();
	await expect(moreMenu).toBeVisible();
	await expect(moreMenu.getByTestId('chat-header-delete')).toHaveAttribute('aria-label', /confirm/i);

	// Download from the More menu records usage for ranking.
	const downloadPromise = page.waitForEvent('download', { timeout: 30000 });
	await moreMenu.getByTestId('chat-header-download').click();
	const download = await downloadPromise;
	expect(download.suggestedFilename()).toBeTruthy();

	// The right-click menu now lists Download first, with close button and scroll arrow.
	await setChatSidebarOpen(page, true);
	const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
	await expect(activeChatItem).toBeVisible({ timeout: 10000 });
	await activeChatItem.click({ button: 'right' });
	const menu = page.getByTestId('context-menu');
	await expect(menu).toBeVisible({ timeout: 5000 });
	await expect(menu.getByTestId('chat-context-scroll').locator('[data-usage-id]').first()).toHaveAttribute(
		'data-testid',
		'chat-context-download'
	);
	await expect(menu.getByTestId('chat-context-scroll-more')).toBeVisible();
	await menu.getByTestId('chat-context-close').click();
	await expect(menu).toHaveCount(0);

	await assertNoMissingTranslations(page);
	await deleteActiveChat(page);
});
