/* eslint-disable @typescript-eslint/no-require-imports */
// contract-test-file: infrastructure
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
const fs = require('fs');
const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	deleteActiveChat,
	waitForChatReady,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const IMAGE_FIXTURE = path.resolve(
	__dirname,
	'../../../../docs/images/architecture/messaging/messageinputfield/large_message.jpg'
);

const PROMPT = 'Evaluate the design and give recommendations for improvements.';
const DESIGN_FEEDBACK_PATTERN = /design|recommend|improve|layout|spacing|interface|ui/i;
const TRIALS = [1, 2, 3];
const DEFAULT_SMOKE_MODEL_LABELS = ['gemini-36-flash'];
const IMAGE_VIEW_TIMEOUT_MS = 180000;
const ASSISTANT_MESSAGE_START_TIMEOUT_MS = 180000;
const ASSISTANT_COMPLETION_TIMEOUT_MS = 240000;

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
		expectedGeneratedBy: /Claude Haiku 4\.5|claude-haiku-4-5-20251001/i,
		expectsReroute: true
	},
	{
		provider: 'google',
		model: 'gemini-3.7-flash',
		label: 'gemini-36-flash',
		expectedGeneratedBy: /Claude Haiku 4\.5|claude-haiku-4-5-20251001/i,
		expectsReroute: true
	},
	{
		provider: 'google',
		model: 'gemini-3.5-flash',
		label: 'gemini-35-flash',
		expectedGeneratedBy: /Claude Haiku 4\.5|claude-haiku-4-5-20251001/i,
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
	// Avoid reusing stale duplicate upload rows for this shared fixture hash.
	const uniqueSuffix = `\nopenmates-e2e-${Date.now()}-${Math.random()}`;
	const imageBuffer = Buffer.concat([fs.readFileSync(IMAGE_FIXTURE), Buffer.from(uniqueSuffix)]);
	await fileInput.setInputFiles({
		name: 'large_message_e2e.jpg',
		mimeType: 'image/jpeg',
		buffer: imageBuffer
	});
	log('Attached image fixture.', { image: IMAGE_FIXTURE });

	const editor = page.getByTestId('message-editor');
	const editorEmbed = editor.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="image"]');
	const editorPreview = editorEmbed.locator(
		'[data-testid="embed-preview"][data-app-id="images"][data-skill-id="view"]'
	);
	await expect(editorEmbed.first()).toBeVisible({ timeout: 20000 });
	// The upload-ready state is owned by the mounted UnifiedEmbedPreview. The
	// TipTap NodeView wrapper can be recreated while upload attrs propagate, so
	// wait on the preview's canonical data-status instead of the wrapper attr.
	await expect(editorPreview.first()).toHaveAttribute('data-status', 'finished', { timeout: 120000 });
	await closeEmbedFullscreenIfOpen(page, log);
	await page.keyboard.press('Escape');
	await editor.press('End');
	log('Image upload finished and editor cursor moved after embed.');
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
		await overlay.getByTestId('embed-minimize').first().dispatchEvent('click');
	}
	await expect(overlay).not.toBeVisible({ timeout: 10000 });
	log('Closed fullscreen overlay before sending.');
}

async function typePromptAndSendAfterAttachment(
	page: any,
	message: string,
	log: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
) {
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 10000 });
	await page.keyboard.press('Escape');
	await editor.press('End');
	await page.keyboard.type(message);
	log(`Typed message after image embed: "${message}"`);
	await takeStepScreenshot(page, `${stepLabel}-message-typed`);

	const userMessages = page.getByTestId('message-user');
	const assistantMessages = page.getByTestId('message-assistant');
	const userCountBeforeSend = await userMessages.count().catch(() => 0);
	const assistantCountBeforeSend = await assistantMessages.count().catch(() => 0);
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 10000 });
	await page.keyboard.press('Escape');
	await sendButton.click({ timeout: 10000 });
	log('Clicked send button after image upload.');

	await expect
		.poll(
			async () => {
				const userCount = await userMessages.count().catch(() => 0);
				const assistantCount = await assistantMessages.count().catch(() => 0);
				return userCount > userCountBeforeSend || assistantCount > assistantCountBeforeSend;
			},
			{ timeout: 60000, intervals: [1000, 2000, 5000] }
		)
		.toBeTruthy();
	log('Message send accepted after attachment-preserving send.', { assistantCountBeforeSend });
}

async function waitForImageViewAndResponse(page: any, log: (message: string, metadata?: Record<string, unknown>) => void) {
	const imageViewEmbed = page.locator('[data-app-id="images"][data-skill-id="view"]').last();
	await expect(imageViewEmbed).toBeVisible({ timeout: IMAGE_VIEW_TIMEOUT_MS });
	log('images.view embed is visible.');

	const assistantMessage = await waitForAssistantMessage(page, {
		which: 'last',
		contains: DESIGN_FEEDBACK_PATTERN,
		timeout: ASSISTANT_COMPLETION_TIMEOUT_MS,
		logCheckpoint: log
	});
	const generatedBy = assistantMessage.getByTestId('generated-by');
	await expect(generatedBy).toBeVisible({ timeout: ASSISTANT_MESSAGE_START_TIMEOUT_MS });
	const generatedByText = (await generatedBy.textContent()) || '';
	const responseText = (await assistantMessage.textContent()) || '';
	return { generatedByText, responseText };
}

test.describe.configure({ mode: 'serial' });

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
			await waitForChatReady(page, log, 90000);
			await attachImage(page, log);

			const message = `${PROMPT} ${modelDirective(model)}`;
			await closeEmbedFullscreenIfOpen(page, log);
			await typePromptAndSendAfterAttachment(page, message, log, screenshot, `image-question-${model.label}-${trial}`);
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
			expect(responseText).toMatch(DESIGN_FEEDBACK_PATTERN);

			await deleteActiveChat(page, log, screenshot, `cleanup-${model.label}-${trial}`);
		});
	}
}
