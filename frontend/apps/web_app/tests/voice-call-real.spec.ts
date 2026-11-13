/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (dev-only real-stack run; the runner records the Playwright video and screenshots of every checkpoint)
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Real voice calls on the dev stack, no mocks (dev-only: scripts/voice_call_web_real_test.py).
 *
 * The runner turns each spoken question into a WAV with text-to-speech and Chromium
 * plays it as its microphone (--use-file-for-fake-audio-capture). Everything after
 * that is the real product: speech-to-text, AI routing and skills, the Mate's
 * text-to-speech and the browser's playback. Each scenario starts the call from a
 * new chat and checks what a person sees and hears:
 *  - the spoken question appears as the user message;
 *  - the new chat confirms with the neutral system clip, never a Mate clip;
 *  - the reply is spoken (an audio element plays it) while its words are revealed;
 *  - the call duration counter runs;
 *  - the expected skill result shows (video search scenario);
 *  - no error or warning notification appears, in particular not
 *    "canonical embed revision changed or is immutable".
 * Held out of isolated CI: real provider inference with the personal dev account.
 */
import type { Page, TestInfo } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const { expect, test } = require('@playwright/test');
const { deleteActiveChat, loginToTestAccount, setChatSidebarOpen } = require('./helpers/chat-test-helpers');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const ENABLED = process.env.VOICE_CALL_REAL_DEV === '1';
const SPEECH_DIR = process.env.VOICE_CALL_REAL_SPEECH_DIR || '';
const ARTIFACTS = 'artifacts';

interface Scenario {
  slug: string;
  question: string;
  heard: RegExp;
  answer: RegExp;
  videos: boolean;
}

// The runner generates <slug>.wav for each scenario from `question`; keep both lists in sync
// through scripts/voice_call_web_real_test.py SCENARIOS.
const SCENARIOS: Scenario[] = [
  { slug: 'capital', question: 'What is the capital of France?', heard: /capital of France/i,
    answer: /Paris/i, videos: false },
  { slug: 'black-hole', question: 'How does a black hole work? Show me a video example.', heard: /black hole/i,
    answer: /black hole|gravity|event horizon/i, videos: true },
];

/** In-page recorders: notifications, media playback and the unspoken-word highlight. */
function installRecorders() {
  type Played = { src: string; maxTime: number; playing: boolean };
  const w = window as unknown as { __realVoice: { notifications: { cls: string; text: string }[]; played: Played[];
    unspoken: number[] } };
  w.__realVoice = { notifications: [], played: [], unspoken: [] };
  const seen = new WeakSet<Element>();
  const scan = () => document.querySelectorAll('[data-testid="notification"]').forEach((node) => {
    if (seen.has(node)) return;
    seen.add(node);
    w.__realVoice.notifications.push({ cls: node.className, text: (node.textContent || '').trim().slice(0, 300) });
  });
  new MutationObserver(scan).observe(document, { childList: true, subtree: true });
  const originalPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function play(this: HTMLMediaElement) {
    const entry: Played = { src: this.currentSrc || this.src || '', maxTime: 0, playing: false };
    w.__realVoice.played.push(entry);
    this.addEventListener('playing', () => { entry.playing = true; entry.src = this.currentSrc || entry.src; });
    this.addEventListener('timeupdate', () => { entry.maxTime = Math.max(entry.maxTime, this.currentTime); });
    return originalPlay.call(this);
  };
  setInterval(() => {
    const highlight = (CSS as unknown as { highlights?: Map<string, Iterable<Range>> }).highlights
      ?.get('assistant-speech-unspoken');
    let chars = 0;
    if (highlight) for (const range of highlight) chars += range.toString().length;
    w.__realVoice.unspoken.push(chars);
  }, 100);
}

async function recorded(page: Page) {
  return page.evaluate(() => (window as unknown as { __realVoice: {
    notifications: { cls: string; text: string }[]; played: { src: string; maxTime: number; playing: boolean }[];
    unspoken: number[] } }).__realVoice);
}

