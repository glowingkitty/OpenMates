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
const EXPECTED_PROVIDER_ORDER = ['ChatGPT', 'Claude', 'Mistral', 'DeepSeek', 'Gemini', 'Qwen'];
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
			text: 'The model picker starts with Auto select, groups exact models by provider, opens model settings from each model name, and applies a chat override only from its toggle.',
			checkpoint: 'composer-model-picker',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'mention-selection',
			text: 'Typing the Best model shortcut resolves to Claude Fable 5, updates the selector, and removes the redundant mention from the message.',
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
			visual: 'Auto select and product-brand providers appear in the approved order, and model rows use toggles instead of question-mark controls.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'ai-model-routing.composer.mention-to-exact-selection',
			checkpoint: 'composer-exact-selection',
			visual: 'The exact resolved model is visibly identified while the redundant model mention is absent from editable text.',
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
	await page.waitForTimeout(COMPOSER_BLUR_SETTLE_MS);
	await expect(attachmentMenu).toBeVisible();
	await expect(composer).toHaveAttribute('data-focused', 'true');
	await expect(composer.getByTestId('action-buttons')).toBeVisible();
	await takeStepScreenshot(page, '01-responsive-actions');
	if (proof) await proof.checkpoint('composer-responsive-actions');
	await composer.getByTestId('composer-attachment-menu-button').click();
	await expect(attachmentMenu).toBeHidden();

	await selector.click();
	const selectorMenu = composer.getByTestId('composer-model-selector-menu');
	await assertProof(proof, 'ai-model-routing.composer.picker-provider-order', async () => {
		await expect(selectorMenu.getByTestId('composer-model-auto')).toContainText('Auto select');
		const providerRows = selectorMenu.getByRole('menuitem');
		for (let index = 0; index < 4; index += 1) {
			await expect(providerRows.nth(index + 1)).toContainText(EXPECTED_PROVIDER_ORDER[index]);
		}
		await expect(selectorMenu.getByTestId('composer-model-provider-openai')).toContainText('from OpenAI');
		await expect(selectorMenu.getByTestId('composer-model-provider-anthropic')).toContainText('from Anthropic');
		await expect(selectorMenu.getByTestId('composer-model-provider-mistral')).toHaveText('Mistral');
		await expect(selectorMenu.getByTestId('composer-model-provider-deepseek')).toHaveText('DeepSeek');
		for (const provider of EXPECTED_PROVIDER_ORDER.slice(0, 4)) {
			await expect.poll(async () => selectorMenu.getByTestId(`composer-model-provider-${provider}`).evaluate((element: HTMLElement) => getComputedStyle(element).justifyContent)).toBe('flex-start');
		}
		await expect(selectorMenu.getByTestId('composer-model-show-more')).toBeVisible();
		await page.waitForTimeout(COMPOSER_BLUR_SETTLE_MS);
		await expect(selectorMenu).toBeVisible();
		await expect(composer).toHaveAttribute('data-focused', 'true');
	});
	await takeStepScreenshot(page, '02-model-picker');
	if (proof) await proof.checkpoint('composer-model-picker');

	const providerRows = selectorMenu.getByRole('menuitem');
	await selectorMenu.getByTestId('composer-model-show-more').click();
	for (let index = 4; index < EXPECTED_PROVIDER_ORDER.length; index += 1) {
		await expect(providerRows.nth(index + 1)).toContainText(EXPECTED_PROVIDER_ORDER[index]);
	}
	await selectorMenu.getByTestId('composer-model-provider-openai').click();
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
	await expect.poll(async () => {
		const [rowBox, nameBox, toggleBox, iconBox, capabilityBox] = await Promise.all([
			firstModelRow.boundingBox(),
			firstModelName.boundingBox(),
			firstModelToggle.boundingBox(),
			firstModelIcon.boundingBox(),
			firstModelCapability.boundingBox()
		]);
		if (!rowBox || !nameBox || !toggleBox || !iconBox || !capabilityBox) return false;
		return nameBox.x < toggleBox.x
			&& toggleBox.x + toggleBox.width >= rowBox.x + rowBox.width - 1
			&& capabilityBox.x >= iconBox.x + iconBox.width / 2
			&& capabilityBox.y >= iconBox.y + iconBox.height / 2;
	}).toBe(true);
	await firstModelName.click();
	await expect(page.getByTestId('ai-model-details')).toBeVisible();
	await page.getByTestId('icon-button-close').click();
	await expect(page.getByTestId('ai-model-details')).toBeHidden();
	await expect(selector).toHaveAttribute('aria-label', /Auto select/i);

	await selector.click();
	await composer.getByTestId('composer-model-selector-menu').getByTestId('composer-model-provider-openai').click();
	await composer.getByTestId('composer-model-selector-menu').getByTestId('composer-model-row').first().getByTestId('composer-model-toggle').click();
	await expect(selector).not.toHaveAttribute('aria-label', /Auto select/i);

	await editor.click();
	await page.keyboard.press('Control+A');
	await page.keyboard.press('Backspace');
	await page.keyboard.insertText('@best');
	const bestMention = page.locator('[data-testid="mention-result"][data-mention-type="model_alias"]').first();
	await expect(bestMention).toBeVisible({ timeout: 10000 });
	await bestMention.click();
	await assertProof(proof, 'ai-model-routing.composer.mention-to-exact-selection', async () => {
		await expect(selector).toHaveAttribute('aria-label', /Claude Fable 5/i);
		await expect.poll(async () => editor.evaluate((element: HTMLElement) => element.innerText.trim())).toBe('');
		await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
	});
	await takeStepScreenshot(page, '03-exact-selection');
	if (proof) {
		await proof.checkpoint('composer-exact-selection');
		await proof.attach();
	}
});
