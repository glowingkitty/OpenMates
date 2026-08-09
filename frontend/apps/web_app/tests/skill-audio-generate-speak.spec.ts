/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Deployed web verification for audio.generate and audio.speak.
 *
 * The CLI creates real authenticated chats with generated-audio app-skill embeds.
 * The browser then opens those chats and verifies preview/fullscreen playback,
 * which covers the Svelte routing path without relying on web-composer steering.
 * Real provider generation is opt-in to avoid accidental ElevenLabs spend.
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getE2EDebugUrl,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { deriveApiUrl, expectCliSuccess, parseCliJson, runCli } = require('./helpers/cli-test-helpers');
const { closeFullscreen, openFullscreen, waitForEmbedFinished } = require('./helpers/embed-test-helpers');

const RUN_REAL_AUDIO_GENERATION = process.env.OPENMATES_RUN_AUDIO_GENERATION_TESTS === 'true';
const CHAT_RESPONSE_TIMEOUT_ARGS = ['--response-timeout-seconds', '300'];
const REAL_AUDIO_CHAT_TIMEOUT_MS = 420_000;
const WEB_EMBED_TIMEOUT_MS = 240_000;

type AudioSkillId = 'generate' | 'speak';

test.describe.serial('App: Audio / Skills: generate + speak', () => {
	test.setTimeout(900_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// contract-test: supporting surface=rest_api assertions=audio-generate.surface-parity,audio-speak.surface-parity
	test('Phase 0: Apps metadata exposes audio generate and speak', async ({ request }: { request: any }) => {
		const response = await request.get(`${apiUrl}/v1/apps/metadata`);
		expect(response.ok()).toBeTruthy();

		const data = await response.json();
		const audio = data.apps?.audio;
		expect(audio, 'audio app should appear in Apps metadata').toBeTruthy();

		const skillIds = (audio.skills || []).map((skill: { id: string }) => skill.id);
		expect(skillIds).toContain('generate');
		expect(skillIds).toContain('speak');
	});

	// contract-test: direct surface=gui.web assertions=audio-generate.output.playable-audio,audio-speak.output.playable-audio,audio-generate.output.binary-excluded-from-inference,audio-speak.output.binary-excluded-from-inference,audio-generate.surface-parity,audio-speak.surface-parity
	test('Phase 1: deployed web renders playable generated-audio previews and fullscreens', async ({ page }: { page: any }) => {
		test.slow();
		test.skip(!RUN_REAL_AUDIO_GENERATION, 'Set OPENMATES_RUN_AUDIO_GENERATION_TESTS=true to run ElevenLabs web rendering proof.');
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'OPENMATES_TEST_ACCOUNT_API_KEY required.');
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-audio-generate-speak');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);
		const createdChatIds: string[] = [];

		try {
			const generateChatId = await createAudioChat(
				apiUrl,
				'generate',
				'Use audio.generate with provider elevenlabs to create a 1 second non-speech soft UI success chime. Do not use speech or music.'
			);
			createdChatIds.push(generateChatId);
			logCheckpoint('Created CLI chat for audio.generate.', { chatId: generateChatId });

			const speakChatId = await createAudioChat(
				apiUrl,
				'speak',
				'Use audio.speak with provider elevenlabs to read aloud exactly this short sentence: OpenMates audio playback is working.'
			);
			createdChatIds.push(speakChatId);
			logCheckpoint('Created CLI chat for audio.speak.', { chatId: speakChatId });

			await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);

			await verifyAudioChat(page, generateChatId, 'generate', logCheckpoint, takeStepScreenshot);
			await verifyAudioChat(page, speakChatId, 'speak', logCheckpoint, takeStepScreenshot);
		} finally {
			for (const chatId of createdChatIds) {
				await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 30_000).catch(() => undefined);
			}
		}
	});
});

async function createAudioChat(apiUrl: string, skillId: AudioSkillId, message: string): Promise<string> {
	const result = await runCli(
		apiUrl,
		['chats', 'new', message, '--json', ...CHAT_RESPONSE_TIMEOUT_ARGS],
		REAL_AUDIO_CHAT_TIMEOUT_MS
	);
	expectCliSuccess(result, `CLI chat audio.${skillId}`);

	const parsed = parseCliJson(result);
	const chatId = String(parsed.chat_id || parsed.chatId || parsed.data?.chat_id || '');
	expect(chatId, `CLI chat audio.${skillId} should return a chat_id`).toBeTruthy();
	return chatId;
}

async function verifyAudioChat(
	page: any,
	chatId: string,
	skillId: AudioSkillId,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`), { waitUntil: 'domcontentloaded' });
	await expect(page).toHaveURL(new RegExp(`chat-id=${escapeRegExp(chatId)}`), { timeout: 60_000 });
	logCheckpoint(`Opened audio.${skillId} chat in web app.`, { chatId });

	const embed = await waitForEmbedFinished(page, 'audio', skillId, WEB_EMBED_TIMEOUT_MS);
	await expect(embed.getByTestId(`audio-${skillId}-preview`)).toBeVisible({ timeout: 15_000 });
	const previewAudio = embed.getByTestId(`audio-${skillId}-audio`);
	await expect(previewAudio).toBeVisible({ timeout: 60_000 });
	await expectAudioCanPlay(previewAudio, `audio.${skillId} preview audio`);
	await assertNoVisibleSensitiveAudioPayload(page, `audio.${skillId} preview`);
	await takeStepScreenshot(page, `audio-${skillId}-preview-finished`);

	const fullscreen = await openFullscreen(page, embed);
	await expect(fullscreen.getByTestId(`audio-${skillId}-fullscreen`)).toBeVisible({ timeout: 15_000 });
	const fullscreenAudio = fullscreen.getByTestId(`audio-${skillId}-fullscreen-audio`);
	await expect(fullscreenAudio).toBeVisible({ timeout: 60_000 });
	await expectAudioCanPlay(fullscreenAudio, `audio.${skillId} fullscreen audio`);
	await assertNoVisibleSensitiveAudioPayload(page, `audio.${skillId} fullscreen`);
	await closeFullscreen(page, fullscreen);
}

async function expectAudioCanPlay(audioLocator: any, label: string): Promise<void> {
	await expect(async () => {
		const state = await audioLocator.evaluate(async (audio: HTMLAudioElement) => {
			audio.muted = true;
			await audio.play();
			await new Promise((resolve) => setTimeout(resolve, 1200));
			const result = {
				paused: audio.paused,
				currentTime: audio.currentTime,
				duration: audio.duration,
				readyState: audio.readyState
			};
			audio.pause();
			return result;
		});

		expect(state.readyState, `${label} should load audio metadata`).toBeGreaterThanOrEqual(1);
		expect(Number.isFinite(state.duration), `${label} should have finite duration`).toBe(true);
		expect(state.duration, `${label} should have non-zero duration`).toBeGreaterThan(0);
		expect(state.currentTime, `${label} should advance during playback`).toBeGreaterThan(0);
	}).toPass({ timeout: 30_000 });
}

async function assertNoVisibleSensitiveAudioPayload(page: any, label: string): Promise<void> {
	const visibleText = await page.locator('body').innerText({ timeout: 10_000 });
	expect(visibleText, `${label} must not expose raw audio bytes`).not.toMatch(/audio_base64|data:audio\//i);
	expect(visibleText, `${label} must not expose encryption fields`).not.toMatch(/aes_key|aes_nonce|vault_wrapped/i);
	expect(visibleText, `${label} must not expose safeguard internals`).not.toMatch(/safeguard.*diagnostic/i);
}

function escapeRegExp(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
