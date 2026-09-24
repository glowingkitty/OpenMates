// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Locator, Page, Route } from '@playwright/test';

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

async function expectCenteredWithin(
	outer: { boundingBox(): Promise<{ x: number; y: number; width: number; height: number } | null> },
	inner: { boundingBox(): Promise<{ x: number; y: number; width: number; height: number } | null> }
): Promise<void> {
	const [outerBox, innerBox] = await Promise.all([outer.boundingBox(), inner.boundingBox()]);
	expect(outerBox).not.toBeNull();
	expect(innerBox).not.toBeNull();
	if (!outerBox || !innerBox) return;
	expect(innerBox.width).toBeGreaterThan(600);
	expect(innerBox.width).toBeLessThanOrEqual(outerBox.width);
	expect(
		Math.abs(innerBox.x + innerBox.width / 2 - (outerBox.x + outerBox.width / 2))
	).toBeLessThan(2);
}

async function expectLargeChoiceTile(choice: Locator): Promise<void> {
	const [choiceBox, iconBox] = await Promise.all([
		choice.boundingBox(),
		choice.locator('.workflow-icon').boundingBox()
	]);
	expect(choiceBox).not.toBeNull();
	expect(iconBox).not.toBeNull();
	if (!choiceBox || !iconBox) return;
	expect(choiceBox.width).toBeGreaterThanOrEqual(140);
	expect(choiceBox.width).toBeLessThanOrEqual(156);
	expect(choiceBox.height).toBeGreaterThanOrEqual(90);
	expect(choiceBox.height).toBeLessThanOrEqual(104);
	expect(iconBox.width).toBeGreaterThanOrEqual(26);
	expect(iconBox.width).toBeLessThanOrEqual(30);
	expect(iconBox.height).toBe(iconBox.width);
}

