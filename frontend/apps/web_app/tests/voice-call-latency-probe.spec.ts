/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (measurement-only latency probe for TASK-9356, never deployed or run in CI)
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Measurement-only voice-call latency probe on the real dev stack (TASK-9356 research).
 *
 * One call, several spoken questions from one fake-microphone WAV (questions separated
 * by long silences). Records, with wall-clock timestamps and no message content:
 *  - when the microphone stream opened (anchor for the known speech offsets in the WAV);
 *  - every WebSocket frame type on the voice socket and the main socket (both directions,
 *    microphone frames only counted), with a few scalar status fields;
 *  - every media element 'playing' event.
 * The analysis runs offline. Not a regression test: it asserts only that the call ran.
 */
import type { Page, TestInfo } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const { expect, test } = require('@playwright/test');
const { deleteActiveChat, loginToTestAccount, setChatSidebarOpen } = require('./helpers/chat-test-helpers');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const ENABLED = process.env.VOICE_CALL_REAL_DEV === '1' && process.env.VOICE_LATENCY_PROBE === '1';
const SPEECH_DIR = process.env.VOICE_CALL_REAL_SPEECH_DIR || '';
const SCENARIO = process.env.VOICE_CALL_REAL_SCENARIO || '';
const QUESTIONS = Number(process.env.VOICE_LATENCY_QUESTIONS || '0');
const CALL_SECONDS = Number(process.env.VOICE_LATENCY_CALL_SECONDS || '0');
const SCALAR_FIELDS = ['final', 'is_final', 'is_last_chunk', 'sequence', 'status', 'kind', 'phase', 'speech_status',
  'state', 'stage', 'reason', 'category', 'decision', 'role'];

type Frame = { t: number; socket: string; dir: string; type: string; fields: Record<string, unknown>; textLen?: number };

function installRecorders() {
  const w = window as unknown as { __probe: { gum: number[]; playing: { t: number; src: string }[] } };
  w.__probe = { gum: [], playing: [] };
  const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (constraints?: MediaStreamConstraints) => {
    const stream = await original(constraints);
    if (constraints && (constraints as { audio?: unknown }).audio) w.__probe.gum.push(Date.now());
    return stream;
  };
  document.addEventListener('playing', (event) => {
    const el = event.target as HTMLMediaElement;
    const src = el.currentSrc || el.src || '';
    w.__probe.playing.push({ t: Date.now(), src: src.startsWith('blob:') ? 'blob' : src.replace(/^https?:\/\/[^/]+/, '').split('?')[0] });
  }, true);
}

test.use({
  permissions: ['microphone'],
  launchOptions: {
    executablePath: process.env.OPENMATES_PROOF_CHROME || undefined,
    args: ['--disable-save-password-bubble', '--disable-features=AutofillSaveCardInfoToAccountSignedIn,PasswordImport',
      '--use-mock-keychain', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
      ...(SCENARIO ? [`--use-file-for-fake-audio-capture=${path.join(SPEECH_DIR, `${SCENARIO}.wav`)}`] : [])],
  },
});

test.describe('voice call latency probe', () => {
  test.skip(!ENABLED, 'Measurement-only: run through the latency probe wrapper.');
  // contract-test: tooling
  test('one call with several spoken questions, every frame timestamped', async ({ page }: { page: Page }, testInfo: TestInfo) => {
    test.setTimeout((CALL_SECONDS + 240) * 1000);
    expect(getTestAccount().email, 'test account credentials').toBeTruthy();
    expect(fs.existsSync(path.join(SPEECH_DIR, `${SCENARIO}.wav`)), 'generated speaker audio').toBe(true);
    await page.setViewportSize({ width: 1400, height: 1000 });
    const log = createSignupLogger('VOICE_LATENCY');
    const screenshot = createStepScreenshotter(log);
    const frames: Frame[] = [];
    let micFrames = 0;
    let sockets = 0;
    page.on('websocket', (socket) => {
      const name = socket.url().includes('voice-call') ? `voice${sockets++}` : `main${sockets++}`;
      for (const [event, dir] of [['framesent', 'sent'], ['framereceived', 'received']] as const) {
        socket.on(event, ({ payload }: { payload: string | Buffer }) => {
          const t = Date.now();
          if (typeof payload !== 'string') { frames.push({ t, socket: name, dir, type: '<binary>', fields: { bytes: payload.length } }); return; }
          let data: { type?: unknown; payload?: Record<string, unknown> } & Record<string, unknown>;
          try { data = JSON.parse(payload); } catch { return; }
          const type = typeof data.type === 'string' ? data.type.slice(0, 80) : '<untyped>';
          if (type === 'mic_audio') { micFrames++; return; }
          const body = (data.payload && typeof data.payload === 'object' ? data.payload : data) as Record<string, unknown>;
          const fields: Record<string, unknown> = {};
          for (const key of SCALAR_FIELDS) {
            const value = body[key];
            if (typeof value === 'boolean' || typeof value === 'number' || (typeof value === 'string' && value.length <= 40)) fields[key] = value;
          }
          const text = typeof body.text === 'string' ? body.text : undefined;
          frames.push({ t, socket: name, dir, type, fields, ...(text !== undefined ? { textLen: text.length } : {}) });
        });
      }
    });
    await page.addInitScript(installRecorders);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, log, screenshot);
    await setChatSidebarOpen(page, false, log);
    let started = false;
    try {
      await page.locator('[data-testid="voice-call-start"]:visible').click();
      started = true;
      const clickedAt = Date.now();
      const privacy = page.getByTestId('notification').filter({ hasText: 'Before your first voice call' });
      const listening = page.getByTestId('voice-call-status-text').filter({ hasText: 'Listening · You can speak now' });
      await expect(privacy.or(listening).first()).toBeVisible({ timeout: 45_000 });
      if (await privacy.isVisible()) {
        await privacy.getByRole('button', { name: 'Continue', exact: true }).click();
        log('voice processing acknowledgement saved for this account');
      }
      await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now', { timeout: 45_000 });
      const listeningAt = Date.now();
      // The WAV speaks every question once; wait for the whole script plus the last answer.
      await page.waitForTimeout(CALL_SECONDS * 1000);
      // Measurement only: record how many turns landed instead of failing before the frames are saved.
      await page.waitForTimeout(20_000);
      const userMessages = await page.getByTestId('message-user').count();
      log(`user messages after the script: ${userMessages} of ${QUESTIONS}`);
      const probe = await page.evaluate(() => (window as unknown as { __probe: unknown }).__probe);
      const report = { clickedAt, listeningAt, micFrames, frames, probe, questions: QUESTIONS, userMessages };
      fs.mkdirSync('artifacts', { recursive: true });
      fs.writeFileSync(path.join('artifacts', 'voice-latency-frames.json'), JSON.stringify(report));
      await testInfo.attach('voice-latency-frames', { body: JSON.stringify(report), contentType: 'application/json' });
      log(`latency frames: ${frames.length}; mic frames: ${micFrames}; playing events: ${(probe as { playing: unknown[] }).playing.length}`);
      log(`LATENCY_REPORT ${JSON.stringify(report)}`);
      await page.getByTestId('voice-call-hangup').click();
      started = false;
    } finally {
      if (started) await page.getByTestId('voice-call-hangup').click({ timeout: 5_000 }).catch(() => undefined);
      await deleteActiveChat(page, log, screenshot, 'latency-probe-cleanup').catch(() => undefined);
    }
  });
});
