// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
export {};
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const { expect, test } = require('../helpers/cookie-audit');

async function openStatus(page: Page, width: number, variant?: string): Promise<void> {
	await page.setViewportSize({ width, height: 800 });
	const params = new URLSearchParams({ theme: 'light', background: '#dbeafe', width: String(width), chrome: '0', ...(variant ? { variant } : {}) });
	await page.goto(`/dev/preview/workflows/WorkflowCompletionStatus?${params}`, { waitUntil: 'domcontentloaded' });
	await waitForComponentPreview(page, 60_000);
	await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
}

test.describe('Workflow completion notification status preview', () => {
	// contract-test: supporting surface=gui.web assertions=notifications.workflow-run.chat-target
	test('shows loading and an accessible unavailable retry at phone and laptop widths', async ({ page }: { page: Page }) => {
		test.setTimeout(90_000);
		for (const width of [390, 900]) {
			await openStatus(page, width);
			const loading = page.getByTestId('workflow-completion-chat-loading');
			await expect(loading).toBeVisible();
			await expect(loading).toHaveAttribute('role', 'status');
			await expect(loading).toContainText('Opening the Workflow message');
			await expect(page.getByTestId('workflow-completion-chat-unavailable')).toHaveCount(0);

			await openStatus(page, width, 'unavailable');
			const unavailable = page.getByTestId('workflow-completion-chat-unavailable');
			await expect(unavailable).toBeVisible();
			await expect(unavailable).toHaveAttribute('role', 'alert');
			await expect(unavailable).toContainText('This Workflow message is unavailable');
			const retry = unavailable.getByRole('button', { name: 'retry opening the message' });
			await expect(retry).toBeVisible();
			await retry.hover();
			await retry.focus();
			await expect(retry).toBeFocused();
			const callback = page.evaluate(() => new Promise<boolean>(resolve => {
				window.addEventListener('workflow-preview-completion-retry', () => resolve(true), { once: true });
			}));
			await retry.press('Enter');
			await expect(callback).resolves.toBe(true);
			const bounds = await unavailable.boundingBox();
			expect(bounds).not.toBeNull();
			expect(bounds!.x).toBeGreaterThanOrEqual(0);
			expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
			expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
		}
	});
});
