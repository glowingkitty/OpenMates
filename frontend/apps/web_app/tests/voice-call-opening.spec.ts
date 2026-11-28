// proof-video: not_required reason=visual_smoke_not_needed
/** Opening a call from a new chat: the call strip appears once and stays.
 * Real call socket, STT fixture and encrypted chat binding in isolated CI. Every
 * animation frame from the tap until the bound chat is listening is sampled, so
 * a remount, a gap or a replayed entrance fails instead of only looking wrong.
 */
/* eslint-disable @typescript-eslint/no-require-imports -- Existing shared helpers use CommonJS. */
const { expect, test: auditedTest } = require('./helpers/cookie-audit');
const { withProofAudio, proofAudioLaunchArgs } = require('./helpers/proof-audio');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
import { installNativeVoiceInput, nativeVoiceInput } from './helpers/voice-call-test-helpers';
import type { NativeVoiceInputEvidence } from './helpers/voice-call-test-helpers';
import type { Page } from '@playwright/test';

const test = withProofAudio(auditedTest);
test.use({ launchOptions: { args: proofAudioLaunchArgs() }, reducedMotion: 'no-preference' });

interface BarSample {
  t: number;
  count: number;
  id: number;
  top: number;
  opacity: number;
  slot: string;
  faded: string[];
}

function observeStartupSpeech(page: Page) {
  const activity = { startupClip: false, replyProse: false };
  page.on('websocket', socket => {
    if (new URL(socket.url()).pathname !== '/v1/voice-call') return;
    socket.on('framesent', ({ payload }) => {
      if (typeof payload !== 'string') return;
      const frame = JSON.parse(payload);
      if (frame.type !== 'assistant_state' || frame.speaking !== true) return;
      if (typeof frame.clip_audio_url === 'string' && frame.clip_audio_url.endsWith('/chat_start-1.mp3')) {
        activity.startupClip = true;
      }
      if (!frame.clip_audio_url && typeof frame.text === 'string' && frame.text.includes('Ich habe das geprüft')) {
        activity.replyProse = true;
      }
    });
  });
  return activity;
}

function observeSpeechWindow(page: Page) {
  const activity = {
    starts: 0,
    ready: 0,
    pcmBytes: 0,
    streamEnds: 0,
    endedOrWarned: 0,
    usage: null as { seconds: number; credits: number } | null,
    billing: null as { listening: boolean; processing: boolean } | null,
  };
  page.on('websocket', socket => {
    if (new URL(socket.url()).pathname !== '/v1/voice-call') return;
    socket.on('framesent', ({ payload }) => {
      if (typeof payload !== 'string') return;
      const frame = JSON.parse(payload);
      if (frame.type === 'start') activity.starts++;
      if (frame.type === 'mic_audio') activity.pcmBytes += Buffer.from(frame.data, 'base64').length;
      if (frame.type === 'audio_stream_end') activity.streamEnds++;
    });
    socket.on('framereceived', ({ payload }) => {
      if (typeof payload !== 'string') return;
      const frame = JSON.parse(payload);
      if (frame.type === 'ready') activity.ready++;
      if (['ended', 'error', 'speech_idle_warning'].includes(frame.type)) activity.endedOrWarned++;
      if (frame.type === 'usage') {
        activity.usage = { seconds: frame.stt_duration_seconds, credits: frame.credits_accrued };
      }
      if (frame.type === 'billing_activity') {
        activity.billing = { listening: frame.input_listening, processing: frame.processing };
      }
    });
  });
  return activity;
}

