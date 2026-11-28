/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
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

const { expect, test: baseTest } = require('@playwright/test');
const { withProofAudio } = require('./helpers/proof-audio');
const test = withProofAudio(baseTest);
const { deleteActiveChat, loginToTestAccount, setChatSidebarOpen } = require('./helpers/chat-test-helpers');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const ENABLED = process.env.VOICE_CALL_REAL_DEV === '1' && process.env.VOICE_LATENCY_PROBE === '1';
const SPEECH_DIR = process.env.VOICE_CALL_REAL_SPEECH_DIR || '';
const SCENARIO = process.env.VOICE_CALL_REAL_SCENARIO || '';
const QUESTIONS = Number(process.env.VOICE_LATENCY_QUESTIONS || '0');
const CALL_SECONDS = Number(process.env.VOICE_LATENCY_CALL_SECONDS || '0');
const GUEST = process.env.VOICE_LATENCY_GUEST === '1';
const SPEAKER_LOOPBACK = process.env.VOICE_LATENCY_SPEAKER_LOOPBACK === '1';
const THINKING = process.env.VOICE_LATENCY_THINKING === '1';
const REASONING_CLIP = /^\/audio\/assistant-acknowledgements\/(?!system\/)[^/]+\/[^/]+\/reasoning-[1-3]\.mp3$/;
const SCALAR_FIELDS = ['final', 'is_final', 'is_last_chunk', 'sequence', 'status', 'kind', 'phase', 'speech_status', 'verified_silence',
  'state', 'stage', 'reason', 'category', 'decision', 'role', 'stt_duration_seconds', 'credits_accrued'];

type Frame = { t: number; socket: string; dir: string; type: string; fields: Record<string, unknown>; textLen?: number };

