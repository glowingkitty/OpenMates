/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Real image-model inference regression test.
 *
 * Uploads a repo screenshot fixture, asks for design feedback with an explicit
 * @ai-model override, then captures the actual model response. This intentionally
 * avoids TEST_MOCK markers because the production regression was provider/runtime
 * behavior after images.view returned uploaded image bytes.
 */

const path = require('path');
const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const IMAGE_FIXTURE = path.resolve(
	__dirname,
	'../../../../docs/images/architecture/messaging/messageinputfield/large_message.jpg'
);

const PROMPT = 'Evaluate the design and give recommendations for improvements.';
const TRIALS = [1, 2, 3];
const DEFAULT_SMOKE_MODEL_LABELS = ['gemini-pro'];

type ModelCase = {
	provider: string;
	model: string;
	label: string;
	expectedGeneratedBy: RegExp;
	expectsReroute?: boolean;
};

const MODELS: ModelCase[] = [
	{
		provider: 'anthropic',
		model: 'claude-haiku-4-5-20251001',
		label: 'claude-haiku',
		expectedGeneratedBy: /Claude Haiku 4\.5|claude-haiku-4-5-20251001/i
	},
	{
		provider: 'anthropic',
		model: 'claude-sonnet-4-6',
		label: 'claude-sonnet',
		expectedGeneratedBy: /Claude Sonnet 4\.6|claude-sonnet-4-6/i
	},
	{
		provider: 'anthropic',
		model: 'claude-opus-4-6',
		label: 'claude-opus-46',
		expectedGeneratedBy: /Claude Opus 4\.6|claude-opus-4-6/i
	},
	{
		provider: 'anthropic',
		model: 'claude-opus-4-7',
		label: 'claude-opus-47',
		expectedGeneratedBy: /Claude Opus 4\.7|claude-opus-4-7/i
	},
	{
		provider: 'anthropic',
		model: 'claude-opus-4-8',
		label: 'claude-opus-48',
		expectedGeneratedBy: /Claude Opus 4\.8|claude-opus-4-8/i
	},
	{
		provider: 'openai',
		model: 'gpt-5.5',
		label: 'gpt-55',
		expectedGeneratedBy: /GPT-5\.5|gpt-5\.5/i
	},
	{
		provider: 'openai',
		model: 'gpt-5.4',
		label: 'gpt-54',
		expectedGeneratedBy: /GPT-5\.4|gpt-5\.4/i
	},
	{
		provider: 'google',
		model: 'gemini-3-flash-preview',
		label: 'gemini-flash',
		expectedGeneratedBy: /Claude Sonnet 4\.6|claude-sonnet-4-6/i,
		expectsReroute: true
	},
	{
		provider: 'google',
		model: 'gemini-3.1-pro-preview',
		label: 'gemini-pro',
		expectedGeneratedBy: /Claude Sonnet 4\.6|claude-sonnet-4-6/i,
		expectsReroute: true
	},
	{
		provider: 'google',
		model: 'gemini-3.5-flash',
		label: 'gemini-35-flash',
		expectedGeneratedBy: /Claude Sonnet 4\.6|claude-sonnet-4-6/i,
		expectsReroute: true
	}
];

const fullMatrix = process.env.IMAGE_MODEL_FULL_MATRIX === '1';
const selectedLabels = new Set(
	(process.env.IMAGE_MODEL_LABELS
		? process.env.IMAGE_MODEL_LABELS.split(',').map((label: string) => label.trim()).filter(Boolean)
		: fullMatrix
			? MODELS.map((model) => model.label)
			: DEFAULT_SMOKE_MODEL_LABELS)
);
const activeModels = MODELS.filter((model) => selectedLabels.has(model.label));
const activeTrials = TRIALS;

function modelDirective(model: { provider: string; model: string }): string {
	return `@ai-model:${model.model}:${model.provider}`;
}

function scoreResponse(text: string) {
	const coordinatePairs = text.match(/\b\d{1,4}\s*,\s*\d{1,4}\b/g) || [];
	const boxMarkers = text.match(/box_2d|bbox|bounding box|\bymin\b|\bxmin\b|\bymax\b|\bxmax\b/gi) || [];
	const labelMarkers = text.match(/\blabel\b|\bpoint\b|\bcoordinate\b/gi) || [];
	const structuralMarks = (text.match(/[{}[\]]/g) || []).length;
	const alphaCount = (text.match(/[a-z]/gi) || []).length;
	const alphaRatio = text.length > 0 ? alphaCount / text.length : 0;
	return {
		length: text.length,
		coordinatePairCount: coordinatePairs.length,
		boxMarkerCount: boxMarkers.length,
		labelPointCoordinateCount: labelMarkers.length,
		structuralMarks,
		alphaRatio,
		rawDumpSuspected:
			text.length > 2500 ||
			coordinatePairs.length >= 8 ||
			boxMarkers.length >= 3 ||
			labelMarkers.length >= 8 ||
			structuralMarks > 20 ||
			(text.length > 250 && alphaRatio < 0.15)
	};
}

