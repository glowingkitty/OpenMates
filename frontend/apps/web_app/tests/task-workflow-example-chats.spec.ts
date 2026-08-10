/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Public example-chat coverage for real CLI-created Tasks and Workflows outputs.
 *
 * Product contract: docs/specs/tasks-workflows-app-skill-embeds/spec.yml
 * Source chats must be real shared CLI chats, not hand-authored fixtures.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { openFullscreen, verifySearchGrid, closeFullscreen } = require('./helpers/embed-test-helpers');

async function openPublicExample(page: any, slug: string, chatId: string) {
	const response = await page.goto(`/example/${slug}`, { waitUntil: 'domcontentloaded' });
	expect(response?.status()).toBe(200);
	await expect(page).toHaveURL(new RegExp(`#chat-id=${chatId}$`), { timeout: 15_000 });
	await expect(page.getByTestId('message-assistant').first()).toBeVisible({ timeout: 30_000 });
}

test.describe('Task and workflow public example chats', () => {
	test('renders the real CLI-created Tasks example with parent and child embeds', async ({ page }) => {
		test.setTimeout(120_000);

		await openPublicExample(page, 'example-chat-task-planning-checklist', 'example-example-chat-task-planning');
		await expect(page.locator('body')).not.toContainText('task-event-task-update-job');
		await expect(page.locator('body')).not.toContainText('pending_client_persistence');

		const parent = page.locator('[data-testid="embed-preview"][data-app-id="tasks"][data-skill-id="create"][data-status="finished"]').first();
		await expect(parent).toBeVisible({ timeout: 30_000 });
		await expect(parent).toContainText('3 tasks created');

		const fullscreen = await openFullscreen(page, parent);
		const taskCards = await verifySearchGrid(fullscreen, 3, 30_000);
		await expect(taskCards.first().getByTestId('task-embed-card')).toBeVisible({ timeout: 15_000 });
		await expect(taskCards.first()).toContainText('Review transcript for private data');

		await taskCards.first().click();
		await expect(page.getByTestId('task-embed-fullscreen')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('task-embed-title')).toContainText('Review transcript for private data');
	});

	test('renders the real CLI-created Workflows example from the public SEO URL', async ({ page }) => {
		test.setTimeout(120_000);

		await openPublicExample(page, 'library-book-return-workflow', 'example-library-book-return-workflow');

		const parent = page.locator('[data-testid="embed-preview"][data-app-id="workflows"][data-skill-id="create-or-modify"][data-status="finished"]').first();
		await expect(parent).toBeVisible({ timeout: 30_000 });
		await expect(parent).toContainText('Library Book Return Checklist');
		await expect(parent).toContainText('Workflow created');

		const fullscreen = await openFullscreen(page, parent);
		await expect(fullscreen).toContainText('Library Book Return Checklist', { timeout: 15_000 });
		await expect(fullscreen.getByTestId('search-template-empty')).toBeVisible({ timeout: 15_000 });
		await closeFullscreen(page, fullscreen);
	});
});
