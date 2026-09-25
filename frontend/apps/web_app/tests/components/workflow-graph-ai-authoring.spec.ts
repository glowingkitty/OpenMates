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

type Box = { x: number; y: number; width: number; height: number };

function overlaps(first: Box, second: Box): boolean {
	return (
		first.x < second.x + second.width &&
		first.x + first.width > second.x &&
		first.y < second.y + second.height &&
		first.y + first.height > second.y
	);
}

function expectInside(outer: Box, inner: Box, tolerance = 1): void {
	expect(inner.x).toBeGreaterThanOrEqual(outer.x - tolerance);
	expect(inner.y).toBeGreaterThanOrEqual(outer.y - tolerance);
	expect(inner.x + inner.width).toBeLessThanOrEqual(outer.x + outer.width + tolerance);
	expect(inner.y + inner.height).toBeLessThanOrEqual(outer.y + outer.height + tolerance);
}

function expectHorizontallyInside(outer: Box, inner: Box, tolerance = 1): void {
	expect(inner.x).toBeGreaterThanOrEqual(outer.x - tolerance);
	expect(inner.x + inner.width).toBeLessThanOrEqual(outer.x + outer.width + tolerance);
}

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
		const coloredHeader = editor.locator('.editor-header.colored');
		const headerBox = await coloredHeader.boundingBox();
		expect(headerBox && headerBox.height >= 180).toBe(true);
		await expect(coloredHeader.locator('.collapse')).toHaveCount(0);
		await expect(coloredHeader.getByRole('button', { name: 'Close' })).toBeVisible();
		const appIcon = editor.getByTestId('workflow-editor-primary-icon');
		const appIconBox = await appIcon.boundingBox();
		expect(appIconBox && appIconBox.width >= 38 && appIconBox.height >= 38).toBe(true);
		const headerType = await editor.locator('.eyebrow').evaluate((element) => ({
			eyebrow: Number.parseFloat(getComputedStyle(element).fontSize),
			title: Number.parseFloat(
				getComputedStyle(element.closest('.title')?.querySelector('strong') as Element).fontSize
			),
			subtitle: Number.parseFloat(
				getComputedStyle(element.closest('.title')?.querySelector('.subtitle') as Element).fontSize
			)
		}));
		expect(headerType.eyebrow).toBeGreaterThanOrEqual(16);
		expect(headerType.title).toBeGreaterThanOrEqual(18);
		expect(headerType.subtitle).toBeGreaterThanOrEqual(18);
		await expect(editor).toContainText('Weather | Get forecast');
		await expect(editor).toContainText('Berlin');
		await expect(coloredHeader.locator('.breadcrumb span')).toBeVisible();
		await expect(editor.getByTestId('workflow-input-icon').locator('svg')).toBeVisible();
		await expect(editor.getByTestId('workflow-output-icon').locator('svg')).toBeVisible();
		await expect(editor.getByTestId('workflow-schema-field-location').locator('.type-badge')).toHaveText('Text');
		await expect(editor.getByTestId('workflow-schema-field-date-range').locator('.type-badge')).toHaveText('Date');
		const exampleHeading = editor.getByTestId('workflow-output-example-heading');
		await expect(exampleHeading).toHaveText('Example:');
		const firstOutput = editor.getByTestId('workflow-output-fields').locator(':scope > div').first();
		const [exampleHeadingBox, firstOutputLabelBox, firstOutputValueBox] = await Promise.all([
			exampleHeading.boundingBox(),
			firstOutput.locator('.output-label').boundingBox(),
			firstOutput.getByTestId('workflow-readable-value').boundingBox()
		]);
		expect(exampleHeadingBox && firstOutputLabelBox && firstOutputValueBox).not.toBeNull();
		if (exampleHeadingBox && firstOutputLabelBox && firstOutputValueBox) {
			expect(Math.abs(exampleHeadingBox.x - firstOutputValueBox.x)).toBeLessThan(2);
			expect(Math.abs(firstOutputLabelBox.y - firstOutputValueBox.y)).toBeLessThan(12);
		}
		const boolOutput = editor.getByTestId('workflow-output-fields').locator(':scope > div').filter({ hasText: 'Rain Expected' });
		await expect(boolOutput.locator('.type')).toHaveText('Bool');
		await expect(boolOutput.getByTestId('workflow-readable-value')).toHaveText('true');
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
		const chooserHeader = chooser.locator('.editor-header');
		await expect(chooserHeader.locator('.collapse')).toHaveCount(0);
		await expect(chooserHeader.getByRole('button', { name: 'Close' })).toBeVisible();
		const backButton = chooserHeader.getByRole('button', { name: 'Add action' });
		const [backIconBox, messageIconBox, messageIconStyle] = await Promise.all([
			backButton.locator('svg').boundingBox(),
			chooserHeader.getByTestId('workflow-editor-primary-icon').boundingBox(),
			chooserHeader.getByTestId('workflow-editor-primary-icon').evaluate((element) => ({
				color: getComputedStyle(element).color,
				headerColor: getComputedStyle(element.closest('.editor-header') as Element).color
			}))
		]);
		expect(backIconBox).not.toBeNull();
		expect(messageIconBox).not.toBeNull();
		if (!backIconBox || !messageIconBox) return;
		expect(backIconBox.width).toBeGreaterThanOrEqual(24);
		expect(backIconBox.height).toBe(backIconBox.width);
		expect(messageIconBox.width).toBeGreaterThanOrEqual(18);
		expect(messageIconBox.width).toBeLessThanOrEqual(20);
		expect(messageIconBox.height).toBe(messageIconBox.width);
		expect(messageIconBox.width).toBeLessThan(backIconBox.width);
		expect(messageIconStyle.color).toBe(messageIconStyle.headerColor);
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
		const newChat = chooser.getByTestId('workflow-new-chat-destination');
		await expect(newChat).toHaveText('New chat');
		const [newChatIconBox, newChatIconMask] = await Promise.all([
			newChat.locator('.new-chat-icon').boundingBox(),
			newChat.locator('.new-chat-icon').evaluate((element) => getComputedStyle(element).maskImage)
		]);
		expect(newChatIconBox).not.toBeNull();
		if (!newChatIconBox) return;
		expect(newChatIconBox.width).toBeGreaterThanOrEqual(20);
		expect(newChatIconBox.height).toBe(newChatIconBox.width);
		expect(newChatIconMask).not.toBe('none');

		await backButton.click();
		const actionPicker = page.getByTestId('workflow-step-menu');
		await expect(actionPicker).toBeVisible();
		await expect(actionPicker.locator('.choice')).toHaveText([
			'Use app',
			'Ask AI',
			'Add check',
			'Send message'
		]);
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.visual-language.coherent,workflows-ui.responsive-accessible-reachable
	test('keeps the enlarged app skill header readable without phone overlap', async ({
		page
	}: {
		page: Page;
	}) => {
		await page.setViewportSize({ width: 390, height: 900 });
		await page.goto(preview(undefined, 390), { waitUntil: 'networkidle' });
		await page.locator('[data-node-id="weather"]').getByTestId('workflow-node-summary').click();
		const header = page.getByTestId('workflow-node-expanded').locator('.editor-header.colored');
		const content = [
			header.locator('.eyebrow'),
			header.getByTestId('workflow-editor-primary-icon'),
			header.locator('.title strong'),
			header.locator('.subtitle')
		];
		const controls = [
			header.locator('.breadcrumb'),
			header.locator('.close-control')
		];
		const editor = page.getByTestId('workflow-node-expanded');
		const previewViewport = page.getByTestId('component-preview-viewport');
		const example = editor.getByTestId('workflow-output-example-heading');
		const back = header.getByRole('button', { name: 'App skill' });
		const backLabel = back.locator('span');
		const save = editor.getByTestId('workflow-node-save');
		const remove = editor.getByTestId('remove-workflow-node');
		const close = header.locator('.close-control');
		const [
			headerBox,
			editorBox,
			viewportBox,
			iconBox,
			exampleBox,
			backBox,
			saveBox,
			removeBox,
			closeBox,
			phoneType,
			contentBoxes,
			controlBoxes,
			overflow
		] = await Promise.all([
			header.boundingBox(),
			editor.boundingBox(),
			previewViewport.boundingBox(),
			header.getByTestId('workflow-editor-primary-icon').boundingBox(),
			example.boundingBox(),
			back.boundingBox(),
			save.boundingBox(),
			remove.boundingBox(),
			close.boundingBox(),
			header.locator('.eyebrow').evaluate((element) => ({
				eyebrow: Number.parseFloat(getComputedStyle(element).fontSize),
				title: Number.parseFloat(
					getComputedStyle(element.closest('.title')?.querySelector('strong') as Element).fontSize
				)
			})),
			Promise.all(content.map((element) => element.boundingBox())),
			Promise.all(controls.map((element) => element.boundingBox())),
			Promise.all([
				editor.evaluate((element) => ({
					clientWidth: element.clientWidth,
					scrollWidth: element.scrollWidth
				})),
				previewViewport.evaluate((element) => ({
					clientWidth: element.clientWidth,
					scrollWidth: element.scrollWidth
				}))
			])
		]);
		expect(headerBox && headerBox.height >= 168).toBe(true);
		expect(iconBox && iconBox.width >= 34 && iconBox.height >= 34).toBe(true);
		expect(phoneType.eyebrow).toBeGreaterThanOrEqual(15);
		expect(phoneType.title).toBeGreaterThanOrEqual(17);
		await expect(header.locator('.collapse')).toHaveCount(0);
		await expect(header.getByRole('button', { name: 'Close' })).toBeVisible();
		await expect(backLabel).toBeHidden();
		await expect(example).toHaveText('Example:');
		await expect(editor.getByTestId('workflow-schema-field-location').locator('.type-badge')).toBeVisible();
		await expect(editor.getByTestId('workflow-schema-field-date-range').locator('.type-badge')).toBeVisible();
		const [mobileInputTypeBox, mobileInputNameBox, mobileOutputTypeBox, mobileOutputNameBox] = await Promise.all([
			editor.getByTestId('workflow-schema-field-location').locator('.type-badge').boundingBox(),
			editor.getByTestId('workflow-schema-field-location').locator('.field-title').boundingBox(),
			editor.getByTestId('workflow-output-fields').locator('.output-label .type').first().boundingBox(),
			editor.getByTestId('workflow-output-fields').locator('.output-label strong').first().boundingBox()
		]);
		expect(mobileInputTypeBox && mobileInputNameBox && mobileOutputTypeBox && mobileOutputNameBox).not.toBeNull();
		if (mobileInputTypeBox && mobileInputNameBox && mobileOutputTypeBox && mobileOutputNameBox) {
			expect(mobileInputTypeBox.y + mobileInputTypeBox.height).toBeLessThanOrEqual(mobileInputNameBox.y + 1);
			expect(mobileOutputTypeBox.y + mobileOutputTypeBox.height).toBeLessThanOrEqual(mobileOutputNameBox.y + 1);
		}
		const mobileFirstOutput = editor.getByTestId('workflow-output-fields').locator(':scope > div').first();
		const [mobileOutputLabelBox, mobileOutputValueBox] = await Promise.all([
			mobileFirstOutput.locator('.output-label').boundingBox(),
			mobileFirstOutput.getByTestId('workflow-readable-value').boundingBox()
		]);
		expect(mobileOutputLabelBox && mobileOutputValueBox).not.toBeNull();
		if (mobileOutputLabelBox && mobileOutputValueBox) {
			expect(Math.abs(mobileOutputLabelBox.y - mobileOutputValueBox.y)).toBeLessThan(12);
		}
		await expect(save).toBeVisible();
		await expect(remove).toBeVisible();
		expect(editorBox).not.toBeNull();
		expect(viewportBox).not.toBeNull();
		expect(exampleBox).not.toBeNull();
		expect(backBox).not.toBeNull();
		expect(saveBox).not.toBeNull();
		expect(removeBox).not.toBeNull();
		expect(closeBox).not.toBeNull();
		if (
			!headerBox ||
			!editorBox ||
			!viewportBox ||
			!exampleBox ||
			!backBox ||
			!saveBox ||
			!removeBox ||
			!closeBox
		)
			return;
		expectInside(editorBox, headerBox);
		expectInside(editorBox, closeBox);
		expect(backBox.x).toBeLessThan(headerBox.x + 35);
		expect(backBox.y).toBeLessThan(headerBox.y + 25);
		for (const elementBox of [exampleBox, saveBox, removeBox]) {
			expectInside(editorBox, elementBox);
			expectHorizontallyInside(viewportBox, elementBox);
		}
		expectHorizontallyInside(viewportBox, headerBox);
		expectHorizontallyInside(viewportBox, closeBox);
		for (const dimensions of overflow) {
			expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
		}
		for (const contentBox of contentBoxes) {
			expect(contentBox).not.toBeNull();
			if (!contentBox) continue;
			for (const controlBox of controlBoxes) {
				expect(controlBox).not.toBeNull();
				if (controlBox) expect(overlaps(contentBox, controlBox)).toBe(false);
			}
		}
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