async function attachImage(page: any, log: (message: string, metadata?: Record<string, unknown>) => void) {
	const fileInput = page.locator('input[type="file"][multiple]');
	await expect(fileInput).toBeAttached({ timeout: 10000 });
	await fileInput.setInputFiles(IMAGE_FIXTURE);
	log('Attached image fixture.', { image: IMAGE_FIXTURE });

	const editorEmbed = page.getByTestId('message-editor').locator('[data-testid="embed-full-width-wrapper"]');
	await expect(editorEmbed.first()).toBeVisible({ timeout: 20000 });
	await page.waitForTimeout(5000);
	await closeEmbedFullscreenIfOpen(page, log);
}

async function closeEmbedFullscreenIfOpen(
	page: any,
	log: (message: string, metadata?: Record<string, unknown>) => void
) {
	const overlay = page.getByTestId('embed-fullscreen-overlay');
	if (!(await overlay.first().isVisible().catch(() => false))) {
		return;
	}
	await page.keyboard.press('Escape');
	if (await overlay.first().isVisible().catch(() => false)) {
		await overlay.getByRole('button', { name: /minimize|close/i }).first().click();
	}
	await expect(overlay).not.toBeVisible({ timeout: 10000 });
	log('Closed fullscreen overlay before sending.');
}

async function sendImageQuestion(
	page: any,
	message: string,
	log: (message: string, metadata?: Record<string, unknown>) => void
) {
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 10000 });
	await editor.click();
	await page.keyboard.type(message);
	log('Typed image question.', { message });

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled({ timeout: 30000 });
	await closeEmbedFullscreenIfOpen(page, log);
	await sendButton.click();
	log('Sent image question.');
}

async function waitForImageViewAndResponse(page: any, log: (message: string, metadata?: Record<string, unknown>) => void) {
	const imageViewEmbed = page.locator('[data-app-id="images"][data-skill-id="view"]').last();
	await expect(imageViewEmbed).toBeVisible({ timeout: 180000 });
	log('images.view embed is visible.');

	const assistantMessage = page.getByTestId('message-assistant').last();
	await expect(assistantMessage).toBeVisible({ timeout: 30000 });
	const generatedBy = assistantMessage.getByTestId('generated-by');
	await expect(generatedBy).toBeVisible({ timeout: 240000 });
	const generatedByText = (await generatedBy.textContent()) || '';
	const responseText = (await assistantMessage.textContent()) || '';
	return { generatedByText, responseText };
}

test.describe.configure({ mode: 'parallel' });

for (const model of activeModels) {
	for (const trial of activeTrials) {
		test(`real image inference ${model.label} trial ${trial}`, async ({ page }: { page: any }, testInfo: any) => {
			test.slow();
			test.setTimeout(420000);

			const { email, password, otpKey } = getTestAccount();
			skipWithoutCredentials(test, email, password, otpKey);

			const log = createSignupLogger(`IMAGE_MODEL_${model.label.toUpperCase()}_${trial}`);
			const screenshot = createStepScreenshotter(log, {
				filenamePrefix: `image-model-${model.label}-${trial}`
			});

			await archiveExistingScreenshots(log);
			await page.goto(getE2EDebugUrl('/'));
			await loginToTestAccount(page, log, screenshot);
			await startNewChat(page, log);
			await attachImage(page, log);

			const message = `${PROMPT} ${modelDirective(model)}`;
			await sendImageQuestion(page, message, log);
			const { generatedByText, responseText } = await waitForImageViewAndResponse(page, log);
			const score = scoreResponse(responseText);

			const artifact = {
				provider: model.provider,
				requestedModel: model.model,
				trial,
				expectsReroute: Boolean(model.expectsReroute),
				generatedByText,
				score,
				responseText
			};
			await testInfo.attach(`image-model-response-${model.label}-${trial}.json`, {
				body: JSON.stringify(artifact, null, 2),
				contentType: 'application/json'
			});
			console.log(`[IMAGE_MODEL_RESPONSE] ${JSON.stringify(artifact)}`);

			expect(generatedByText).toMatch(model.expectedGeneratedBy);
			if (model.expectsReroute) {
				expect(generatedByText).not.toMatch(/gemini|google/i);
			}
			expect(score.rawDumpSuspected, `response looked like a raw coordinate/label dump: ${responseText.slice(0, 500)}`).toBe(false);
			expect(responseText.toLowerCase()).toMatch(/design|recommend|improve|layout|spacing|interface|ui/);

			await deleteActiveChat(page, log, screenshot, `cleanup-${model.label}-${trial}`);
		});
	}
}
