// playwright-account: not_required reason=isolated_component_preview
import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = '/dev/preview/voicecall/VoiceCallAudioGatePreview?chrome=0&theme=light&background=%23dbeafe&width=900';
const value = async (page: Page, name: string) => Number(await page.getByTestId(`gate-${name}`).textContent());
interface WorkerEvidence { created: number; terminated: number; ready: number; results: number }
const workerEvidence = (page: Page) => page.evaluate(() =>
  (window as unknown as { __gateWorkerEvidence: WorkerEvidence }).__gateWorkerEvidence);

async function observeNativeWorkers(page: Page) {
  await page.addInitScript(() => {
    const observed: WorkerEvidence = { created: 0, terminated: 0, ready: 0, results: 0 };
    Object.assign(window, { __gateWorkerEvidence: observed });
    const NativeWorker = window.Worker;
    window.Worker = new Proxy(NativeWorker, {
      construct(Target, args) {
        const worker: Worker = Reflect.construct(Target, args);
        observed.created++;
        let terminated = false;
        const terminate = worker.terminate.bind(worker);
        worker.terminate = () => { if (!terminated) { terminated = true; observed.terminated++; } terminate(); };
        worker.addEventListener('message', ({ data }) => {
          if (data?.type === 'ready') observed.ready++;
          if (data?.type === 'result') observed.results++;
        });
        return worker;
      },
    });
  });
}

async function startAndFlushStartup(page: Page) {
  await page.goto(preview);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('audio-gate-preview')).toBeVisible();
  await page.getByRole('button', { name: 'Start capture', exact: true }).click();
  await expect(page.getByTestId('gate-phase')).toHaveText('Capturing before ready');
  await expect.poll(() => value(page, 'captured')).toBeGreaterThanOrEqual(4);
  expect(await value(page, 'uploaded')).toBe(0);
  const capturedBeforeReady = await value(page, 'captured-samples');
  await page.getByRole('button', { name: 'Server ready', exact: true }).click();
  await expect(page.getByTestId('gate-phase')).toHaveText('Live');
  await expect.poll(() => value(page, 'uploaded-samples')).toBeGreaterThanOrEqual(capturedBeforeReady);
  await expect(page.getByTestId('gate-track')).toHaveText('live');
  await expect(page.getByTestId('gate-context')).toHaveText('running');
}

async function assertNativeCleanup(page: Page) {
  await page.getByRole('button', { name: 'Hang up', exact: true }).click();
  await expect(page.getByTestId('gate-phase')).toHaveText('Ended');
  await expect(page.getByTestId('gate-track')).toHaveText('ended');
  await expect(page.getByTestId('gate-context')).toHaveText('closed');
  await expect.poll(async () => {
    const worker = await workerEvidence(page);
    return worker.created - worker.terminated;
  }).toBe(0);
  await expect(page.getByRole('alert')).toHaveCount(0);
}

