// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page, Route } from '@playwright/test';

const { expect, test } = require('../helpers/cookie-audit');

const preview = (variant?: string, width = 900) =>
	`/dev/preview/workflows/WorkflowGraphRenderer?${new URLSearchParams({
		theme: 'light',
		background: '#dbeafe',
		width: String(width),
		chrome: '0',
		...(variant ? { variant } : {})
	})}`;

async function openLastActionMenu(page: Page): Promise<void> {
	await page.getByTestId('workflow-add-step').last().click();
	await expect(page.getByTestId('workflow-step-menu')).toBeVisible();
}

test.describe('WorkflowGraphRenderer AI authoring preview', () => {
	// contract-test: direct surface=gui.web assertions=workflows-ui.template.centered-in-place-editor,workflows-ui.mvp.ask-ai
	test('keeps Ask AI hints above the editor and blocking guidance below it', async ({ page }: { page: Page }) => {
		let releaseStaleRequest!: () => void;
		const staleRequestGate = new Promise<void>((resolve) => { releaseStaleRequest = resolve; });
		await page.route('**/v1/workflows/ai-authoring/hints', async (route: Route) => {
			const instruction = String(route.request().postDataJSON()?.instruction ?? '');
			if (instruction.includes('Slow app request')) await staleRequestGate;
			await route.fulfill({ json: instruction.includes('Search the web')
				|| instruction.includes('Slow app request')
				? { verdict: 'asks_to_invoke_app_skill', validation_path: 'jev', suggested_references: [] }
				: { verdict: 'allowed', validation_path: 'jev', suggested_references: ['$nodes.news.output.results'] }
			});
		});
		await page.goto(preview(), { waitUntil: 'networkidle' });
		await openLastActionMenu(page);
		await expect(page.getByTestId('workflow-step-menu').locator('.choice')).toHaveText([
			'Use app', 'Ask AI', 'Add check', 'Send message'
		]);
		await page.getByTestId('workflow-step-ask-ai').click();
		const editor = page.getByTestId('workflow-message-template');
		await editor.fill('Summarize the news results');
		await expect(page.getByTestId('workflow-ai-suggestions')).toContainText('Results', { timeout: 10_000 });
		const suggestionBox = await page.getByTestId('workflow-ai-suggestions').boundingBox();
		const editorBox = await editor.boundingBox();
		expect(suggestionBox && editorBox && suggestionBox.y < editorBox.y).toBe(true);

		const staleResponse = page.waitForResponse((response) =>
			response.url().includes('/v1/workflows/ai-authoring/hints')
			&& String(response.request().postDataJSON()?.instruction ?? '').includes('Slow app request')
		);
		await editor.fill('Slow app request that must become stale');
		await page.waitForRequest((request) =>
			request.url().includes('/v1/workflows/ai-authoring/hints')
			&& String(request.postDataJSON()?.instruction ?? '').includes('Slow app request')
		);
		await editor.fill('Summarize the current news results');
		await expect(page.getByTestId('workflow-ai-suggestions')).toContainText('Results', { timeout: 10_000 });
		releaseStaleRequest();
		await staleResponse;
		await expect(page.getByTestId('workflow-ai-app-warning')).toHaveCount(0);

		await editor.fill('Search the web for more news');
		await expect(page.getByTestId('workflow-ai-app-warning')).toBeVisible({ timeout: 10_000 });
		const warningBox = await page.getByTestId('workflow-ai-app-warning').boundingBox();
		const currentEditorBox = await editor.boundingBox();
		expect(warningBox && currentEditorBox && warningBox.y > currentEditorBox.y).toBe(true);
		await expect(page.getByTestId('workflow-node-save')).toBeDisabled();
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.ai-check,workflows-ui.responsive-accessible-reachable
	test('shows the selected AI question and all three branches at phone width', async ({ page }: { page: Page }) => {
		await page.goto(preview('aiCheck', 390), { waitUntil: 'networkidle' });
		const check = page.locator('[data-node-id="rain"]');
		await expect(page.locator('.branch-label')).toHaveText(['If true', 'Else', 'If unsure']);
		await check.getByTestId('workflow-node-summary').click();
		await expect(check.getByLabel('How should this be checked?')).toHaveValue('ai');
		await expect(check.getByTestId('workflow-ai-check-question')).toHaveValue(
			'Is this weather unsuitable for an outdoor lunch?'
		);
		await expect(check.getByTestId('workflow-ai-check-inputs').getByRole('checkbox', { checked: true })).toHaveCount(2);
		const box = await check.getByTestId('workflow-node-expanded').boundingBox();
		expect(box && box.width <= 390).toBe(true);
	});
});
