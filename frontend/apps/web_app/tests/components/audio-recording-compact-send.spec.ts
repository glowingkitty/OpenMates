// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import type { Locator, Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
import { allowFixtureMicrophone } from '../helpers/recording-permission';

const RAW_TRANSCRIPT = 'please schedule the project review';
const CORRECTED_TRANSCRIPT = 'Please schedule the project review.';

test.use({
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['microphone'],
});

async function openRecording(page: Page, width: number, variant: string, options: { draftText?: string; imageDraft?: boolean } = {}) {
  await allowFixtureMicrophone(page, /\/dev\/preview\/enter_message\/MessageInput(?:RecordingDraftPreviewHarness)?(?:\?|$)/);
  await page.setViewportSize({ width: width < 400 ? 390 : 1280, height: 844 });
  await page.addInitScript(() => sessionStorage.setItem('ws_token', 'synthetic-preview-token'));
  let releaseCorrection: (() => void) | null = null;
  let emitDelta: ((text: string) => void) | null = null;
  await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, socket => {
    socket.send(JSON.stringify({ type: 'session.ready', sample_rate: 16000 }));
    emitDelta = text => socket.send(JSON.stringify({ type: 'transcription.text.delta', text }));
    let hasTranscript = false;
    socket.onMessage(rawMessage => {
      const message = JSON.parse(String(rawMessage));
      if (message.type === 'input_audio.append' && !hasTranscript) {
        hasTranscript = true;
        socket.send(JSON.stringify({ type: 'transcription.text.delta', text: RAW_TRANSCRIPT }));
      }
      if (message.type !== 'input_audio.end') return;
      socket.send(JSON.stringify({ type: 'transcription.done', model: 'synthetic-realtime' }));
      socket.send(JSON.stringify({ type: 'correction.started', model: 'synthetic-correction' }));
      releaseCorrection = () => socket.send(JSON.stringify({ type: 'correction.done', transcript: CORRECTED_TRANSCRIPT }));
    });
  });
  const params = new URLSearchParams({ variant, width: String(width), theme: width < 400 ? 'dark' : 'light', background: '#dbeafe', chrome: '0' });
  const component = options.imageDraft ? 'MessageInputRecordingDraftPreviewHarness' : 'MessageInput';
  await page.goto(`/dev/preview/enter_message/${component}?${params}`);
  await waitForComponentPreview(page);
  if (options.imageDraft) await expect(page.getByTestId('recording-draft-fixture')).toHaveAttribute('data-ready', 'true');
  const field = options.imageDraft
    ? page.getByTestId('recording-draft-composer').getByTestId('message-field')
    : page.getByTestId('message-field');
  await expect(field).toHaveAttribute('data-editor-ready', 'true');
  const editor = page.getByTestId('message-editor').locator('.ProseMirror');
  await editor.focus();
  if (!options.imageDraft) await editor.fill(options.draftText ?? 'Existing notes. ');
  await editor.press('ControlOrMeta+End');
  await expect(field).toHaveAttribute('data-focused', 'true');
  expect(await page.evaluate(async () => (await navigator.permissions.query({ name: 'microphone' as PermissionName })).state)).toBe('granted');
  if (options.imageDraft && width >= 680) {
    await page.keyboard.press('ControlOrMeta+Shift+M');
    await expect(page.locator('html')).toHaveAttribute('data-recording-shortcut-active', 'true');
  } else {
    await field.getByTestId('record-audio-button').dispatchEvent('mousedown', { button: 0 });
  }
  const overlay = page.getByTestId('record-overlay');
  // Dictation streams into the editor itself; the compact overlay shows no text preview.
  await expect(editor).toContainText(RAW_TRANSCRIPT);
  await expect(overlay.getByTestId('recording-live-transcript')).toHaveCount(0);
  return { field, editor, overlay, emit: (text: string) => emitDelta!(text), release: async () => {
    await expect.poll(() => releaseCorrection !== null).toBe(true);
    releaseCorrection!();
  } };
}

