import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
test('recording overlay keeps only its latest wrapped transcript line visible on mobile', async ({
	page
}) => {
	await page.goto(
		'/dev/preview/enter_message/RecordAudio?variant=longTranscript&theme=dark&background=%23181818&width=390&chrome=0'
	);
	await waitForComponentPreview(page);

	const overlay = page.getByTestId('record-overlay');
	const header = overlay.getByTestId('release-text');
	const transcript = header.getByTestId('recording-live-transcript');
	const transcriptFlow = transcript.getByTestId('recording-live-transcript-flow');
	await expect(overlay).toBeVisible();
	await expect(transcript).toContainText('The latest spoken sentence remains visible here.');
	await expect
		.poll(async () => Number(await transcript.getAttribute('data-line-count')))
		.toBeGreaterThan(1);
	await expect(header).not.toContainText('Recording');
	await expect(overlay.getByTestId('record-shortcuts')).toBeVisible();
	await expect(overlay.getByTestId('recording-waveform')).toBeVisible();
	await expect(overlay.getByTestId('record-controls')).toBeVisible();

	const [overlayBox, headerBox, transcriptBox, transcriptFlowBox, controlsBox] = await Promise.all([
		overlay.boundingBox(),
		header.boundingBox(),
		transcript.boundingBox(),
		transcriptFlow.boundingBox(),
		overlay.getByTestId('record-controls').boundingBox()
	]);
	expect(overlayBox).not.toBeNull();
	expect(headerBox).not.toBeNull();
	expect(transcriptBox).not.toBeNull();
	expect(transcriptFlowBox).not.toBeNull();
	expect(controlsBox).not.toBeNull();
	expect(headerBox!.x).toBeGreaterThanOrEqual(overlayBox!.x);
	expect(headerBox!.x + headerBox!.width).toBeLessThanOrEqual(overlayBox!.x + overlayBox!.width);
	expect(headerBox!.y + headerBox!.height).toBeLessThan(controlsBox!.y);
	expect(transcriptBox!.height).toBeLessThan(transcriptFlowBox!.height);
	await expect(transcriptFlow).not.toHaveCSS('transform', 'none');
	await expect(transcriptFlow).toHaveCSS('transition-duration', '0.22s');
});