test.describe('voice call opening', () => {
  // contract-test: direct surface=gui.web assertions=video-call.chat.call-strip-opening
  test('opens the call bar from a new chat exactly once and keeps it visible until listening', async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    await page.addInitScript(() => {
      const samples: BarSample[] = [];
      const entrances: string[] = [];
      const ids = new WeakMap<Element, number>();
      let nextId = 0;
      let armed = false;
      Object.assign(window, { __callBarSamples: samples, __callBarEntrances: entrances, __armCallBarSampling: () => { armed = true; } });
      document.addEventListener('animationstart', event => {
        if (armed && event.target instanceof Element && event.target.matches('.voice-call-inline-region')) {
          entrances.push(event.animationName);
        }
      });
      const sample = () => {
        if (armed && samples.length < 6000) {
          const bars = [...document.querySelectorAll('[data-testid="voice-call-bar"]')]
            .filter(bar => { const box = bar.getBoundingClientRect(); return box.width > 0 && box.height > 0; });
          const bar = bars[0];
          if (bar && !ids.has(bar)) ids.set(bar, ++nextId);
          let opacity = 1;
          const faded: string[] = [];
          for (let node: Element | null = bar ?? null; node; node = node.parentElement) {
            const value = Number(getComputedStyle(node).opacity);
            opacity *= value;
            if (value < 0.99) faded.push(`${node.className || node.tagName}: ${value.toFixed(2)}`);
          }
          samples.push({
            t: Math.round(performance.now()), count: bars.length, id: bar ? ids.get(bar)! : 0,
            top: bar ? Math.round(bar.getBoundingClientRect().top) : -1, opacity: bar ? Math.round(opacity * 100) / 100 : 0,
            slot: !bar ? 'none' : bar.closest('.voice-call-inline-region') ? 'inline' : 'history', faded,
          });
        }
        requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    });
    await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
    // The consent notice has its own case in voice-call.spec.ts.
    const acknowledged = await page.evaluate(async (apiUrl: string) => {
      const response = await fetch(`${apiUrl}/v1/settings/voice-processing-ack`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: 3 }),
      });
      return response.ok && (await response.json()).acknowledged === true;
    }, process.env.PLAYWRIGHT_TEST_API_URL!);
    expect(acknowledged, 'save the voice processing acknowledgement').toBe(true);

    const start = page.locator('[data-testid="voice-call-start"]:visible');
    await expect(start).toBeVisible();
    // The hover tooltip names only the action.
    await start.hover();
    const tooltip = page.getByRole('tooltip');
    await expect(tooltip).toHaveText('Start voice call');
    await expect(start).not.toHaveAttribute('title', /.+/);
    await testInfo.attach('start-voice-call-tooltip', { body: await page.screenshot(), contentType: 'image/png' });
    await page.mouse.move(0, 0);

    await page.evaluate(() => (window as unknown as { __armCallBarSampling: () => void }).__armCallBarSampling());
    await start.click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now', { timeout: 20_000 });
    await expect(page).toHaveURL(/chat-id=/);
    // playwright-determinism: allow - this observation window measures visibility across the full chat binding and header reveal.
    await page.waitForTimeout(3_000);
    await testInfo.attach('call-bar-open', { body: await page.screenshot(), contentType: 'image/png' });
    const { samples, entrances } = await page.evaluate(() => {
      const recording = window as unknown as { __callBarSamples: BarSample[]; __callBarEntrances: string[] };
      return { samples: recording.__callBarSamples, entrances: recording.__callBarEntrances };
    });
    await testInfo.attach('call-bar-opening-timeline', { body: JSON.stringify(samples), contentType: 'application/json' });
    expect(entrances, 'one slide-in for the call strip').toEqual([expect.stringContaining('voice-call-enter')]);

    const first = samples.findIndex(sample => sample.count > 0);
    expect(first, 'the call bar appears after the tap').toBeGreaterThanOrEqual(0);
    const after = samples.slice(first);
    expect(after.filter(sample => sample.count === 0).length, 'the call bar never disappears while it opens').toBe(0);
    // Name each element change (time, slot, position) so a failure shows which mount replaced the bar.
    const changes = after.filter((sample, index) => index > 0 && sample.id !== after[index - 1].id)
      .map(sample => `${sample.t - after[0].t}ms -> #${sample.id} ${sample.slot} top=${sample.top}`);
    expect(new Set(after.map(sample => sample.id)).size, `one call bar element: no remount restarts its entrance (${after[0].slot} first; ${changes.join(', ')})`).toBe(1);
    expect(Math.max(...after.map(sample => sample.count)), 'never two call bars at once').toBe(1);
    const shown = after.findIndex(sample => sample.opacity >= 0.99);
    expect(shown, 'the call bar becomes fully visible').toBeGreaterThanOrEqual(0);
    const faded = after.slice(shown).filter(sample => sample.opacity < 0.99);
    const ancestors = [...new Set(faded.flatMap(sample => sample.faded))];
    expect(faded.length, `the call bar does not fade out and in again (${ancestors.join(', ')})`).toBe(0);

    await page.getByTestId('voice-call-hangup').click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.audio.localized-waiting
  test('reports the startup announcement and first reply independently for echo detection', async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    await installNativeVoiceInput(page);
    const activity = observeStartupSpeech(page);
    await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    const privacy = page.getByTestId('notification').filter({ hasText: 'Before your first voice call' });
    const status = page.getByTestId('voice-call-status-text');
    await expect(privacy.or(status).first()).toBeVisible({ timeout: 20_000 });
    if (await privacy.isVisible()) await privacy.getByRole('button', { name: 'Continue', exact: true }).click();
    await expect(status).toHaveText('Listening · You can speak now', { timeout: 20_000 });
    await page.getByTestId('voice-call-mute').click();

    const request = 'Bitte prüfe das gründlich';
    const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]');
    await editor.click();
    await page.keyboard.insertText(request);
    await page.getByTestId('composer-send-button').click();
    await expect.poll(() => activity, { timeout: 60_000 }).toEqual({ startupClip: true, replyProse: true });
    await expect(page.getByTestId('message-user')).toHaveCount(1);
    await expect(page.getByTestId('message-user')).toContainText(request);
    await expect(page.getByTestId('message-assistant')).toContainText('Ich habe das geprüft. Hier ist das Ergebnis.');
    await testInfo.attach('new-call-first-reply', { body: await page.screenshot(), contentType: 'image/png' });
    await page.getByTestId('voice-call-hangup').click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.automatic-idle,video-call.audio.background-detection,video-call.usage.provider-metering
  test('keeps one call open with a frozen transcription bill during quiet', async ({ page, context }, testInfo) => {
    test.setTimeout(150_000);
    await installNativeVoiceInput(page);
    const activity = observeSpeechWindow(page);
    await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
    let releaseDetector!: () => void;
    const detectorHeld = new Promise<void>(resolve => { releaseDetector = resolve; });
    await context.route('**/*silero_vad_v5*', async route => {
      if (route.request().resourceType() !== 'script') await detectorHeld;
      await route.continue();
    });
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    const privacy = page.getByTestId('notification').filter({ hasText: 'Before your first voice call' });
    const status = page.getByTestId('voice-call-status-text');
    try {
      await expect(privacy.or(status).first()).toBeVisible({ timeout: 20_000 });
      if (await privacy.isVisible()) await privacy.getByRole('button', { name: 'Continue', exact: true }).click();
      await expect.poll(() => activity.ready).toBe(1);
      await expect.poll(() => activity.pcmBytes).toBeGreaterThan(0);
    } finally {
      releaseDetector();
    }
    await expect.poll(async () => (await nativeVoiceInput(page)).detectorReady, { timeout: 30_000 }).toBe(1);
    await expect(status).toHaveText('Speak to resume call.', { timeout: 15_000 });
    expect(activity.streamEnds).toBe(1);
    await expect.poll(() => activity.billing).toEqual({ listening: false, processing: false });
    const seconds = activity.pcmBytes / 32_000;
    expect(seconds).toBeGreaterThan(0);
    await expect.poll(() => activity.usage).toEqual({ seconds, credits: Math.ceil(seconds * 0.25) });
    const quiet = { ...activity };
    await page.evaluate(() => {
      (window as unknown as { __nativeVoiceInput: NativeVoiceInputEvidence }).__nativeVoiceInput.failDetector();
    });
    await expect.poll(async () => (await nativeVoiceInput(page)).workersTerminated).toBe(1);
    const quietStarted = Date.now();
    await expect.poll(() => Date.now() - quietStarted, { timeout: 41_000, intervals: [1_000] }).toBeGreaterThan(35_000);
    expect(activity).toEqual(quiet);
    expect(activity).toMatchObject({ starts: 1, ready: 1, endedOrWarned: 0 });
    await expect(status).toHaveText('Speak to resume call.');
    const bar = page.getByTestId('voice-call-bar');
    const quietScreenshot = testInfo.outputPath('connected-during-quiet.png');
    await bar.screenshot({ path: quietScreenshot });
    await testInfo.attach('connected-during-quiet', { path: quietScreenshot, contentType: 'image/png' });

    // The isolated transcription provider emits one request per call.
    // Use that request after quiet so it proves the resumed window.
    await expect.poll(async () => (await nativeVoiceInput(page)).speechReady).toBe(true);
    await page.evaluate(() => {
      (window as unknown as { __nativeVoiceInput: NativeVoiceInputEvidence }).__nativeVoiceInput.play(false);
    });
    await expect.poll(() => activity.pcmBytes).toBeGreaterThan(quiet.pcmBytes);
    await expect(page.getByTestId('message-user').filter({ hasText: 'How do I make ramen?' }))
      .toHaveCount(1, { timeout: 30_000 });
    await expect(page.getByTestId('message-assistant').filter({ hasText: 'For ramen, simmer the broth and cook the noodles.' }))
      .toHaveCount(1, { timeout: 30_000 });
    await expect.poll(() => activity.streamEnds).toBe(2);
    await expect.poll(() => activity.billing).toEqual({ listening: false, processing: false });
    await expect(status).toHaveText('Speak to resume call.', { timeout: 20_000 });
    const resumedSeconds = activity.pcmBytes / 32_000;
    expect(resumedSeconds).toBeGreaterThan(seconds);
    await expect.poll(() => activity.usage).toEqual({ seconds: resumedSeconds, credits: Math.ceil(resumedSeconds * 0.25) });
    expect(activity).toMatchObject({ starts: 1, ready: 1, endedOrWarned: 0 });
    const answerScreenshot = testInfo.outputPath('answered-after-quiet.png');
    await page.screenshot({ path: answerScreenshot });
    await testInfo.attach('answered-after-quiet', { path: answerScreenshot, contentType: 'image/png' });
    await bar.getByTestId('voice-call-hangup').click();
    await expect(bar).toHaveCount(0);
  });
});
