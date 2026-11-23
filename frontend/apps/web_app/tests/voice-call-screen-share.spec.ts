/** Web voice-call screen sharing on the real call stack in isolated CI.
 * The browser's display picker is replaced by a canvas stream in an init script
 * (headless CI has no screen picker); frames, call socket and encryption are real.
 */
import type { Page } from '@playwright/test';
/* eslint-disable @typescript-eslint/no-require-imports -- Existing shared helpers use CommonJS. */
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

interface ShareProbe { requests: number; trackStops: number; endShare: () => void; sentFrames: { source?: string }[] }

/** Stub display capture with a canvas stream and record call-socket frames. */
async function installFakeDisplayCapture(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const probe: ShareProbe = { requests: 0, trackStops: 0, endShare: () => {}, sentFrames: [] };
    Object.assign(window, { __screenShareProbe: probe });
    Object.defineProperty(navigator.mediaDevices, 'getDisplayMedia', {
      configurable: true,
      value: async () => {
        probe.requests++;
        const canvas = document.createElement('canvas');
        canvas.width = 1280; canvas.height = 720;
        const context = canvas.getContext('2d')!;
        let tick = 0;
        const paint = () => { context.fillStyle = tick++ % 2 ? '#0f766e' : '#7c3aed'; context.fillRect(0, 0, 1280, 720); };
        paint();
        const timer = setInterval(paint, 200);
        const stream = canvas.captureStream(5);
        const [track] = stream.getVideoTracks();
        const stop = track.stop.bind(track);
        track.stop = () => { probe.trackStops++; clearInterval(timer); stop(); };
        probe.endShare = () => { clearInterval(timer); stop(); track.dispatchEvent(new Event('ended')); };
        return stream;
      },
    });
    const send = WebSocket.prototype.send;
    WebSocket.prototype.send = function (data: string | ArrayBufferLike | Blob | ArrayBufferView) {
      if (typeof data === 'string' && data.includes('"camera_frame"')) {
        try { probe.sentFrames.push({ source: JSON.parse(data).source }); } catch { /* non-JSON frames are not call events */ }
      }
      return send.call(this, data);
    };
  });
}

const probe = (page: Page) => page.evaluate(() => {
  const p = (window as unknown as { __screenShareProbe: ShareProbe }).__screenShareProbe;
  return { requests: p.requests, trackStops: p.trackStops, frames: p.sentFrames.map(frame => frame.source) };
});

/** A silent microphone (a real MediaStream), as the ambient-sounds call spec uses; sharing needs no speech. */
async function installSilentMicrophone(page: Page): Promise<void> {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => new AudioContext().createMediaStreamDestination().stream;
  });
}

async function startCall(page: Page): Promise<void> {
  await installSilentMicrophone(page);
  await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
  // The consent notice has its own case in voice-call.spec.ts; save the
  // acknowledgement through the product API (as that spec does) so this case
  // starts its call with one tap.
  const acknowledged = await page.evaluate(async (apiUrl) => {
    const response = await fetch(`${apiUrl}/v1/settings/voice-processing-ack`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version: 3 }),
    });
    return response.ok && (await response.json()).acknowledged === true;
  }, process.env.PLAYWRIGHT_TEST_API_URL!);
  expect(acknowledged, 'save the voice processing acknowledgement').toBe(true);
  await page.locator('[data-testid="voice-call-start"]:visible').click();
  await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now', { timeout: 30_000 });
}

test.describe('voice call screen sharing', () => {
  // Call diagnostics: why a started call ended, attached to a failed case.
  let callConsole: string[] = [];
  test.beforeEach(async ({ page }) => {
    callConsole = [];
    page.on('console', (message) => {
      const line = message.text();
      if (/\[(VoiceCall|RustCore)\]/.test(line) || message.type() === 'error') callConsole.push(`${message.type()}: ${line}`.slice(0, 500));
    });
    page.on('response', (response) => {
      if (response.status() >= 400) callConsole.push(`http ${response.status()} ${new URL(response.url()).pathname}`);
    });
  });
  test.afterEach(async ({ page: _page }, testInfo) => {
    if (testInfo.status !== testInfo.expectedStatus) {
      await testInfo.attach('voice-call-console', { body: callConsole.join('\n') || '(none)', contentType: 'text/plain' });
    }
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.web-screen-share
  test('desktop Chrome starts and stops sharing by tap and by the browser stop control', async ({ page, context }) => {
    test.setTimeout(180_000);
    await context.grantPermissions(['microphone']);
    await page.setViewportSize({ width: 1280, height: 900 });
    await installFakeDisplayCapture(page);
    await startCall(page);
    const share = page.getByTestId('voice-call-screen-share');
    await expect(share).toBeVisible();
    await expect(page.getByTestId('voice-call-screen-share-indicator')).toHaveCount(0);

    await share.click();
    await expect(page.getByTestId('voice-call-screen-share-indicator')).toContainText('You are sharing your screen');
    await expect.poll(async () => (await probe(page)).frames.length, { timeout: 30_000 }).toBeGreaterThan(0);
    expect((await probe(page)).frames.every(source => source === 'screen')).toBe(true);

    await page.getByTestId('voice-call-screen-share-stop').click();
    await expect(page.getByTestId('voice-call-screen-share-indicator')).toHaveCount(0);
    await expect.poll(async () => (await probe(page)).trackStops).toBeGreaterThan(0);
    const framesAfterStop = (await probe(page)).frames.length;
    await page.waitForTimeout(2500);
    expect((await probe(page)).frames.length).toBe(framesAfterStop);

    // The browser's own stop-sharing control ends the track: sharing stops quietly.
    await share.click();
    await expect(page.getByTestId('voice-call-screen-share-indicator')).toBeVisible();
    await page.evaluate(() => (window as unknown as { __screenShareProbe: ShareProbe }).__screenShareProbe.endShare());
    await expect(page.getByTestId('voice-call-screen-share-indicator')).toHaveCount(0);
    await expect(page.getByTestId('voice-call-bar')).toBeVisible();
    await page.getByTestId('voice-call-hangup').click();
  });

  test.describe('mobile Safari', () => {
    test.use({
      viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true,
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
    });

    // contract-test: direct surface=gui.web assertions=video-call.video.web-screen-share
    test('hides the screen share button where getDisplayMedia is absent', async ({ page, context }) => {
      test.setTimeout(180_000);
      await context.grantPermissions(['microphone']);
      // iOS Safari exposes no getDisplayMedia; Chromium here does, so remove it as WebKit would.
      await page.addInitScript(() => {
        Object.defineProperty(MediaDevices.prototype, 'getDisplayMedia', { configurable: true, value: undefined });
      });
      await startCall(page);
      await expect(page.getByTestId('voice-call-video')).toBeVisible();
      await expect(page.getByTestId('voice-call-screen-share')).toHaveCount(0);
    });
  });
});
