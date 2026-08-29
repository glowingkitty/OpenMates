/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Deployed responsive composer model-routing contract.
 *
 * Verifies direct and grouped actions, provider ordering, exact picker choices,
 * alias-to-exact mention resolution, accessible compact labels, and overflow.
 * The checkpoints provide laptop and phone proof-video evidence.
 */

export {};

const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_DEVICE = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10) === 390 ? 'web-phone' : 'web-laptop';
const EXPECTED_PROVIDERS = [
	{ id: 'openai', label: 'ChatGPT' },
	{ id: 'anthropic', label: 'Claude' },
	{ id: 'mistral', label: 'Mistral' },
	{ id: 'deepseek', label: 'DeepSeek' },
	{ id: 'google', label: 'Gemini' },
	{ id: 'alibaba', label: 'Qwen' },
	{ id: 'moonshot', label: 'Kimi' },
	{ id: 'zai', label: 'GLM' }
];
const COMPOSER_BLUR_SETTLE_MS = 250;

const COMPOSER_MODEL_ROUTING_PROOF = defineVideoProof({
	id: 'composer-model-routing',
	title: 'Responsive composer model routing',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'responsive-actions',
			text: 'The composer keeps model, camera, audio, and send controls direct while left-aligned Drawing, Location, and Files actions share one attachment menu.',
			checkpoint: 'composer-responsive-actions',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'model-picker',
			text: 'The one-line Auto select row aligns with provider rows. Show more opens the remaining providers on a separate page, and provider pages sort newest models before capability.',
			checkpoint: 'composer-model-picker',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'mention-selection',
			text: 'Typing the Best model shortcut resolves to Claude Fable 5, shows Claude with a max capability badge in the selector, and removes the redundant mention.',
			checkpoint: 'composer-exact-selection',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'ai-model-routing.composer.responsive-actions',
			checkpoint: 'composer-responsive-actions',
			visual: 'The grouped attachment menu and direct model, camera, audio, and send controls are reachable without clipping.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'ai-model-routing.composer.picker-provider-order',
			checkpoint: 'composer-model-picker',
			visual: 'Auto select is a single aligned row, product-brand providers use separate main and more pages, and model rows sort by release date then capability.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'ai-model-routing.composer.mention-to-exact-selection',
			checkpoint: 'composer-exact-selection',
			visual: 'The resolved provider brand and capability badge are visible while the redundant model mention is absent from editable text.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

async function assertProof(proof: any, assertionId: string, assertion: () => Promise<void>): Promise<void> {
	if (proof) {
		await proof.assert(assertionId, assertion);
		return;
	}
	await assertion();
}

async function focusComposer(page: any): Promise<any> {
	const editor = page.getByTestId('message-editor').last();
	await expect(editor).toBeVisible({ timeout: 20000 });
	await page.waitForTimeout(600);
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');
	await expect(page.getByTestId('action-buttons').last()).toBeVisible({ timeout: 20000 });
	return editor;
}

async function expectComposerFocusPreserved(page: any, composer: any, expectEditorFocus = true): Promise<void> {
	await page.waitForTimeout(COMPOSER_BLUR_SETTLE_MS);
	await expect(composer).toHaveAttribute('data-focused', 'true');
	await expect(composer.getByTestId('action-buttons')).toBeVisible();
	if (expectEditorFocus) {
		await expect.poll(async () => composer.getByTestId('message-editor').evaluate((editor: HTMLElement) => {
			const activeElement = document.activeElement;
			return activeElement === editor || editor.contains(activeElement);
		})).toBe(true);
	}
}

// contract-test: direct surface=gui.web assertions=ai-model-routing.composer.mention-to-exact-selection,ai-model-routing.composer.responsive-actions,ai-model-routing.settings.hierarchy-canonical
test('composer picker, mentions, and grouped actions remain reachable without clipping', async ({ page }, testInfo: any) => {
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logCheckpoint = createSignupLogger('COMPOSER_MODEL_ROUTING');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'composer-model-routing' });
	const proof = IS_PROOF_CAPTURE
		? createVideoProofRuntime(COMPOSER_MODEL_ROUTING_PROOF, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => page.screenshot({ type: 'png' })
		})
		: null;

	attachConsoleListeners(page, logCheckpoint);
	attachNetworkListeners(page, logCheckpoint);
	await archiveExistingScreenshots(logCheckpoint);
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);
	const editor = await focusComposer(page);
	const composer = page.getByTestId('message-field').last();
	const selector = composer.getByTestId('composer-model-selector');

	await page.keyboard.insertText('How do I make ramen?');
	await assertProof(proof, 'ai-model-routing.composer.responsive-actions', async () => {
		await expect(selector).toHaveAttribute('aria-label', /Model selection: Auto select/i);
		await expect(composer.getByTestId('composer-camera-button')).toBeVisible();
		await expect(composer.getByTestId('record-audio-button')).toBeVisible();
		await expect(composer.getByTestId('composer-send-button')).toBeVisible();
		await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
		if (PROOF_DEVICE === 'web-phone') {
			await expect(composer.getByTestId('composer-model-selector-label')).toBeHidden();
		} else {
			await expect(composer.getByTestId('composer-model-selector-label')).toBeVisible();
		}
	});
	await composer.getByTestId('composer-attachment-menu-button').click();
	const attachmentMenu = composer.getByTestId('composer-attachment-menu');
	await expect(composer.getByTestId('composer-attachment-menu-button')).toHaveAttribute('data-icon', 'plus');
	await expect(attachmentMenu.getByTestId('composer-attachment-drawing')).toBeVisible();
	await expect(attachmentMenu.getByTestId('composer-attachment-location')).toBeVisible();
	await expect(attachmentMenu.getByTestId('composer-attachment-files')).toBeVisible();
	for (const testId of ['composer-attachment-drawing', 'composer-attachment-location', 'composer-attachment-files']) {
		await expect.poll(async () => attachmentMenu.getByTestId(testId).evaluate((element: HTMLElement) => getComputedStyle(element).justifyContent)).toBe('flex-start');
	}
	await expect(attachmentMenu).toBeVisible();
	await expectComposerFocusPreserved(page, composer);

	await attachmentMenu.getByTestId('composer-attachment-drawing').click();
	await expectComposerFocusPreserved(page, composer, false);
	await composer.getByRole('button', { name: 'Close sketch' }).click();

	await composer.getByTestId('composer-attachment-menu-button').click();
	await attachmentMenu.getByTestId('composer-attachment-location').click();
	await expectComposerFocusPreserved(page, composer, false);
	await composer.getByRole('button', { name: 'Close', exact: true }).click();

	await composer.getByTestId('composer-attachment-menu-button').click();
	await Promise.all([
		page.waitForEvent('filechooser'),
		attachmentMenu.getByTestId('composer-attachment-files').click()
	]);
	await expectComposerFocusPreserved(page, composer);
	await takeStepScreenshot(page, '01-responsive-actions');
	if (proof) await proof.checkpoint('composer-responsive-actions');

	await selector.click();
	const selectorMenu = composer.getByTestId('composer-model-selector-menu');
	await expect(selectorMenu).toHaveAttribute('role', 'group');
	await assertProof(proof, 'ai-model-routing.composer.picker-provider-order', async () => {
		const autoRow = selectorMenu.getByTestId('composer-model-auto');
		const openAiRow = selectorMenu.getByTestId('composer-model-provider-openai');
		await expect(autoRow).toHaveText('Auto select');
		for (let index = 0; index < 4; index += 1) {
			await expect(selectorMenu.getByTestId(`composer-model-provider-${EXPECTED_PROVIDERS[index].id}`)).toContainText(EXPECTED_PROVIDERS[index].label);
		}
		await expect(openAiRow).toContainText('from OpenAI');
		await expect(selectorMenu.getByTestId('composer-model-provider-anthropic')).toContainText('from Anthropic');
		await expect(selectorMenu.getByTestId('composer-model-provider-mistral')).toHaveText('Mistral');
		await expect(selectorMenu.getByTestId('composer-model-provider-deepseek')).toHaveText('DeepSeek');
		for (const provider of EXPECTED_PROVIDERS.slice(0, 4)) {
			await expect.poll(async () => selectorMenu.getByTestId(`composer-model-provider-${provider.id}`).evaluate((element: HTMLElement) => getComputedStyle(element).justifyContent)).toBe('flex-start');
		}
		await expect(selectorMenu.getByTestId('composer-model-show-more')).toHaveText('Show more');
		const [autoIconBox, providerIconBox, autoLabelBox, providerLabelBox] = await Promise.all([
			autoRow.getByTestId('composer-model-auto-icon').boundingBox(),
			openAiRow.getByTestId('composer-model-provider-icon').boundingBox(),
			autoRow.getByTestId('composer-model-auto-label').boundingBox(),
			openAiRow.getByTestId('composer-model-provider-label').boundingBox()
		]);
		expect(autoIconBox).toBeTruthy();
		expect(providerIconBox).toBeTruthy();
		expect(autoLabelBox).toBeTruthy();
		expect(providerLabelBox).toBeTruthy();
		expect(Math.abs(autoIconBox!.width - providerIconBox!.width)).toBeLessThanOrEqual(1);
		expect(Math.abs(autoIconBox!.height - providerIconBox!.height)).toBeLessThanOrEqual(1);
		expect(Math.abs(autoLabelBox!.x - providerLabelBox!.x)).toBeLessThanOrEqual(1);
		await expect(selectorMenu).toBeVisible();
		await expectComposerFocusPreserved(page, composer);
	});
	await takeStepScreenshot(page, '02-model-picker');
	if (proof) await proof.checkpoint('composer-model-picker');
	await selectorMenu.getByTestId('composer-model-show-more').focus();
	await page.keyboard.press('Escape');
	await expect(selectorMenu).toBeHidden();
	await selector.click();

	await selectorMenu.getByTestId('composer-model-show-more').click();
	await expectComposerFocusPreserved(page, composer);
	const modelSelectionBack = selectorMenu.getByTestId('composer-model-back');
	await expect(modelSelectionBack).toHaveText('Model selection');
	await expect(selectorMenu.getByTestId('composer-model-auto')).toBeHidden();
	await expect(selectorMenu.getByTestId('composer-model-provider-openai')).toBeHidden();
	for (const provider of EXPECTED_PROVIDERS.slice(4)) {
		await expect(selectorMenu.getByTestId(`composer-model-provider-${provider.id}`)).toContainText(provider.label);
	}
	await modelSelectionBack.click();
	await expectComposerFocusPreserved(page, composer);
	await expect(selectorMenu.getByTestId('composer-model-auto')).toBeVisible();
	await expect(selectorMenu.getByTestId('composer-model-provider-openai')).toBeVisible();

	await selectorMenu.getByTestId('composer-model-provider-openai').click();
	await expectComposerFocusPreserved(page, composer);
	await expect(selectorMenu.getByTestId('composer-model-name')).toHaveText([
		'GPT-5.6 Sol Max',
		'GPT-5.6 Sol',
		'GPT-5.6 Terra',
		'GPT-5.6 Luna',
		'GPT-5.5',
		'GPT-5.4',
		'GPT-OSS-120b',
		'GPT-OSS-20b'
	]);
	const firstModelRow = selectorMenu.getByTestId('composer-model-row').first();
	const firstModelName = firstModelRow.getByTestId('composer-model-name');
	const firstModelToggle = firstModelRow.getByTestId('composer-model-toggle');
	const firstModelIcon = firstModelRow.getByTestId('composer-model-icon');
	const firstModelCapability = firstModelRow.getByTestId('composer-model-capability');
	await expect(firstModelName).toBeVisible();
	await expect(firstModelToggle.getByRole('checkbox')).not.toBeChecked();
	await expect(firstModelRow).not.toContainText('?');
	await expect.poll(async () => firstModelName.evaluate((element: HTMLElement) => getComputedStyle(element).justifyContent)).toBe('flex-start');
	const modelDetailsLabel = await firstModelName.getAttribute('aria-label');
	expect(modelDetailsLabel).toBeTruthy();
	await expect(firstModelName).toHaveText(modelDetailsLabel!.split(': ').at(-1)!);
	await expect(firstModelCapability).toHaveAttribute('data-level', /^(low|medium|high|max)$/);
	const [rowBox, nameBox, toggleBox, iconBox, capabilityBox] = await Promise.all([
		firstModelRow.boundingBox(),
		firstModelName.boundingBox(),
		firstModelToggle.boundingBox(),
		firstModelIcon.boundingBox(),
		firstModelCapability.boundingBox()
	]);
	expect(rowBox).toBeTruthy();
	expect(nameBox).toBeTruthy();
	expect(toggleBox).toBeTruthy();
	expect(iconBox).toBeTruthy();
	expect(capabilityBox).toBeTruthy();
	expect(nameBox!.x).toBeLessThan(toggleBox!.x);
	const toggleRightInset = rowBox!.x + rowBox!.width - (toggleBox!.x + toggleBox!.width);
	expect(toggleRightInset).toBeGreaterThanOrEqual(0);
	expect(toggleRightInset).toBeLessThanOrEqual(8);
	expect(capabilityBox!.x + capabilityBox!.width / 2).toBeGreaterThan(iconBox!.x + iconBox!.width / 2);
	expect(capabilityBox!.y + capabilityBox!.height / 2).toBeGreaterThan(iconBox!.y + iconBox!.height / 2);
	await takeStepScreenshot(page, '03-model-list');
	await firstModelName.click();
	await expect(page.getByTestId('ai-model-details')).toBeVisible();
	await page.waitForTimeout(COMPOSER_BLUR_SETTLE_MS);
	await expect(composer).toHaveAttribute('data-focused', 'false');
	await page.getByTestId('icon-button-close').click();
	await expect(page.getByTestId('ai-model-details')).toBeHidden();
	await expect(selector).toHaveAttribute('aria-label', /Auto select/i);

	await focusComposer(page);
	await selector.click();
	await composer.getByTestId('composer-model-selector-menu').getByTestId('composer-model-provider-openai').click();
	const solMaxRow = composer.getByTestId('composer-model-selector-menu').getByTestId('composer-model-row').filter({ hasText: 'GPT-5.6 Sol Max' });
	await solMaxRow.getByTestId('composer-model-toggle').click();
	await expect(selector).toHaveAttribute('aria-label', /Model selection: ChatGPT/i);
	await expect(composer.getByTestId('composer-model-selector-label')).toHaveText('ChatGPT');
	const [triggerIconBox, triggerCapabilityBox] = await Promise.all([
		selector.getByTestId('composer-model-selector-icon').boundingBox(),
		selector.getByTestId('composer-model-selector-capability').boundingBox()
	]);
	expect(triggerIconBox).toBeTruthy();
	expect(triggerCapabilityBox).toBeTruthy();
	expect(triggerCapabilityBox!.x + triggerCapabilityBox!.width / 2).toBeLessThan(triggerIconBox!.x + triggerIconBox!.width / 2);
	expect(triggerCapabilityBox!.y + triggerCapabilityBox!.height / 2).toBeGreaterThan(triggerIconBox!.y + triggerIconBox!.height / 2);

	await selector.click();
	const reopenedMenu = composer.getByTestId('composer-model-selector-menu');
	await expect(reopenedMenu.getByTestId('composer-model-auto')).toBeHidden();
	await expect(reopenedMenu.getByTestId('composer-model-back')).toBeVisible();
	await expect(reopenedMenu.getByTestId('composer-model-row').filter({ hasText: 'GPT-5.6 Sol Max' }).getByRole('checkbox')).toBeChecked();
	await reopenedMenu.getByTestId('composer-model-back').click();
	await expect(reopenedMenu.getByTestId('composer-model-auto')).toBeVisible();
	await selector.click();

	await editor.click();
	await page.keyboard.press('Control+A');
	await page.keyboard.press('Backspace');
	await page.keyboard.insertText('@best');
	const bestMention = page.locator('[data-testid="mention-result"][data-mention-type="model_alias"]').first();
	await expect(bestMention).toBeVisible({ timeout: 10000 });
	await bestMention.click();
	await assertProof(proof, 'ai-model-routing.composer.mention-to-exact-selection', async () => {
		await expect(selector).toHaveAttribute('aria-label', /Model selection: Claude/i);
		await expect(selector.getByTestId('composer-model-selector-capability')).toHaveAttribute('data-level', 'max');
		await expect.poll(async () => editor.evaluate((element: HTMLElement) => element.innerText.trim())).toBe('');
		await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
	});
	await takeStepScreenshot(page, '04-exact-selection');
	if (proof) {
		await proof.checkpoint('composer-exact-selection');
		await proof.attach();
	}
});