function installRecorders({ speakerLoopback, thinking }: { speakerLoopback: boolean; thinking: boolean }) {
  const w = window as unknown as { __probe: {
    gum: number[]; playing: { t: number; src: string }[]; speakerFeeds: string[];
  } };
  w.__probe = { gum: [], playing: [], speakerFeeds: [] };
  let echoPath: { context: AudioContext; microphone: MediaStreamAudioDestinationNode } | undefined;
  const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (constraints?: MediaStreamConstraints) => {
    const stream = await original(constraints);
    if (constraints?.audio) {
      w.__probe.gum.push(Date.now());
      if (speakerLoopback) {
        const context = new AudioContext();
        const microphone = context.createMediaStreamDestination();
        context.createMediaStreamSource(stream).connect(microphone);
        echoPath = { context, microphone };
        await context.resume();
        return new MediaStream([...microphone.stream.getAudioTracks(), ...stream.getVideoTracks()]);
      }
    }
    return stream;
  };
  // The streaming player uses a detached HTMLAudioElement, so its events
  // do not reach the document. Capture actual playback from the player.
  const speechUrls = new Map<string, string>();
  const createObjectURL = URL.createObjectURL.bind(URL);
  URL.createObjectURL = (source) => {
    const url = createObjectURL(source);
    if (source instanceof MediaSource) speechUrls.set(url, 'media-source');
    if (source instanceof Blob && source.type === 'audio/mpeg') speechUrls.set(url, 'reply-blob');
    return url;
  };
  const revokeObjectURL = URL.revokeObjectURL.bind(URL);
  URL.revokeObjectURL = (url) => {
    speechUrls.delete(url);
    revokeObjectURL(url);
  };
  const hooked = new WeakSet<HTMLMediaElement>();
  const looped = new WeakMap<HTMLMediaElement, GainNode>();
  const originalPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function play(this: HTMLMediaElement) {
    if (!hooked.has(this)) {
      hooked.add(this);
      this.addEventListener('playing', () => {
        const src = this.currentSrc || this.src || '';
        const kind = speechUrls.get(src) ?? (src.startsWith('blob:') ? 'blob'
          : src.startsWith('data:') ? 'data' : new URL(src || '/', location.href).pathname);
        w.__probe.playing.push({ t: Date.now(), src: kind });
      });
    }
    if (echoPath) {
      const asset = new URL(this.src || this.currentSrc || '/', location.href);
      const loopback = asset.origin === location.origin && asset.pathname.startsWith('/audio/assistant-acknowledgements/')
        && (!thinking || /\/reasoning-[1-3]\.mp3$/.test(asset.pathname));
      const existingGain = looped.get(this);
      if (existingGain) existingGain.gain.value = loopback ? 0.22 : 0;
      if (loopback && !existingGain) {
        const { context, microphone } = echoPath;
        const speaker = context.createMediaElementSource(this);
        const delay = context.createDelay();
        delay.delayTime.value = 0.075;
        const gain = context.createGain();
        gain.gain.value = 0.22;
        speaker.connect(context.destination);
        speaker.connect(delay).connect(gain).connect(microphone);
        looped.set(this, gain);
      }
      if (loopback) w.__probe.speakerFeeds.push(asset.pathname);
    }
    return originalPlay.call(this);
  };
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
    if (!GUEST) expect(getTestAccount().email, 'test account credentials').toBeTruthy();
    expect(fs.existsSync(path.join(SPEECH_DIR, `${SCENARIO}.wav`)), 'generated speaker audio').toBe(true);
    await page.setViewportSize({ width: 1400, height: 1000 });
    const log = createSignupLogger('VOICE_LATENCY');
    const screenshot = createStepScreenshotter(log);
    const frames: Frame[] = [];
    const microphoneTimes: number[] = [];
    const detectorFallbackTimes: number[] = [];
    let sockets = 0;
    page.on('console', (message) => {
      if (message.text().startsWith('[VoiceCall] Local speech detection unavailable;')) detectorFallbackTimes.push(Date.now());
    });
    page.on('websocket', (socket) => {
      const name = socket.url().includes('voice-call') ? `voice${sockets++}` : `main${sockets++}`;
      for (const [event, dir] of [['framesent', 'sent'], ['framereceived', 'received']] as const) {
        socket.on(event, ({ payload }: { payload: string | Buffer }) => {
          const t = Date.now();
          if (typeof payload !== 'string') { frames.push({ t, socket: name, dir, type: '<binary>', fields: { bytes: payload.length } }); return; }
          let data: { type?: unknown; payload?: Record<string, unknown> } & Record<string, unknown>;
          try { data = JSON.parse(payload); } catch { return; }
          const type = typeof data.type === 'string' ? data.type.slice(0, 80) : '<untyped>';
          if (type === 'mic_audio') { microphoneTimes.push(t); return; }
          const body = (data.payload && typeof data.payload === 'object' ? data.payload : data) as Record<string, unknown>;
          const fields: Record<string, unknown> = {};
          for (const key of SCALAR_FIELDS) {
            const value = body[key];
            if (typeof value === 'boolean' || typeof value === 'number' || (typeof value === 'string' && value.length <= 40)) fields[key] = value;
          }
          if (type === 'assistant_speech_acknowledgement' && typeof body.audio_url === 'string'
            && REASONING_CLIP.test(body.audio_url) && typeof body.voice_call_id === 'string') {
            fields.reasoningClip = body.audio_url;
          }
          const text = typeof body.text === 'string' ? body.text : undefined;
          frames.push({ t, socket: name, dir, type, fields, ...(text !== undefined ? { textLen: text.length } : {}) });
        });
      }
    });
    await page.addInitScript(installRecorders, { speakerLoopback: SPEAKER_LOOPBACK, thinking: THINKING });
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    if (!GUEST) {
      await loginToTestAccount(page, log, screenshot);
      await setChatSidebarOpen(page, false, log);
    }
    let started = false;
    try {
      await page.locator('[data-testid="voice-call-start"]:visible').click();
      started = true;
      const clickedAt = Date.now();
      const privacy = page.getByTestId('notification').filter({ hasText: GUEST ? 'Continue' : 'Before your first voice call' });
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
      const probe = await page.evaluate(() => (window as unknown as {
        __probe: { playing: Array<{ t: number; src: string }>; speakerFeeds: string[] };
      }).__probe);
      const report = {
        clickedAt, listeningAt, micFrames: microphoneTimes.length, microphoneTimes,
        detectorFallbackTimes, frames, probe, questions: QUESTIONS, userMessages,
      };
      fs.mkdirSync('artifacts', { recursive: true });
      fs.writeFileSync(path.join('artifacts', 'voice-latency-frames.json'), JSON.stringify(report));
      await testInfo.attach('voice-latency-frames', { body: JSON.stringify(report), contentType: 'application/json' });
      log(`latency frames: ${frames.length}; mic frames: ${microphoneTimes.length}; playing events: ${(probe as { playing: unknown[] }).playing.length}`);
      log(`LATENCY_REPORT ${JSON.stringify(report)}`);
      if (SPEAKER_LOOPBACK) {
        expect(probe.speakerFeeds.length, 'a real static clip reached the speaker path').toBeGreaterThan(0);
        expect(userMessages, 'the microphone echo did not create a chat turn').toBe(QUESTIONS);
        expect(frames.filter(frame => frame.type === 'transcript' && frame.fields.final === true)).toHaveLength(QUESTIONS);
      }
      if (THINKING) {
        const dispatch = frames.find(frame => typeof frame.fields.reasoningClip === 'string');
        const clip = probe.playing.find(event => event.src === dispatch?.fields.reasoningClip);
        const answer = probe.playing.find(event => event.src === 'media-source' || event.src === 'reply-blob');
        expect(dispatch, 'the real model dispatch sent a call-bound reasoning acknowledgement').toBeDefined();
        expect(clip, 'the routed Mate clip played audibly').toBeDefined();
        expect(answer, 'the generated answer played').toBeDefined();
        expect(clip!.t, 'the cached clip played before the generated answer').toBeLessThan(answer!.t);
        expect(probe.speakerFeeds).toContain(clip!.src);
        expect(frames.filter(frame => frame.type === 'transcript' && frame.t >= clip!.t),
          'the thinking clip did not produce even a partial user transcript').toHaveLength(0);
        await expect(page.getByTestId('message-assistant').last().getByTestId('generated-by'))
          .toContainText(/Gemini|Mercury|Claude|GPT-5/i);
      }
      if (GUEST) {
        expect(userMessages, 'the guest question turned into one chat message').toBe(QUESTIONS);
        expect(probe.playing.some(event => event.src === 'reply-blob'), 'the guest heard the generated reply').toBe(true);
      }
      const hangup = page.getByTestId('voice-call-hangup');
      await expect(hangup, 'the call survives the replay and subsequent quiet').toBeVisible({ timeout: 5_000 });
      await hangup.click();
      started = false;
    } finally {
      if (started) await page.getByTestId('voice-call-hangup').click({ timeout: 5_000 }).catch(() => undefined);
      if (!GUEST) await deleteActiveChat(page, log, screenshot, 'latency-probe-cleanup').catch(() => undefined);
    }
  });
});
