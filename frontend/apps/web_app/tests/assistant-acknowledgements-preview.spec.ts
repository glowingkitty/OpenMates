/**
 * Verifies the manifest-backed assistant acknowledgement preview on dev.
 * Covers Spanish and French inventory, filtering, transcripts, and audio delivery.
 * Uses the existing preview page without authentication or product-state mutation.
 * Provides phone and laptop checkpoints for the required feature proof video.
 */

import { expect, test } from './helpers/cookie-audit';

// contract-test-file: tooling

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';

const ACKNOWLEDGEMENT_LOCALES_PROOF = defineVideoProof({
	id: 'assistant-acknowledgement-locales',
	title: 'Spanish and French assistant acknowledgements',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'spanish-library',
			text: 'Open the acknowledgement library and review the twelve Spanish clips for one mate.',
			checkpoint: 'spanish-library',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'french-library',
			text: 'Switch to French and confirm the translated acknowledgement variants are ready to play.',
			checkpoint: 'french-library',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'spanish-visible',
			checkpoint: 'spanish-library',
			visual: 'The language control selects es-ES and the page shows twelve Spanish clips for Hiro.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'french-visible',
			checkpoint: 'french-library',
			visual: 'The language control selects fr-FR and the page shows twelve French clips for Ace.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

test('Spanish and French acknowledgement libraries render and serve audio', async ({ page }, testInfo) => {
	const proof = createVideoProofRuntime(ACKNOWLEDGEMENT_LOCALES_PROOF, {
		device: PROOF_DEVICE,
		attach: testInfo.attach.bind(testInfo),
		captureFrame: () => page.screenshot({ type: 'png' })
	});
	const response = await page.goto(
		'/dev/preview/assistant-acknowledgements?language=es-ES&mate=hiro',
		{ waitUntil: 'networkidle' }
	);
	expect(response?.status()).toBe(200);

	const languageSelect = page.getByTestId('assistant-ack-language-select');
	await expect(languageSelect.getByRole('option')).toHaveCount(4);
	await proof.assert('spanish-visible', async () => {
		await expect(languageSelect).toHaveValue('es-ES');
		await expect(page.getByTestId('assistant-ack-selection-summary')).toContainText(
			'Showing 12 clips for es-ES / Hiro'
		);
		await expect(page.getByTestId('assistant-ack-clip-card')).toHaveCount(12);
		await expect(page.getByText('Claro, vamos a verlo.', { exact: true })).toBeVisible();
	});
	await proof.checkpoint('spanish-library');

	const spanishAudio = await page.request.get(
		'/audio/assistant-acknowledgements/hiro/es-ES/general-1.mp3'
	);
	expect(spanishAudio.status()).toBe(200);
	expect(spanishAudio.headers()['content-type']).toContain('audio/mpeg');

	await proof.action('switch-to-french', () => languageSelect.selectOption('fr-FR'));
	await proof.assert('french-visible', async () => {
		await expect(languageSelect).toHaveValue('fr-FR');
		await expect(page.getByTestId('assistant-ack-selection-summary')).toContainText(
			'Showing 12 clips for fr-FR / Ace'
		);
		await expect(page.getByTestId('assistant-ack-clip-card')).toHaveCount(12);
		await expect(page.getByText('Bien sûr, regardons ça.', { exact: true })).toBeVisible();
	});
	await proof.checkpoint('french-library');

	const frenchAudio = await page.request.get(
		'/audio/assistant-acknowledgements/ace/fr-FR/general-1.mp3'
	);
	expect(frenchAudio.status()).toBe(200);
	expect(frenchAudio.headers()['content-type']).toContain('audio/mpeg');
	await proof.attach();
});
