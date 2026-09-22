import { expect, test } from '../helpers/cookie-audit';
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

type RecorderTestState = {
  stopCalls: number;
  trackStops: number;
  emitData(value: string): void;
  emitStop(): void;
};

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
