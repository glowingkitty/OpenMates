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
	await expect(transcriptFlow).toHaveCSS('transition-duration', '0s');
});

for (const width of [1155, 768, 390]) {
  // contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle,message-input.audio.single-line-preview
  test(`long recording shows exactly the newest transcript line at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width: Math.max(width + 40, 430), height: 900 });
    await page.goto(`/dev/preview/enter_message/RecordAudio?variant=veryLongTranscript&theme=dark&background=%23181818&width=${width}&chrome=0`);
    await waitForComponentPreview(page);
    const overlay = page.getByTestId('record-overlay');
    const transcript = overlay.getByTestId('recording-live-transcript');
    const flow = transcript.getByTestId('recording-live-transcript-flow');
    await expect(overlay).toBeVisible();
    await expect(transcript).toContainText('The newest words must remain fully readable.');
    await expect.poll(async () => Number(await transcript.getAttribute('data-line-count'))).toBeGreaterThan(2);
    await expect(flow).toHaveCSS('transition-duration', '0s');
    await expect(transcript).toHaveCSS('overflow', 'hidden');
    const assertOneCompleteLine = async () => {
      await expect.poll(async () => transcript.evaluate((element) => {
        const flow = element.querySelector('[data-testid="recording-live-transcript-flow"]')!;
        const viewport = element.getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(flow);
        const visible = [...range.getClientRects()].filter(rect => rect.bottom > viewport.top + 0.75 && rect.top < viewport.bottom - 0.75);
        return visible.length === 1
          && visible[0].top >= viewport.top - 0.75
          && visible[0].bottom <= viewport.bottom + 0.75
          && Math.abs(viewport.height - Number.parseFloat(getComputedStyle(flow).lineHeight)) < 0.75
          && Math.abs(flow.getBoundingClientRect().bottom - viewport.bottom) < 0.75;
      })).toBe(true);
    };
    await assertOneCompleteLine();
    // Width reflow must recalculate the last line without a two-line animation.
    await page.setViewportSize({ width: Math.max(430, width - 120), height: 900 });
    await assertOneCompleteLine();
    for (const id of ['record-shortcuts', 'recording-waveform', 'record-controls']) {
      await expect(overlay.getByTestId(id)).toBeVisible();
    }
  });
}