test.describe('WorkflowGraphRenderer AI authoring preview', () => {
	// contract-test: direct surface=gui.web assertions=workflows-ui.template.centered-in-place-editor,workflows-ui.mvp.ask-ai
	test('keeps Ask AI hints above the editor and blocking guidance below it', async ({
		page
	}: {
		page: Page;
	}) => {
		let releaseStaleRequest!: () => void;
		const staleRequestGate = new Promise<void>((resolve) => {
			releaseStaleRequest = resolve;
		});
		await page.route('**/v1/workflows/ai-authoring/hints', async (route: Route) => {
			const instruction = String(route.request().postDataJSON()?.instruction ?? '');
			if (instruction.includes('Slow app request')) await staleRequestGate;
			await route.fulfill({
				json:
					instruction.includes('Search the web') || instruction.includes('Slow app request')
						? {
								verdict: 'asks_to_invoke_app_skill',
								validation_path: 'jev',
								suggested_references: []
							}
						: {
								verdict: 'allowed',
								validation_path: 'jev',
								suggested_references: ['$nodes.news.output.results']
							}
			});
		});
		await page.goto(preview(), { waitUntil: 'networkidle' });
		await openLastActionMenu(page);
		await expect(page.getByTestId('workflow-step-menu').locator('.choice')).toHaveText([
			'Use app',
			'Ask AI',
			'Add check',
			'Send message'
		]);
		await page.getByTestId('workflow-step-ask-ai').click();
		const editor = page.getByTestId('workflow-message-template');
		await editor.fill('Summarize the news results');
		await expect(page.getByTestId('workflow-ai-suggestions')).toContainText('Results', {
			timeout: 10_000
		});
		const suggestionBox = await page.getByTestId('workflow-ai-suggestions').boundingBox();
		const editorBox = await editor.boundingBox();
		expect(suggestionBox && editorBox && suggestionBox.y < editorBox.y).toBe(true);

		const staleResponse = page.waitForResponse(
			(response) =>
				response.url().includes('/v1/workflows/ai-authoring/hints') &&
				String(response.request().postDataJSON()?.instruction ?? '').includes('Slow app request')
		);
		await editor.fill('Slow app request that must become stale');
		await page.waitForRequest(
			(request) =>
				request.url().includes('/v1/workflows/ai-authoring/hints') &&
				String(request.postDataJSON()?.instruction ?? '').includes('Slow app request')
		);
		await editor.fill('Summarize the current news results');
		await expect(page.getByTestId('workflow-ai-suggestions')).toContainText('Results', {
			timeout: 10_000
		});
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
	test('shows the selected AI question and all three branches at phone width', async ({
		page
	}: {
		page: Page;
	}) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(preview('aiCheck', 390), { waitUntil: 'networkidle' });
		const check = page.locator('[data-node-id="rain"]');
		await expect(page.locator('.branch-label')).toHaveText(['If true', 'Else', 'If unsure']);
		await check.getByTestId('workflow-node-summary').click();
		await expect(check.getByLabel('How should this be checked?')).toHaveValue('ai');
		await expect(check.getByTestId('workflow-ai-check-question')).toHaveValue(
			'Is this weather unsuitable for an outdoor lunch?'
		);
		await expect(
			check.getByTestId('workflow-ai-check-inputs').getByRole('checkbox', { checked: true })
		).toHaveCount(2);
		const box = await check.getByTestId('workflow-node-expanded').boundingBox();
		expect(box && box.width <= 390).toBe(true);
	});
});

test.describe('WorkflowGraphRenderer Figma builder preview', () => {
	// contract-test: direct surface=gui.web assertions=workflows-ui.template.centered-in-place-editor,workflows-ui.responsive-accessible-reachable
	test('uses prominent empty-state choices on desktop without overflowing a phone', async ({
		page
	}: {
		page: Page;
	}) => {
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto(preview('empty'), { waitUntil: 'networkidle' });
		const desktopChoices = page.getByTestId('workflow-action-palette').locator('.choice');
		await expect(desktopChoices).toHaveCount(2);
		await expectLargeChoiceTile(desktopChoices.nth(0));
		await expectLargeChoiceTile(desktopChoices.nth(1));

		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(preview('empty', 390), { waitUntil: 'networkidle' });
		const mobileCanvas = page.locator('.graph-canvas');
		const mobileChoices = page.getByTestId('workflow-action-palette').locator('.choice');
		const [canvasBox, triggerBox, actionBox] = await Promise.all([
			mobileCanvas.boundingBox(),
			mobileChoices.nth(0).boundingBox(),
			mobileChoices.nth(1).boundingBox()
		]);
		expect(canvasBox).not.toBeNull();
		expect(triggerBox).not.toBeNull();
		expect(actionBox).not.toBeNull();
		if (!canvasBox || !triggerBox || !actionBox) return;
		expect(Math.abs(triggerBox.y - actionBox.y)).toBeLessThan(2);
		expect(triggerBox.x).toBeGreaterThanOrEqual(canvasBox.x);
		expect(actionBox.x + actionBox.width).toBeLessThanOrEqual(canvasBox.x + canvasBox.width);
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.template.centered-in-place-editor,workflows-ui.responsive-accessible-reachable
	test('keeps the empty start compact and opens a wide focused trigger picker', async ({
		page
	}: {
		page: Page;
	}) => {
		await page.goto(preview('empty'), { waitUntil: 'networkidle' });
		const canvas = page.locator('.graph-canvas');
		const initialPalette = page.getByTestId('workflow-action-palette');
		await expect(initialPalette.getByTestId('workflow-add-time-trigger')).toBeVisible();
		await expect(initialPalette.getByTestId('workflow-add-step')).toBeVisible();
		await expect(initialPalette.locator('.choice')).toHaveCount(2);
		await page.getByTestId('workflow-add-time-trigger').click();
		const picker = page.getByTestId('workflow-step-menu');
		await expectCenteredWithin(canvas, picker);
		await expect(picker.locator('.choice')).toHaveText(['Date & Time']);
		await expect(picker.getByText('Webhook')).toHaveCount(0);
		await expect(picker.getByText('App use')).toHaveCount(0);
		const closeControl = picker.locator('.close-control');
		const [closeBox, closeButtonBox, closeIconBox] = await Promise.all([
			closeControl.boundingBox(),
			closeControl.getByRole('button', { name: 'Close' }).boundingBox(),
			closeControl.locator('.clickable-icon').boundingBox()
		]);
		expect(closeBox).not.toBeNull();
		expect(closeButtonBox).not.toBeNull();
		expect(closeIconBox).not.toBeNull();
		if (!closeBox || !closeButtonBox || !closeIconBox) return;
		expect(closeBox.width).toBeGreaterThanOrEqual(40);
		expect(closeBox.height).toBeGreaterThanOrEqual(40);
		expect(closeButtonBox.width).toBeGreaterThanOrEqual(closeBox.width - 1);
		expect(closeButtonBox.width).toBeLessThanOrEqual(closeBox.width + 1);
		expect(closeButtonBox.height).toBeGreaterThanOrEqual(closeBox.height - 1);
		expect(closeButtonBox.height).toBeLessThanOrEqual(closeBox.height + 1);
		expect(closeButtonBox.x).toBeGreaterThanOrEqual(closeBox.x - 1);
		expect(closeButtonBox.x + closeButtonBox.width).toBeLessThanOrEqual(
			closeBox.x + closeBox.width + 1
		);
		expect(closeIconBox.x).toBeGreaterThanOrEqual(closeBox.x);
		expect(closeIconBox.x + closeIconBox.width).toBeLessThanOrEqual(closeBox.x + closeBox.width);
		expect(closeIconBox.y).toBeGreaterThanOrEqual(closeBox.y);
		expect(closeIconBox.y + closeIconBox.height).toBeLessThanOrEqual(closeBox.y + closeBox.height);
		expect(
			Math.abs(
				closeIconBox.x + closeIconBox.width / 2 - (closeBox.x + closeBox.width / 2)
			)
		).toBeLessThanOrEqual(1);
		expect(
			Math.abs(
				closeIconBox.y + closeIconBox.height / 2 - (closeBox.y + closeBox.height / 2)
			)
		).toBeLessThanOrEqual(1);
		await page.getByTestId('workflow-trigger-date-time').click();
		const triggerEditor = page.getByTestId('workflow-node-expanded');
		await expect(triggerEditor).toContainText('Repeat');
		await expect(triggerEditor.getByLabel('Repeat')).toBeVisible();
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.template.centered-in-place-editor,workflows-ui.visual-language.coherent,workflows-ui.responsive-accessible-reachable
	test('expands app identity in place and shows recent chats beneath the destination question', async ({
		page
	}: {
		page: Page;
	}) => {
		await page.goto(preview(), { waitUntil: 'networkidle' });
		const canvas = page.locator('.graph-canvas');
		await page.locator('[data-node-id="weather"]').getByTestId('workflow-node-summary').click();
		const editor = page.getByTestId('workflow-node-expanded');
		await expectCenteredWithin(canvas, editor);
		const headerBox = await editor.locator('.editor-header.colored').boundingBox();
		expect(headerBox && headerBox.height >= 120).toBe(true);
		await expect(editor.getByTestId('workflow-editor-primary-icon')).toBeVisible();
		await expect(editor).toContainText('Weather | Get forecast');
		await expect(editor).toContainText('Berlin');
		const dateRange = editor.getByTestId('workflow-date-range-field');
		await expect(dateRange).toContainText('Date range');
		await expect(dateRange.getByTestId('workflow-date-range-today')).toBeVisible();
		await expect(dateRange.getByTestId('workflow-date-range-specific')).toBeVisible();
		await expect(editor.getByText('Days', { exact: true })).toHaveCount(0);
		await dateRange.getByTestId('workflow-date-range-specific').click();
		await expect(editor.getByTestId('workflow-date-range-control')).toBeVisible();
		await editor.getByRole('button', { name: 'Close' }).click();
		await openLastActionMenu(page);
		await expect(page.getByTestId('workflow-step-menu').locator('.choice')).toHaveText([
			'Use app',
			'Ask AI',
			'Add check',
			'Send message'
		]);
		await expect(page.getByTestId('workflow-step-menu').getByText('Add filter')).toHaveCount(0);
		await page.getByTestId('workflow-step-create-chat-report').click();
		const chooser = page.getByTestId('workflow-node-expanded');
		const chatCards = chooser.getByTestId('app-store-example-chat-card');
		await expect(chatCards).toHaveCount(2);
		await expect(chatCards.nth(0)).toContainText('Daily weather reports');
		await expect(chatCards.nth(0)).toContainText('Daily forecasts, rain windows');
		await expect(chatCards.nth(1)).toContainText('Language learning events');
		await expect(chatCards.nth(1)).toContainText('Privacy & user interests focused AI agents');
		const cardsBox = await chooser.locator('.card-scroll').boundingBox();
		const searchBox = await chooser
			.getByRole('textbox', { name: 'Search recent chats' })
			.boundingBox();
		expect(cardsBox && searchBox && searchBox.y >= cardsBox.y + cardsBox.height).toBe(true);
		await expect(chooser.getByTestId('workflow-new-chat-destination')).toBeVisible();
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows-ui.responsive-accessible-reachable
	test('keeps an existing message draft when returning from the destination chooser', async ({
		page
	}: {
		page: Page;
	}) => {
		await page.goto(preview(), { waitUntil: 'networkidle' });
		const messageNode = page.locator('[data-node-id="message"]');
		await messageNode.getByTestId('workflow-node-summary').click();
		let editor = messageNode.getByTestId('workflow-node-expanded');
		const title = editor.getByTestId('workflow-message-title');
		const body = editor.getByTestId('workflow-message-template');
		await title.fill('Edited morning briefing');
		await body.fill('Keep this unsaved weather and news draft.');
		await editor.getByRole('button', { name: /^To:/ }).click();
		await expect(editor.getByTestId('app-store-example-chat-card')).toHaveCount(2);
		await editor.locator('.breadcrumb').click();

		editor = messageNode.getByTestId('workflow-node-expanded');
		await expect(editor).toBeVisible();
		await expect(editor.getByTestId('workflow-message-title')).toHaveValue('Edited morning briefing');
		await expect(editor.getByTestId('workflow-message-template')).toHaveText(
			'Keep this unsaved weather and news draft.'
		);
	});
});
