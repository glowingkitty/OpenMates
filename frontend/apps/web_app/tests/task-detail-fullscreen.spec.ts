/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Focused component coverage for the read-only Task detail fullscreen.
 *
 * Uses the deterministic component preview to verify the Figma-aligned content,
 * responsive layout, keyboard close behavior, and visible linked-work context.
 * Product contract: contracts/features/tasks/contract.yml
 */
export {};

const { expect, test } = require('./helpers/cookie-audit');

async function openTaskDetailPreview(page: any): Promise<void> {
	const response = await page.goto('/dev/preview/tasks/TaskDetailFullscreen', { waitUntil: 'networkidle' });
	expect(response?.status()).toBe(200);
	await expect(page.getByTestId('preview-status-bar')).toContainText('preview.ts loaded', { timeout: 15_000 });
	await expect(page.getByTestId('render-error')).not.toBeVisible({ timeout: 5_000 });
	await expect(page.getByTestId('task-detail-fullscreen')).toBeVisible({ timeout: 15_000 });
}

test.describe('Task detail fullscreen component', () => {
	// contract-test: direct surface=gui.web assertions=tasks.detail.embed-responsive,tasks.surface.semantic-parity
	test('renders complete read-only task context and closes from the keyboard', async ({ page }) => {
		await openTaskDetailPreview(page);

		const detail = page.getByTestId('task-detail-content');
		await expect(detail.getByTestId('task-detail-title')).toContainText('Design 3D model');
		await expect(detail.getByTestId('task-detail-description')).toContainText('fits 2-3 people');
		await expect(detail.getByTestId('task-detail-status')).toContainText('To do');
		await expect(detail.getByTestId('task-detail-priority')).toContainText('Urgent');
		await expect(detail.getByTestId('task-detail-assignee')).toContainText('OpenMates');
		await expect(detail.getByTestId('task-detail-due')).toContainText('Oct 22, 2026');
		await expect(detail.getByTestId('task-detail-projects')).toContainText('Research project');
		await expect(detail.getByTestId('task-detail-plan')).toContainText('Research launch plan');
		await expect(detail.getByTestId('task-detail-dependencies')).toContainText('Prepare research brief');
		await expect(detail.getByTestId('task-detail-tags')).toContainText('#software');
		await expect(detail.getByTestId('task-detail-chat')).toContainText('3D model planning');

		const close = page.getByTestId('task-detail-minimize');
		await close.focus();
		await expect(close).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(page.getByTestId('task-detail-fullscreen')).not.toBeVisible({ timeout: 2_000 });
	});

	// contract-test: supporting surface=gui.web assertions=tasks.detail.embed-responsive
	test('keeps every detail section reachable on a phone viewport', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await openTaskDetailPreview(page);

		const detail = page.getByTestId('task-detail-content');
		await expect(detail.getByTestId('task-detail-title')).toBeVisible();
		await detail.getByTestId('task-detail-chat').scrollIntoViewIfNeeded();
		await expect(detail.getByTestId('task-detail-chat')).toBeVisible();
		const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
		expect(overflow, 'Task detail should not create horizontal page overflow on mobile').toBeLessThan(8);
	});
});