async function expectContained(overlay: Locator, controls: Locator[]) {
  const outer = (await overlay.boundingBox())!;
  let previousRight = outer.x;
  for (const control of controls) {
    await expect(control).toBeVisible();
    const box = (await control.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(previousRight);
    expect(box.y).toBeGreaterThanOrEqual(outer.y);
    expect(box.x + box.width).toBeLessThanOrEqual(outer.x + outer.width);
    expect(box.y + box.height).toBeLessThanOrEqual(outer.y + outer.height);
    previousRight = box.x + box.width;
  }
}

async function expectCentered(overlay: Locator, content: Locator) {
  await expect(content).toBeVisible();
  const outer = (await overlay.boundingBox())!;
  const inner = (await content.boundingBox())!;
  expect(Math.abs(inner.x + inner.width / 2 - outer.x - outer.width / 2)).toBeLessThan(1);
}

for (const { width, variant, compactHeight, phase } of [
  { width: 330, variant: 'recordingInline', compactHeight: 48, phase: 'recording' },
  { width: 680, variant: 'recording', compactHeight: 60, phase: 'recording' },
  { width: 330, variant: 'recording', compactHeight: 60, phase: 'correction' },
  { width: 680, variant: 'recordingInline', compactHeight: 48, phase: 'correction' },
]) {
  // contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.audio.live-editor-transcript,message-input.layout.responsive-parity,message-input.recording.lifecycle
  test(`recording and Send during ${phase} show dictation above the ${compactHeight}px ${width}px controls`, async ({ page }) => {
    test.setTimeout(60000);
    const { field, editor, overlay } = await openRecording(page, width, variant, { draftText: '' });
    // The first dictated words expand an empty composer to show the full draft.
    await expect(field).toHaveCSS('height', '180px');
    await expect(overlay).toHaveCSS('height', `${compactHeight}px`);
    await expect(editor).toHaveText(RAW_TRANSCRIPT);
    await expect(field).toHaveAttribute('data-focused', 'false');
    const cancel = overlay.getByTestId('record-cancel-button');
    const finish = overlay.getByTestId('record-finish-button');
    const send = overlay.getByTestId('record-send-button');
    await expect(cancel).toHaveAccessibleName('Cancel');
    await expect(overlay.getByTestId('record-cancel-icon')).toBeVisible();
    await expect(overlay.getByTestId('record-cancel-icon')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    await expect(overlay.getByTestId('record-cancel-icon')).not.toHaveCSS('mask-image', 'none');
    await expect(finish).toHaveAccessibleName('Finish');
    await expect(finish).toHaveCSS('width', '40px');
    await expect(finish).toHaveCSS('background-color', await cancel.evaluate(element => getComputedStyle(element).backgroundColor));
    const stopIcon = overlay.getByTestId('record-finish-icon');
    await expect(stopIcon).toBeVisible();
    await expect(stopIcon).toHaveCSS('width', '16px');
    await expect(stopIcon).toHaveCSS('height', '16px');
    await expect(stopIcon).toHaveCSS('border-radius', '4px');
    await expect(stopIcon).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    const waveform = overlay.getByTestId('recording-waveform');
    const preview = waveform;
    await expect(overlay.getByTestId('recording-live-transcript')).toHaveCount(0);
    if (width < 400) {
      await expect(waveform).toHaveCSS('mask-image', /linear-gradient\(to right,\s*rgba\([^)]*,\s*0\),\s*rgb\(/);
      await expect(cancel).toHaveCSS('mask-image', 'none');
      await test.info().attach('compact-waveform-left-fade', {
        body: await overlay.screenshot(), contentType: 'image/png',
      });
    }
    await expect(overlay.getByTestId('release-text')).toHaveCSS('text-align', 'center');
    await expectCentered(overlay, preview);
    await expectContained(overlay, [cancel, preview, finish, send]);
    if (phase === 'correction') {
      await finish.click();
      await expect(overlay).toHaveAttribute('data-recording-processing', 'true');
      await expect(field).toHaveCSS('height', '180px');
      await expect(editor.getByTestId('recording-transcript-processing')).toHaveText(RAW_TRANSCRIPT);
      await expect(editor).not.toBeFocused();
      await expect(send).toBeEnabled();
    }
    await send.click();
    await expect(field).toHaveCSS('height', '180px');
    await expect(overlay).toHaveCSS('height', `${compactHeight}px`);
    // The dictated text sweeps a gradient above the still-colored recording controls.
    const processingText = editor.getByTestId('recording-transcript-processing');
    await expect(processingText).toHaveText(RAW_TRANSCRIPT);
    await expect(processingText).toHaveCSS('animation-name', 'processing-text-shimmer');
    await expect(overlay).toHaveCSS('background-image', /linear-gradient/);
    await expect(overlay).toHaveAttribute('data-recording-processing', 'true');
    await expect(overlay.getByTestId('recording-live-transcript')).toHaveCount(0);
    await expect(overlay.getByTestId('recording-waveform')).toHaveCount(0);
    for (const id of ['timer-pill', 'record-finish-button', 'record-send-button']) {
      await expect(overlay.getByTestId(id)).toBeHidden();
    }
    const status = overlay.getByTestId('recording-processing-text');
    await expect(status).toHaveText('Improving transcript…');
    await expectCentered(overlay, status);
    await expectContained(overlay, [cancel, status]);
    await expect(status).toHaveText('Removing filler words…', { timeout: 4000 });
    await expectCentered(overlay, status);
    await expectContained(overlay, [cancel, status]);
    await expect(status).toHaveText('Making it more concise…', { timeout: 4000 });
    await expectCentered(overlay, status);
    await expectContained(overlay, [cancel, status]);
    await cancel.hover();
    await cancel.focus();
    await expect(cancel).toBeFocused();
    await cancel.press('Enter');
    await expect(overlay).toHaveCount(0);
    // Cancel discards the unedited dictation.
    await expect(editor).toHaveText('');
    await field.click();
    await expect(editor).toBeFocused();
    await expect(editor).toHaveText('');
  });
}

for (const { width, variant, height } of [
  { width: 330, variant: 'recordingInline', height: 48 },
  { width: 680, variant: 'recording', height: 60 },
]) {
  // contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.audio.live-editor-transcript,message-input.layout.responsive-parity,message-input.recording.lifecycle
  test(`Finish on the ${width}px composer shimmers dictated text until correction replaces it`, async ({ page }) => {
    test.setTimeout(60000);
    const { field, editor, overlay, release } = await openRecording(page, width, variant);
    await expect(field).toHaveCSS('height', '180px');
    await expect(overlay).toHaveCSS('height', `${height}px`);
    await expect(editor).toBeVisible();
    await expect(editor).toHaveText(`Existing notes. ${RAW_TRANSCRIPT}`);
    const finish = overlay.getByTestId('record-finish-button');
    await finish.hover();
    await finish.focus();
    await expect(finish).toBeFocused();
    await finish.press('Enter');
    await expect(overlay).toHaveAttribute('data-recording-processing', 'true');
    await expect(field).toHaveCSS('height', '180px');
    await expectCentered(overlay, overlay.getByTestId('recording-processing-text'));
    await expect(editor.getByTestId('recording-transcript-processing')).toHaveText(RAW_TRANSCRIPT);
    await expect(editor).not.toBeFocused();
    await release();
    await expect(overlay).toHaveCount(0);
    await expect(field).toHaveCSS('height', '180px');
    await expect(field).toHaveAttribute('data-focused', 'true');
    await expect(editor).toBeFocused();
    await expect(editor).toHaveText(`Existing notes. ${CORRECTED_TRANSCRIPT}`);
    await expect(editor.getByTestId('recording-transcript-processing')).toHaveCount(0);
    await page.keyboard.type(' Edited before sending.');
    await expect(editor).toContainText('Edited before sending.');
  });
}

for (const { width, variant, includeNotes } of [
  { width: 330, variant: '', includeNotes: true },
  { width: 680, variant: '', includeNotes: true },
  { width: 330, variant: 'imageOnly', includeNotes: false },
]) {
  // contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.send.ownership,message-input.layout.responsive-parity,message-input.recording.lifecycle
  test(`${width}px ${includeNotes ? 'text and image' : 'image-only'} draft stays visible while recording and viewing its image`, async ({ page }) => {
    test.setTimeout(60000);
    const { field, editor, overlay, release } = await openRecording(page, width, variant, { imageDraft: true });
    const fixture = page.getByTestId('recording-draft-fixture');
    const scroll = field.locator('.scrollable-content');
    await expect(editor).toBeVisible();
    expect((await field.boundingBox())!.height).toBeGreaterThanOrEqual(180);
    await expect(overlay).toHaveCSS('height', '60px');
    const fieldBox = (await field.boundingBox())!;
    const overlayBox = (await overlay.boundingBox())!;
    const scrollBox = (await scroll.boundingBox())!;
    expect(Math.abs(overlayBox.y + overlayBox.height - fieldBox.y - fieldBox.height)).toBeLessThan(1);
    expect(scrollBox.y + scrollBox.height).toBeLessThanOrEqual(overlayBox.y + 1);
    await expect(field.getByTestId('record-audio-button')).toHaveCount(0);
    await expect(field.getByTestId('composer-send-button')).toHaveCount(0);
    await expect(field.getByTestId('message-expand-button')).toHaveCount(0);
    if (includeNotes) {
      await expect(editor).toContainText('Existing detail 12.');
      expect(await scroll.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
      await scroll.evaluate(element => { element.scrollTop = element.scrollHeight; });
      expect(await scroll.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    }
    await scroll.evaluate(element => { element.scrollTop = 0; });
    const image = field.getByRole('img', { name: 'recording-draft.jpg' });
    await expect(image).toBeVisible();
    const screenshot = test.info().outputPath('recording-with-visible-draft.png');
    await page.screenshot({ path: screenshot });
    await test.info().attach('Recording with visible draft', { path: screenshot, contentType: 'image/png' });
    for (const closeWithEscape of [false, true]) {
      await image.click();
      const viewer = page.getByTestId('embed-fullscreen-overlay');
      await expect(viewer).toBeVisible();
      await expect(viewer.getByRole('img').first()).toBeVisible();
      await expect(overlay).toHaveAttribute('data-recording-finalized', 'false');
      if (closeWithEscape) await page.keyboard.press('Escape');
      else await viewer.getByTestId('embed-minimize').click();
      await expect(viewer, `${closeWithEscape ? 'Escape' : 'Close button'} closes the image viewer during recording`).toHaveCount(0);
      await expect(overlay).toHaveAttribute('data-recording-finalized', 'false');
      await expect(overlay).toHaveAttribute('data-recording-processing', 'false');
      await expect(image).toBeVisible();
    }
    await expect(fixture).toHaveAttribute('data-send-requests', '0');
    await overlay.getByTestId('record-finish-button').click();
    await expect(overlay).toHaveAttribute('data-recording-processing', 'true');
    await expect(editor).toBeVisible();
    await expect(image).toBeVisible();
    await release();
    await expect(overlay).toHaveCount(0);
    await expect(editor).toContainText(CORRECTED_TRANSCRIPT);
    await expect(image).toBeVisible();
    if (includeNotes) await expect(editor).toContainText('Existing detail 12.');
    await expect(fixture).toHaveAttribute('data-send-requests', '0');
  });
}

// contract-test: direct surface=gui.web assertions=message-input.audio.live-editor-transcript,message-input.recording.lifecycle
test('moving the caret while recording inserts the next words there and Enter in the editor finishes', async ({ page }) => {
  test.setTimeout(60000);
  const { field, editor, overlay, emit, release } = await openRecording(page, 680, 'recording', { draftText: '' });
  await expect(editor).toHaveText(RAW_TRANSCRIPT);
  // Tap the start of the dictated text and keep speaking.
  await editor.click({ position: { x: 1, y: 8 } });
  await expect(editor).toBeFocused();
  // The tap itself places the caret; recording must not move it to the end.
  await expect.poll(() => editor.evaluate(() => window.getSelection()?.anchorOffset)).toBe(0);
  emit(' urgently');
  await expect(editor).toHaveText(`urgently ${RAW_TRANSCRIPT}`);
  await expect(overlay).toHaveAttribute('data-recording-finalized', 'false');
  const screenshot = test.info().outputPath('recording-caret-redirect.png');
  await field.screenshot({ path: screenshot });
  await test.info().attach('Dictation inserted at the moved caret', { path: screenshot, contentType: 'image/png' });
  // Enter in the focused editor finishes the recording instead of sending or adding a line.
  await page.keyboard.press('Enter');
  await expect(overlay).toHaveAttribute('data-recording-processing', 'true');
  await expect(editor).toHaveText(`urgently ${RAW_TRANSCRIPT}`);
  await release();
  await expect(overlay).toHaveCount(0);
  // Dictation the user arranged in two places is kept rather than overwritten.
  await expect(editor).toHaveText(`urgently ${RAW_TRANSCRIPT}`);
  await expect(editor).not.toContainText(CORRECTED_TRANSCRIPT);
});

// contract-test: direct surface=gui.web assertions=message-input.audio.live-editor-transcript,pii.composer.detect-redact-exclude
test('dictated private data is highlighted live and fades out recording Send until reviewed', async ({ page }) => {
  test.setTimeout(60000);
  const { field, editor, overlay, emit } = await openRecording(page, 680, 'recording', { draftText: '' });
  const send = overlay.getByTestId('record-send-button');
  const finish = overlay.getByTestId('record-finish-button');
  await expect(send).toBeVisible();
  emit(' and email anna.private@example.com today');
  const highlight = editor.getByTestId('pii-highlight').filter({ hasText: 'anna.private@example.com' });
  await expect(highlight).toHaveAttribute('data-pii-type', 'EMAIL');
  await expect(send).toHaveCount(0);
  await expect(finish).toBeVisible();
  await expect(overlay.getByTestId('record-cancel-button')).toBeVisible();
  await expect(overlay).toHaveAttribute('data-recording-finalized', 'false');
  const screenshot = test.info().outputPath('recording-pii-hides-send.png');
  await field.screenshot({ path: screenshot });
  await test.info().attach('Recording with detected private data', { path: screenshot, contentType: 'image/png' });
  // Tapping the highlight marks it as not private and restores direct Send.
  await highlight.click();
  await expect(editor.getByTestId('pii-highlight')).toHaveCount(0);
  await expect(send).toBeVisible();
  await expect(send).toBeEnabled();
  await expect(overlay).toHaveAttribute('data-recording-finalized', 'false');
});