test.describe('Actual self-hosted voice activity gate', () => {
  // contract-test: direct surface=gui.web assertions=video-call.audio.background-detection,video-call.audio.automatic-idle,video-call.audio.startup-buffer,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
  test('starts during a cold model load, gates actual silence, resumes short speech and releases native resources', async ({ page, context }) => {
    test.setTimeout(100_000);
    await observeNativeWorkers(page);
    let releaseModel!: () => void;
    let modelRequested = false;
    let modelReleased = false;
    const modelHold = new Promise<void>((resolve) => { releaseModel = resolve; });
    const assetOrigins = new Set<string>();
    context.on('request', (request) => {
      if (/silero_vad_v5|ort-wasm-simd-threaded/.test(request.url())) assetOrigins.add(new URL(request.url()).origin);
    });
    await context.route('**/*silero_vad_v5*', async (route) => {
      // Vite's development ?import/?url modules are JavaScript. Hold only the
      // worker's actual model fetch, preserving every real model/worker byte.
      if (route.request().resourceType() === 'script') { await route.continue(); return; }
      modelRequested = true;
      await modelHold;
      modelReleased = true;
      await route.continue();
    });
    try {
      await startAndFlushStartup(page);
      await expect.poll(() => modelRequested, { timeout: 20_000 }).toBe(true);
      expect(modelReleased).toBe(false);
      const coldUploads = await value(page, 'uploaded');
      await expect.poll(() => value(page, 'uploaded')).toBeGreaterThan(coldUploads + 12);
      await expect(page.getByTestId('gate-status')).toHaveText('Listening');
      expect(await value(page, 'ends')).toBe(0);
      expect((await workerEvidence(page)).ready).toBe(0);
      releaseModel();
      await expect.poll(async () => (await workerEvidence(page)).ready, { timeout: 30_000 }).toBe(1);
      await expect(page.getByTestId('gate-status')).toHaveText('Speak to resume call.', { timeout: 15_000 });
      expect(await value(page, 'ends')).toBe(1);
      const idleUploaded = await value(page, 'uploaded');
      const idleCaptured = await value(page, 'captured');
      await expect.poll(() => value(page, 'captured')).toBeGreaterThan(idleCaptured + 12);
      expect(await value(page, 'uploaded')).toBe(idleUploaded);
      expect(await value(page, 'ends')).toBe(1);
      await page.getByRole('button', { name: 'Play short speech', exact: true }).click();
      await expect.poll(() => value(page, 'resumes')).toBe(1);
      await expect.poll(() => value(page, 'uploaded')).toBeGreaterThan(idleUploaded);
      expect(await value(page, 'prefix')).toBeGreaterThanOrEqual(300);
      expect(await value(page, 'prefix')).toBeLessThanOrEqual(500);
      await expect(page.getByTestId('gate-playing')).toHaveText('false');
      await expect(page.getByTestId('gate-status')).toHaveText('Speak to resume call.', { timeout: 15_000 });
      expect(await value(page, 'ends')).toBe(2);

      await page.getByRole('button', { name: 'Mute microphone', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Mute microphone', exact: true })).toHaveAttribute('aria-pressed', 'true');
      const mutedUploads = await value(page, 'uploaded');
      await page.getByRole('button', { name: 'Play speech', exact: true }).click();
      await expect(page.getByTestId('gate-playing')).toHaveText('true');
      await expect(page.getByTestId('gate-playing')).toHaveText('false', { timeout: 10_000 });
      expect(await value(page, 'uploaded')).toBe(mutedUploads);
      expect(await value(page, 'resumes')).toBe(1);
      expect(await value(page, 'ends')).toBe(2);
      await expect(page.getByTestId('gate-status')).toHaveText('Microphone muted');
      await page.getByRole('button', { name: 'Mute microphone', exact: true }).click();
      await expect.poll(() => value(page, 'uploaded')).toBeGreaterThan(mutedUploads);
      await page.getByRole('button', { name: 'Mute microphone', exact: true }).click();
      expect(await value(page, 'ends')).toBe(3);
      expect(assetOrigins).toEqual(new Set([new URL(page.url()).origin]));
      expect((await workerEvidence(page)).results).toBeGreaterThan(100);
      await assertNativeCleanup(page);
    } finally { releaseModel(); }
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.background-detection,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
  test('keeps continuous upload after an actual model fetch failure', async ({ page, context }) => {
    test.setTimeout(45_000);
    await observeNativeWorkers(page);
    let failedModel = false;
    await context.route('**/*silero_vad_v5*', async (route) => {
      if (route.request().resourceType() === 'script') { await route.continue(); return; }
      failedModel = true;
      await route.abort('failed');
    });
    const fallback = page.waitForEvent('console', { predicate: (message) => message.text().includes('Local speech detection unavailable') });
    await startAndFlushStartup(page);
    await fallback;
    expect(failedModel).toBe(true);
    const captureStart = await value(page, 'captured-samples');
    const uploadsStart = await value(page, 'uploaded');
    // Advance through more than the real silence threshold by observing native
    // capture samples, rather than sleeping or fabricating detector outcomes.
    await expect.poll(() => value(page, 'captured-samples'), { timeout: 15_000 }).toBeGreaterThan(captureStart + 16_000 * 6);
    expect(await value(page, 'uploaded')).toBeGreaterThan(uploadsStart + 100);
    expect(await value(page, 'ends')).toBe(0);
    await expect(page.getByTestId('gate-status')).toHaveText('Listening');
    expect((await workerEvidence(page)).ready).toBe(0);
    await assertNativeCleanup(page);
  });
});
