import { expect, test } from '../helpers/cookie-audit';
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

for (const width of [330, 768]) {
  for (const processing of [false, true]) {
    // contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.layout.responsive-parity
    test(`round Send remains reachable ${processing ? 'during correction' : 'while recording'} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width: Math.max(390, width + 40), height: 844 });
      await page.goto(`/dev/preview/enter_message/RecordAudio?${processing ? 'variant=processing&' : ''}theme=dark&background=%23181818&width=${width}&chrome=0`);
      await waitForComponentPreview(page);
      const overlay = page.getByTestId('record-overlay');
      const send = overlay.getByTestId('record-send-button');
      await expect(send).toBeVisible();
      await expect(send).toBeEnabled();
      await expect(send).toHaveAccessibleName('Send');
      await expect(send.locator('svg')).toBeVisible();
      await expect(send).toHaveCSS('width', '40px');
      await expect(send).toHaveCSS('height', '40px');
      await expect(send).toHaveCSS('border-radius', '50%');
      for (const id of ['timer-pill', 'record-cancel-button', 'record-finish-button', 'record-send-button']) {
        const button = overlay.getByTestId(id);
        await expect(button).toBeVisible();
        const [controlBox, overlayBox] = await Promise.all([button.boundingBox(), overlay.boundingBox()]);
        expect(controlBox!.x).toBeGreaterThanOrEqual(overlayBox!.x);
        expect(controlBox!.x + controlBox!.width).toBeLessThanOrEqual(overlayBox!.x + overlayBox!.width);
      }
      const [finishBox, sendBox] = await Promise.all([
        overlay.getByTestId('record-finish-button').boundingBox(), send.boundingBox(),
      ]);
      expect(finishBox!.x + finishBox!.width).toBeLessThanOrEqual(sendBox!.x);
      await send.hover();
      await send.focus();
      await expect(send).toBeFocused();
      // Native Enter on Send must retain the selected action during recording.
      await send.press('Enter');
      await expect(send).toBeDisabled();
      await expect(overlay.getByTestId('record-cancel-button')).toBeEnabled();
    });
  }
}

// contract-test: direct surface=gui.web assertions=message-input.actions.visibility
test('shared compact Send preserves its normal and busy states', async ({ page }) => {
  await page.goto('/dev/preview/enter_message/CompactSendButton?theme=light&background=%23dbeafe&width=330&chrome=0');
  await waitForComponentPreview(page);
  const send = page.getByTestId('composer-send-button');
  await expect(send).toBeVisible();
  await expect(send).toHaveAccessibleName('Send');
  await expect(send).toBeEnabled();
  await expect(send.locator('svg')).toBeVisible();
  await expect(send).toHaveCSS('width', '40px');
  await expect(send).toHaveCSS('height', '40px');
  await page.goto('/dev/preview/enter_message/CompactSendButton?variant=disabled&theme=light&background=%23dbeafe&width=330&chrome=0');
  await waitForComponentPreview(page);
  await expect(send).toBeDisabled();
  await expect(send).toHaveAttribute('aria-busy', 'true');
});

type RecorderTestState = {
  stopCalls: number;
  trackStops: number;
  emitData(value: string): void;
  emitStop(): void;
};

// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.recording.lifecycle
test('processing overlay cycles readable messages and respects reduced motion', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('/dev/preview/enter_message/RecordAudio?variant=processing&theme=dark&background=%23181818&width=390&chrome=0');
  await waitForComponentPreview(page);
  const overlay = page.getByTestId('record-overlay');
  const status = overlay.getByTestId('recording-processing-text');
  await expect(overlay).toBeVisible();
  await expect(overlay).toHaveAttribute('data-recording-processing', 'true');
  await expect(status).toHaveText('Improving transcript…');
  await expect(overlay.getByTestId('record-finish-button')).toBeDisabled();
  await expect(overlay.getByTestId('record-cancel-button')).toBeVisible();
  await expect(overlay.getByTestId('record-shortcuts')).toHaveCount(0);
  await expect(overlay.getByTestId('recording-waveform')).toHaveCount(0);
  const container = await overlay.boundingBox();
  const label = await status.boundingBox();
  expect(container).not.toBeNull();
  expect(label).not.toBeNull();
  expect(label!.x).toBeGreaterThanOrEqual(container!.x);
  expect(label!.x + label!.width).toBeLessThanOrEqual(container!.x + container!.width);
  await expect(status).toHaveText('Removing filler words…', { timeout: 4000 });
  await expect(status).toHaveText('Making it more concise…', { timeout: 4000 });
  await expect(status).toHaveText('Improving transcript…', { timeout: 4000 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(status).toHaveCSS('animation-name', 'none');
});

declare global {
  interface Window {
    __recordAudioTest: RecorderTestState;
  }
}

const RECORD_AUDIO_PREVIEW =
  '/dev/preview/enter_message/RecordAudio?variant=liveRecorder&theme=light&background=%23dbeafe&width=768&chrome=0';

async function installRecorderMocks(page: Page) {
  await page.addInitScript(() => {
    type RecorderCallbacks = {
      state: 'inactive' | 'recording' | 'paused';
      mimeType: string;
      ondataavailable: ((event: BlobEvent) => void) | null;
      onstop: (() => void) | null;
    };

    const recorderRef: { current: RecorderCallbacks | null } = { current: null };
    const state: RecorderTestState = {
      stopCalls: 0,
      trackStops: 0,
      emitData(value: string) {
        const currentRecorder = recorderRef.current;
        currentRecorder?.ondataavailable?.(
          new BlobEvent('dataavailable', {
            data: new Blob([value], { type: currentRecorder.mimeType }),
          }),
        );
      },
      emitStop() {
        recorderRef.current?.onstop?.();
      },
    };
    window.__recordAudioTest = state;

    class FakeMediaRecorder implements RecorderCallbacks {
      static isTypeSupported() { return true; }
      state: 'inactive' | 'recording' | 'paused' = 'inactive';
      mimeType = 'audio/mp4';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void) | null = null;
      onerror: ((event: Event) => void) | null = null;

      constructor() {
        recorderRef.current = this;
      }

      start() {
        this.state = 'recording';
      }

      stop() {
        state.stopCalls += 1;
        this.state = 'inactive';
      }
    }

    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: FakeMediaRecorder,
    });
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => ({
          getTracks: () => [{ stop: () => { state.trackStops += 1; } }],
        }),
      },
    });
  });
}

async function openLiveRecorder(page: Page) {
  await installRecorderMocks(page);
  await page.goto(RECORD_AUDIO_PREVIEW);
  await waitForComponentPreview(page);
  const overlay = page.getByTestId('record-overlay');
  await expect(overlay).toBeVisible();
  await expect(overlay).toHaveAttribute('data-recording-finalized', 'false');
  await page.clock.install();
  return overlay;
}

// contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
test('audio preview keeps the raw transcript visible during auto correction', async ({ page }) => {
  await page.goto('/dev/preview/embeds/audio/RecordingEmbedPreview?variant=correcting&chrome=0');
  await waitForComponentPreview(page);

  const preview = page.getByTestId('recording-preview');
  await expect(preview).toBeVisible();
  await expect(preview).toContainText('Please schedule the project review for Thursday afternoon.');
  await expect(preview.getByTestId('recording-auto-correction')).toContainText('Auto correction');
  await expect(preview.locator('.correction-spinner')).toBeVisible();
});

// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
test('recording finish falls back when the browser omits stop and ignores a late stop', async ({ page }) => {
  const overlay = await openLiveRecorder(page);
  await page.evaluate(() => window.__recordAudioTest.emitData('fallback-audio'));
  await page.getByTestId('record-finish-button').click();
  await page.clock.fastForward(10_000);

  await expect(overlay).toHaveAttribute('data-recording-finalized', 'true');
  await expect(overlay).toHaveAttribute('data-recording-stop-intent', 'finish');
  await expect.poll(() => page.evaluate(() => window.__recordAudioTest.trackStops)).toBe(1);

  await page.evaluate(() => window.__recordAudioTest.emitStop());
  await expect.poll(() => page.evaluate(() => window.__recordAudioTest.trackStops)).toBe(1);
  await expect.poll(() => page.evaluate(() => window.__recordAudioTest.stopCalls)).toBe(1);
});

// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
test('cancel escalates a pending finish and releases the microphone synchronously', async ({ page }) => {
  const overlay = await openLiveRecorder(page);
  await page.getByTestId('record-finish-button').click();
  await page.getByTestId('record-cancel-button').click();

  await expect(overlay).toHaveAttribute('data-recording-finalized', 'true');
  await expect(overlay).toHaveAttribute('data-recording-stop-intent', 'cancel');
  expect(await page.evaluate(() => window.__recordAudioTest.trackStops)).toBe(1);

  await page.evaluate(() => window.__recordAudioTest.emitStop());
  expect(await page.evaluate(() => window.__recordAudioTest.trackStops)).toBe(1);
  expect(await page.evaluate(() => window.__recordAudioTest.stopCalls)).toBe(1);
});

// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
test('recording waits for the final data chunk before normal stop finalization', async ({ page }) => {
  const overlay = await openLiveRecorder(page);
  await page.getByTestId('record-finish-button').click();

  await expect(overlay).toHaveAttribute('data-recording-finalized', 'false');
  await page.clock.fastForward(5_000);
  await expect(overlay).toHaveAttribute('data-recording-finalized', 'false');
  await page.evaluate(() => {
    window.__recordAudioTest.emitData('final-audio-chunk');
    window.__recordAudioTest.emitStop();
  });

  await expect(overlay).toHaveAttribute('data-recording-finalized', 'true');
  await expect(overlay).toHaveAttribute('data-recording-stop-intent', 'finish');
  expect(await page.evaluate(() => window.__recordAudioTest.trackStops)).toBe(1);
});
