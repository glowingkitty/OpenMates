// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page } from '@playwright/test';

const { expect, test } = require('../helpers/cookie-audit');

const preview = (component: string, width: number, variant?: string) =>
	`/dev/preview/${component.includes('/') ? component : `workflows/${component}`}?${new URLSearchParams({
		theme: 'light',
		background: '#dbeafe',
		width: String(width),
		chrome: '0',
		...(variant ? { variant } : {})
	})}`;

test.describe('Workflow AI preview components', () => {
	// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows-ui.responsive-accessible-reachable
	test('shows a read-only pending workflow at laptop and phone widths', async ({ page }: { page: Page }) => {
		for (const width of [900, 390]) {
			await page.setViewportSize({ width, height: 844 });
			await page.goto(preview('WorkflowPendingPreview', width), { waitUntil: 'networkidle' });
			const card = page.getByTestId('workflow-ai-pending-preview');
			await expect(card).toBeVisible();
			await expect(card).toHaveAttribute('data-save-status', 'saving');
			await expect(card).toHaveAttribute('data-disabled', 'true');
			await expect(page.getByTestId('workflow-ai-saving-pill')).toBeVisible();
			await expect(page.getByTestId('workflow-ai-preview-title')).toHaveText('Weekly school weather brief');
			await expect(page.getByTestId('workflow-ai-preview-steps').locator('li')).toHaveCount(3);
			await expect(page.getByTestId('workflow-ai-preview-graph')).toHaveCount(0);
			const box = await card.boundingBox();
			expect(box).not.toBeNull();
			expect(box!.x).toBeGreaterThanOrEqual(0);
			expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
		}
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows-ui.responsive-accessible-reachable
	test('renders the editor graph while the save is pending', async ({ page }: { page: Page }) => {
		await page.goto(preview('WorkflowPendingPreview', 900, 'editor'), { waitUntil: 'networkidle' });
		const graph = page.getByTestId('workflow-ai-preview-graph');
		await expect(graph).toBeVisible();
		await expect(graph.locator('[data-node-id]')).toHaveCount(3);
		await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveAttribute('data-disabled', 'true');
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows-ui.responsive-accessible-reachable
	test('uses the chat recording UI for streamed workflow voice text', async ({ page }: { page: Page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(preview('enter_message/RecordAudio', 390), { waitUntil: 'networkidle' });
		const recorder = page.getByTestId('record-overlay');
		await expect(recorder).toBeVisible();
		await expect(page.getByTestId('recording-live-transcript')).toContainText('project review');
		await expect(page.getByTestId('record-finish-button')).toBeVisible();
		await page.getByTestId('record-cancel-button').focus();
		await expect(page.getByTestId('record-cancel-button')).toBeFocused();
		const box = await recorder.boundingBox();
		expect(box).not.toBeNull();
		expect(box!.x).toBeGreaterThanOrEqual(0);
		expect(box!.x + box!.width).toBeLessThanOrEqual(391);
	});
});