async function timerSeconds(page: Page): Promise<number> {
  const text = (await page.getByTestId('voice-call-timer').textContent()) ?? '';
  expect(text.trim()).toMatch(/^\d{2}:\d{2}$/);
  return text.trim().split(':').reduce((total, part) => total * 60 + Number(part), 0);
}

async function snap(page: Page, testInfo: TestInfo, name: string) {
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  const file = path.join(ARTIFACTS, `${name}.png`);
  await page.screenshot({ path: file });
  await testInfo.attach(name, { path: file, contentType: 'image/png' });
}

const ACK_ROOT = '/audio/assistant-acknowledgements/';
const MATE_WAITING_CLIP = /\/audio\/assistant-acknowledgements\/(?!system\/)[^/]+\/[^/]+\/(general|lookup|reasoning|action)-\d+\.mp3/;

for (const scenario of SCENARIOS) {
  test.describe(`real voice call: ${scenario.slug}`, () => {
    test.skip(!ENABLED, 'Dev-only real voice call: run through scripts/voice_call_web_real_test.py.');
    test.use({
      permissions: ['microphone'],
      launchOptions: {
        executablePath: process.env.OPENMATES_PROOF_CHROME || undefined,
        args: ['--disable-save-password-bubble', '--disable-features=AutofillSaveCardInfoToAccountSignedIn,PasswordImport',
          '--use-mock-keychain', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
          `--use-file-for-fake-audio-capture=${path.join(SPEECH_DIR, `${scenario.slug}.wav`)}`],
      },
    });

    // contract-test: direct surface=gui.web assertions=video-call.chat.transcripts,video-call.audio.localized-waiting,video-call.audio.spoken-rich-response
    test(`a spoken question in a new chat is transcribed, answered aloud${scenario.videos ? ' with videos' : ''} and raises no error`,
      async ({ page }: { page: Page }, testInfo: TestInfo) => {
        test.setTimeout(420_000);
        expect(getTestAccount().email, 'test account credentials').toBeTruthy();
        expect(fs.existsSync(path.join(SPEECH_DIR, `${scenario.slug}.wav`)), 'generated speaker audio').toBe(true);
        await page.setViewportSize({ width: 1400, height: 1000 });
        const log = createSignupLogger(`VOICE_REAL_${scenario.slug.toUpperCase()}`);
        const screenshot = createStepScreenshotter(log);
        const consoleErrors: string[] = [];
        page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300)); });
        await page.addInitScript(installRecorders);

        await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
        await loginToTestAccount(page, log, screenshot);
        await setChatSidebarOpen(page, false, log);
        let started = false;
        try {
          await page.locator('[data-testid="voice-call-start"]:visible').click();
          started = true;
          const privacy = page.getByTestId('notification').filter({ hasText: 'Before your first voice call' });
          if (await privacy.isVisible({ timeout: 3_000 }).catch(() => false)) {
            await privacy.getByRole('button', { name: 'Continue', exact: true }).click();
            log('voice processing acknowledgement saved for this account');
          }
          await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now', { timeout: 45_000 });
          await expect(page.getByTestId('voice-call-bar')).toBeVisible();
          const timerAtStart = await timerSeconds(page);
          await snap(page, testInfo, `${scenario.slug}-01-listening`);

          // The question is spoken once by the fake microphone; it must arrive as the user's message.
          const userMessage = page.getByTestId('message-user').filter({ hasText: scenario.heard });
          await expect(userMessage).toHaveCount(1, { timeout: 60_000 });
          log(`heard: ${(await userMessage.first().textContent())?.trim()}`);
          const mute = page.getByTestId('voice-call-mute');
          if (await mute.isEnabled()) {
            await mute.click();  // the looped file must not ask the question a second time
            await expect(mute).toHaveAttribute('aria-pressed', 'true');
          }
          await snap(page, testInfo, `${scenario.slug}-02-transcribed`);

          const reply = page.getByTestId('message-assistant').last();
          await expect(reply).toContainText(scenario.answer, { timeout: 150_000 });
          if (scenario.videos) {
            const videos = page.locator('[data-testid="embed-preview"][data-app-id="videos"]');
            await expect(videos.first()).toBeVisible({ timeout: 180_000 });
            await expect(page.locator('[data-testid="embed-preview"][data-app-id="videos"][data-status="finished"]').first())
              .toBeVisible({ timeout: 180_000 });
            log(`video results: ${await videos.count()}`);
            await snap(page, testInfo, `${scenario.slug}-03-video-results`);
          }

          // The reply is spoken: its words are revealed while an audio element plays it.
          await expect.poll(async () => (await recorded(page)).unspoken.some((chars) => chars > 0),
            { timeout: 90_000, message: 'reply words must be dimmed until spoken' }).toBe(true);
          await snap(page, testInfo, `${scenario.slug}-04-speaking`);
          await expect.poll(async () => {
            const samples = (await recorded(page)).unspoken;
            return samples.length > 30 && samples.slice(-20).every((chars) => chars === 0);
          }, { timeout: 240_000, message: 'the whole reply must become visible once spoken' }).toBe(true);
          const state = await recorded(page);
          const dimmed = state.unspoken.filter((chars) => chars > 0);
          const steps = dimmed.filter((chars, index) => index > 0 && chars < dimmed[index - 1]).length;
          log(`highlight steps: ${steps}; max unspoken chars: ${Math.max(...dimmed)}`);
          expect(steps, 'the unspoken part must shrink word by word while the reply plays').toBeGreaterThanOrEqual(3);

          const played = state.played.filter((entry) => entry.playing);
          log(`played audio: ${JSON.stringify(played.map((entry) => ({
            src: entry.src.startsWith('blob:') ? 'blob' : entry.src.replace(/^https?:\/\/[^/]+/, '').split('?')[0], seconds: Math.round(entry.maxTime * 10) / 10 })))}`);
          const startClips = played.filter((entry) => entry.src.includes(`${ACK_ROOT}system/`));
          expect(startClips, 'a new chat confirms once with the neutral system clip').toHaveLength(1);
          expect(played.filter((entry) => MATE_WAITING_CLIP.test(entry.src)), 'no guessed Mate waiting clip').toHaveLength(0);
          const speech = played.filter((entry) => !entry.src.includes(ACK_ROOT));
          expect(speech.length, 'the reply is played as audio').toBeGreaterThan(0);
          expect(Math.max(...speech.map((entry) => entry.maxTime)), 'reply audio really advances').toBeGreaterThan(1.5);

          const timerNow = await timerSeconds(page);
          log(`call duration: ${timerAtStart}s -> ${timerNow}s`);
          expect(timerNow, 'call duration counter runs').toBeGreaterThan(timerAtStart + 5);
          const generatedBy = reply.getByTestId('generated-by');
          if (await generatedBy.isVisible().catch(() => false)) log(`reply generated by: ${(await generatedBy.textContent())?.trim()}`);
          await snap(page, testInfo, `${scenario.slug}-05-answered`);

          await page.getByTestId('voice-call-hangup').click();
          started = false;
          await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
          await expect(page.getByTestId('voice-call-ended')).toHaveCount(1, { timeout: 20_000 });

          const notifications = (await recorded(page)).notifications;
          log(`notifications: ${JSON.stringify(notifications)}`);
          const problems = notifications.filter((entry) => /notification-(error|warning)/.test(entry.cls)
            || /canonical embed revision/i.test(entry.text));
          expect(problems, 'no error or warning notification during the call').toEqual([]);
          expect(consoleErrors.filter((text) => /canonical embed revision/i.test(text)),
            'no canonical embed revision error').toEqual([]);
          await snap(page, testInfo, `${scenario.slug}-06-ended`);
        } finally {
          if (started) await page.getByTestId('voice-call-hangup').click({ timeout: 5_000 }).catch(() => undefined);
          await deleteActiveChat(page, log, screenshot, `${scenario.slug}-cleanup`);
        }
      });
  });
}
