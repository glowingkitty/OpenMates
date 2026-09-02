/**
 * Focused deployed proof for the Figma-defined assistant speech player.
 * Uses the isolated component preview before the broader encrypted chat flow.
 * Verifies responsive hierarchy, chapter loading, waveform transition, and controls.
 * Network generation and billing remain covered by assistant-response-speech.spec.ts.
 */

import { expect, test } from './helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_WIDTH === 390 ? 'web-phone' : 'web-laptop';

const PLAYER_PROOF = defineVideoProof({
	id: 'assistant-speech-player-component',
	title: 'Assistant speech player component',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'playing', text: 'The responsive player shows Sophia, a waveform, and named response chapters.', checkpoint: 'playing', devices: ['web-laptop', 'web-phone'] },
		{ id: 'pending', text: 'Selecting a pending chapter switches immediately to Loading and a flat placeholder waveform.', checkpoint: 'pending', devices: ['web-laptop', 'web-phone'] },
		{ id: 'ready', text: 'When audio becomes ready, real waveform bars transition into place and playback resumes.', checkpoint: 'ready', devices: ['web-laptop', 'web-phone'] },
		{ id: 'paused', text: 'Pausing reveals separate Play and Close controls without hiding chapter navigation.', checkpoint: 'paused', devices: ['web-laptop', 'web-phone'] }
	],
	assertions: [
		{ id: 'assistant-speech.playback.pinned-full-response-waveform', checkpoint: 'playing', visual: 'The rounded speech-accent player follows the Figma hierarchy without clipping.', devices: ['web-laptop', 'web-phone'] },
		{ id: 'assistant-speech.playback.two-second-idle-grace', checkpoint: 'pending', visual: 'The selected pending chapter is current with Loading and a flat waveform.', devices: ['web-laptop', 'web-phone'] },
		{ id: 'assistant-speech.playback.deterministic-chapter-labels', checkpoint: 'ready', visual: 'The selected named chapter retains focus as ready waveform samples replace the flat placeholder and playback starts.', devices: ['web-laptop', 'web-phone'] },
		{ id: 'assistant-speech.playback.single-queue-segment-control', checkpoint: 'paused', visual: 'Paused playback exposes distinct Play and Close controls.', devices: ['web-laptop', 'web-phone'] }
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

test.describe('AssistantSpeechPlayer component preview', () => {
	// contract-test: direct surface=gui.web assertions=assistant-speech.playback.single-queue-segment-control,assistant-speech.playback.deterministic-chapter-labels,assistant-speech.playback.pinned-full-response-waveform,assistant-speech.playback.two-second-idle-grace
	test('matches responsive playing, loading, ready, and paused states', async ({ page }, testInfo) => {
		const proof = createVideoProofRuntime(PLAYER_PROOF, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo)
		});
		const width = PROOF_DEVICE === 'web-phone' ? '381' : '1155';
		await page.goto(`/dev/preview/AssistantSpeechPlayer?theme=light&chrome=0&width=${width}`, { waitUntil: 'networkidle' });
		await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true');

		const player = page.getByTestId('assistant-speech-player');
		await proof.assert('assistant-speech.playback.pinned-full-response-waveform', async () => {
			await expect(player).toBeVisible();
			await expect(player).toHaveAttribute('data-presentation', 'replayable_track_queue');
			await expect(player.getByTestId('assistant-speech-current-chapter')).toHaveText('Key considerations');
			await expect(player.getByTestId('assistant-speech-previous-chapter')).toContainText('Short answer');
			await expect(player.getByTestId('assistant-speech-next-chapter')).toContainText('Optimization');
			await expect(player.getByTestId('assistant-speech-waveform')).toHaveAttribute('data-segment-id', 'segment-1');
			await expect(player.getByTestId('assistant-speech-waveform')).toHaveAttribute('data-window', 'segment-0,segment-1,segment-2');
			await expect(player.getByTestId('assistant-speech-waveform-region')).toHaveCount(3);
			await expect(player.getByTestId('assistant-speech-primary-control')).toHaveAccessibleName('Pause voice response');
			await expect(player.getByTestId('assistant-speech-primary-icon')).toHaveAttribute('data-icon', 'pause');
			await expect(player.getByTestId('assistant-speech-waveform-bar')).not.toHaveCount(0);
			if (PROOF_DEVICE === 'web-laptop') {
				await expect(player.getByTestId('assistant-speech-mate')).toBeVisible();
				await expect(player.getByTestId('assistant-speech-mate')).toHaveAttribute('data-mate-category', 'software_development');
				await expect.poll(() => player.getByTestId('assistant-speech-mate').evaluate((element) => getComputedStyle(element).backgroundImage)).not.toBe('none');
			}
		});
		await proof.checkpoint('playing');

		await proof.action('select-pending-chapter', async () => player.getByTestId('assistant-speech-next-chapter').click());
		await proof.assert('assistant-speech.playback.deterministic-chapter-labels', async () => {
			await expect(player.getByTestId('assistant-speech-current-chapter')).toHaveText('Optimization');
			await expect(player.getByTestId('assistant-speech-loading')).toBeVisible();
			await expect(player.getByTestId('assistant-speech-waveform')).toHaveAttribute('data-placeholder', 'true');
			await expect(player.getByTestId('assistant-speech-waveform')).toHaveAttribute('data-segment-id', 'segment-2');
			await expect(player.getByTestId('assistant-speech-waveform')).toHaveAttribute('data-window', 'segment-1,segment-2');
			await expect(player.getByTestId('assistant-speech-waveform-region')).toHaveCount(2);
		});
		await proof.checkpoint('pending');

		await proof.action('wait-for-ready-audio', async () => {
			await expect(player.getByTestId('assistant-speech-waveform')).toHaveAttribute('data-placeholder', 'false', { timeout: 5_000 });
		});
		await proof.assert('assistant-speech.playback.two-second-idle-grace', async () => {
			await expect(player.getByTestId('assistant-speech-primary-control')).toHaveAccessibleName('Pause voice response');
		});
		await proof.checkpoint('ready');

		await proof.action('pause-playback', async () => player.getByTestId('assistant-speech-primary-control').click());
		await proof.assert('assistant-speech.playback.single-queue-segment-control', async () => {
			await expect(player.getByTestId('assistant-speech-primary-control')).toHaveAccessibleName('Play voice response');
			await expect(player.getByTestId('assistant-speech-primary-icon')).toHaveAttribute('data-icon', 'play');
			await expect(player.getByTestId('assistant-speech-close')).toBeVisible();
			await expect(player.getByTestId('assistant-speech-close-icon')).toBeVisible();
		});
		await proof.checkpoint('paused');
		await proof.attach();
	});
});
