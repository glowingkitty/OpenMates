/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Deployed AI settings hierarchy and Figma parity contract.
 *
 * Verifies overview copy, editable tier rows, provider brands/order,
 * capability indicators, and provider/model detail navigation.
 * The same checkpoints provide phone and laptop proof-video evidence.
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
const {
	dismissSecurityReminderIfPresent,
	loginToTestAccount
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const EXPECTED_PROVIDER_ORDER = ['ChatGPT', 'Claude', 'Mistral', 'DeepSeek', 'Gemini', 'Qwen'];
const EXPECTED_HEADER_DESCRIPTION = 'Manage which AI models are used, how they respond & add your subscriptions.';
const PROOF_CAPTURE_END_HOLD_MS = 750;

const AI_MODEL_SETTINGS_PROOF = defineVideoProof({
	id: 'ai-model-settings-hierarchy',
	title: 'AI model settings hierarchy',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'overview-defaults',
			text: 'AI Settings shows editable request defaults.',
			checkpoint: 'ai-settings-overview-defaults',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'overview-providers',
			text: 'AI Settings shows product-brand model providers in the approved order.',
			checkpoint: 'ai-settings-overview-providers',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'tier-catalog',
			text: 'Simple requests opens a tier catalog with automatic routing, provider families, and capability guidance.',
			checkpoint: 'ai-tier-catalog',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'tier-provider-models',
			text: 'The ChatGPT provider page lists exact model choices for the Simple requests tier.',
			checkpoint: 'ai-tier-provider-models',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'model-detail-summary',
			text: 'A model detail page explains capability and supported inputs.',
			checkpoint: 'ai-model-detail-summary',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'model-detail-pricing-providers',
			text: 'The model detail page also shows pricing and available provider regions.',
			checkpoint: 'ai-model-detail-pricing-providers',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'ai-model-routing.settings.default-models',
			checkpoint: 'ai-settings-overview-defaults',
			visual: 'The AI settings overview visibly contains three editable default-model rows.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'ai-model-routing.settings.provider-order',
			checkpoint: 'ai-settings-overview-providers',
			visual: 'The AI settings overview visibly contains ordered branded provider rows.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'ai-model-routing.catalog.capability-recommendation-variants',
			checkpoint: 'ai-tier-catalog',
			visual: 'The tier catalog visibly identifies automatic routing, provider families, and low capability guidance.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'ai-model-routing.catalog.provider-models',
			checkpoint: 'ai-tier-provider-models',
			visual: 'The provider-specific tier catalog visibly lists exact model choices without raw translation placeholders.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'ai-model-routing.model-detail.summary',
			checkpoint: 'ai-model-detail-summary',
			visual: 'The model page visibly presents capability and details without a generic reasoning control.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'ai-model-routing.model-detail.pricing-provider-availability',
			checkpoint: 'ai-model-detail-pricing-providers',
			visual: 'The model page visibly presents pricing and provider availability.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

async function openAiSettings(page: any): Promise<void> {
	const settingsMenu = page.getByTestId('settings-menu');
	if (!(await settingsMenu.isVisible().catch(() => false))) {
		await page.locator('#settings-menu-toggle').click({ timeout: 10000 });
	}
	const visibleMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(visibleMenu).toBeVisible({ timeout: 10000 });
	await visibleMenu.getByRole('menuitem', { name: /^AI$/i }).first().click();
	await expect(visibleMenu.getByTestId('ai-settings')).toBeVisible({ timeout: 10000 });
}

// contract-test: direct surface=gui.web assertions=ai-model-routing.settings.hierarchy-canonical,ai-model-routing.catalog.capability-recommendation-variants
test('AI settings overview, tier, provider, and model detail match the approved hierarchy', async ({ page }, testInfo: any) => {
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logCheckpoint = createSignupLogger('AI_MODEL_SETTINGS');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'ai-model-settings' });
	const proof = createVideoProofRuntime(AI_MODEL_SETTINGS_PROOF, {
		device: PROOF_DEVICE,
		attach: testInfo.attach.bind(testInfo),
		captureFrame: () => page.screenshot({ type: 'png' })
	});

	attachConsoleListeners(page, logCheckpoint);
	attachNetworkListeners(page, logCheckpoint);
	await archiveExistingScreenshots(logCheckpoint);
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await dismissSecurityReminderIfPresent(page, logCheckpoint);
	await openAiSettings(page);

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	const aiSettings = settingsMenu.getByTestId('ai-settings');
	await proof.assert('ai-model-routing.settings.default-models', async () => {
		await expect(settingsMenu.getByText(EXPECTED_HEADER_DESCRIPTION, { exact: true })).toBeVisible();
		await expect(aiSettings.getByTestId('ai-tier-row-simple')).toBeVisible();
		await expect(aiSettings.getByTestId('ai-tier-row-complex')).toBeVisible();
		await expect(aiSettings.getByTestId('ai-tier-row-most-demanding')).toBeVisible();
		await expect(settingsMenu).not.toContainText('[T:');
	});
	await aiSettings.getByTestId('ai-tier-row-simple').scrollIntoViewIfNeeded();
	await takeStepScreenshot(page, '01-ai-settings-defaults');
	await proof.checkpoint('ai-settings-overview-defaults');

	const providerRows = aiSettings.getByTestId('ai-provider-family-card');
	await proof.action('show-ai-provider-rows', async () => {
		await providerRows.first().scrollIntoViewIfNeeded();
	});
	await proof.assert('ai-model-routing.settings.provider-order', async () => {
		for (let index = 0; index < EXPECTED_PROVIDER_ORDER.length; index += 1) {
			await expect(providerRows.nth(index)).toContainText(EXPECTED_PROVIDER_ORDER[index]);
		}
		await expect(providerRows.nth(0)).toContainText('from OpenAI');
		await expect(providerRows.nth(1)).toContainText('from Anthropic');
		await expect(providerRows.nth(2)).not.toContainText('from Mistral');
		await expect(settingsMenu).not.toContainText('[T:');
	});
	await takeStepScreenshot(page, '02-ai-settings-providers');
	await proof.checkpoint('ai-settings-overview-providers');

	await proof.action('open-simple-tier-catalog', async () => {
		await aiSettings.getByTestId('ai-tier-row-simple-modify-button').scrollIntoViewIfNeeded();
		await aiSettings.getByTestId('ai-tier-row-simple-modify-button').click();
	});
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'ai/tier/simple', { timeout: 10000 });
	const tierCatalog = settingsMenu.getByTestId('ai-tier-provider-catalog');
	await proof.assert('ai-model-routing.catalog.capability-recommendation-variants', async () => {
		await expect(tierCatalog.getByTestId('ai-model-option-auto')).toContainText('Auto select');
		await expect(tierCatalog.getByTestId('ai-capability-scale')).toHaveAttribute('data-level', 'low');
		await expect(tierCatalog.getByTestId('ai-provider-family-card').first()).toContainText('ChatGPT');
		await expect(settingsMenu).not.toContainText('[T:');
	});
	await tierCatalog.getByTestId('ai-provider-family-card').first().scrollIntoViewIfNeeded();
	await takeStepScreenshot(page, '03-simple-tier-families');
	await proof.checkpoint('ai-tier-catalog');

	await proof.action('open-chatgpt-provider-models', async () => {
		await tierCatalog.getByTestId('ai-provider-family-card').first().click();
	});
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'ai/tier/simple/provider/openai', { timeout: 10000 });
	const providerCatalog = settingsMenu.getByTestId('ai-tier-provider-catalog');
	await proof.assert('ai-model-routing.catalog.provider-models', async () => {
		await expect(providerCatalog.getByTestId('ai-model-option-exact').first()).toBeVisible();
		await expect(providerCatalog.getByText(/Recommended/i).first()).toBeVisible();
		await expect(settingsMenu).not.toContainText('[T:');
	});
	await takeStepScreenshot(page, '04-simple-tier-chatgpt-models');
	await proof.checkpoint('ai-tier-provider-models');

	await proof.action('open-first-chatgpt-model-detail', async () => {
		await providerCatalog.getByTestId('ai-model-option-exact').first().click();
	});
	await expect(settingsMenu).toHaveAttribute('data-active-view', /^ai\/model\//, { timeout: 10000 });
	const modelDetails = settingsMenu.getByTestId('ai-model-details');
	await proof.assert('ai-model-routing.model-detail.summary', async () => {
		await expect(modelDetails).toBeVisible();
		await expect(modelDetails.getByTestId('ai-capability-scale')).toBeVisible();
		await expect(modelDetails.getByText('Details', { exact: true })).toBeVisible();
		await expect(modelDetails.getByText(/reasoning level/i)).toHaveCount(0);
		await expect(settingsMenu).not.toContainText('[T:');
	});
	await modelDetails.getByTestId('ai-capability-scale').scrollIntoViewIfNeeded();
	await takeStepScreenshot(page, '05-model-detail-summary');
	await proof.checkpoint('ai-model-detail-summary');

	await proof.action('show-model-detail-pricing-providers', async () => {
		await modelDetails.getByText('Pricing', { exact: true }).scrollIntoViewIfNeeded();
	});
	await proof.assert('ai-model-routing.model-detail.pricing-provider-availability', async () => {
		await expect(modelDetails.getByText('Pricing', { exact: true })).toBeVisible();
		await expect(modelDetails.getByTestId('ai-model-provider-options')).toBeVisible();
		await expect(settingsMenu).not.toContainText('[T:');
	});
	await takeStepScreenshot(page, '06-model-detail-pricing-providers');
	await proof.checkpoint('ai-model-detail-pricing-providers');
	await page.waitForTimeout(PROOF_CAPTURE_END_HOLD_MS);
	await proof.attach();
});
