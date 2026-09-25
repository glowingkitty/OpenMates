// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page } from '@playwright/test';

const { expect, test } = require('../helpers/cookie-audit');

const EVENTS_PREVIEW =
	'/dev/preview/workflows/WorkflowGraphRenderer?variant=eventsSearch&theme=light&background=%23dbeafe&width=900&chrome=0';

test.describe('WorkflowGraphRenderer real skill variants', () => {
	// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring
	test('opens and inspects the Events Search capability schema', async ({
		page
	}: {
		page: Page;
	}) => {
		await page.goto(EVENTS_PREVIEW, { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute(
			'data-preview-ready',
			'true',
			{ timeout: 30000 }
		);

		const eventsNode = page.locator('[data-node-id="events"]');
		await expect(eventsNode.getByTestId('workflow-node-title-label')).toHaveText('Events | Search');
		await expect(eventsNode.getByText('Berlin', { exact: true })).toBeVisible();

		await eventsNode.getByTestId('workflow-node-summary').click();
		const editor = eventsNode.getByTestId('workflow-node-expanded');
		await expect(editor).toBeVisible();
		await expect(editor.locator('.title strong')).toHaveText('Events | Search');
		await expect(editor.getByTestId('workflow-input-heading')).toContainText('Input');
		await expect(editor.getByText('Requests *', { exact: true })).toHaveCount(0);
		await expect(editor.getByRole('button', { name: 'Add item' })).toHaveCount(0);
		await expect(editor.getByLabel('Query', { exact: true })).toHaveValue('AI');
		await expect(editor.getByTestId('workflow-node-location-picker')).toContainText('Berlin');
		await expect(editor.getByTestId('workflow-schema-field-date-range')).toHaveCount(0);
		await expect(editor.getByLabel('Event Type')).toHaveCount(0);

		const showAll = editor.getByTestId('workflow-show-all-fields');
		await expect(showAll).toHaveAttribute('aria-expanded', 'false');
		await showAll.click();
		await expect(showAll).toHaveAttribute('aria-expanded', 'true');
		await expect(editor.getByTestId('workflow-schema-field-date-range')).toBeVisible();
		await expect(editor.getByLabel('Event Type')).toBeVisible();

		await expect(editor.getByTestId('workflow-output-heading')).toContainText('Output');
		await expect(editor.getByTestId('workflow-output-field')).toHaveCount(6);
		await expect(editor.getByTestId('workflow-output-fields')).toContainText('Results');
		await editor.getByTestId('workflow-output-fields').locator('summary').filter({ hasText: '1 items' }).click();
		await expect(editor.getByTestId('workflow-output-fields')).toContainText('AI community meetup');
	});
});
