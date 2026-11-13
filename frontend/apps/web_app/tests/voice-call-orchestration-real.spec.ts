/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (dev-only real-stack run; the runner records the Playwright video and screenshots of every checkpoint)
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Real voice call that starts a spawned main chat and speaks its report (dev-only:
 * scripts/voice_call_orchestration_web_real_test.py). No mocks.
 *
 * One WAV is the fake microphone: utterance A asks for a separate chat that writes a poem and
 * reports back, ~8 s of silence, utterance B asks for the capital of France, then a long silence.
 * Checked: the spawned chat appears with its started notice in the creator chat; B is answered
 * (Paris) and spoken; the report/finished notices appear; exactly one automatic interpreting
 * assistant message follows them, is spoken only after the Paris audio ended, and nothing
 * answers the same events a second time within 30 s.
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
const SLUG = 'chat-report-spoken';
const ACK_ROOT = '/audio/assistant-acknowledgements/';
const NOTICE = '[data-testid="chat-orchestration-event"]';

type Played = { src: string; startedAt: number; endedAt: number; maxTime: number; playing: boolean };
type Recorder = { notifications: { cls: string; text: string }[]; played: Played[] };

/** In-page recorders: notifications and media playback with start/end times (performance.now). */
function installRecorders() {
  const w = window as unknown as { __realVoice: Recorder };
  w.__realVoice = { notifications: [], played: [] };
  const seen = new WeakSet<Element>();
  const scan = () => document.querySelectorAll('[data-testid="notification"]').forEach((node) => {
    if (seen.has(node)) return;
    seen.add(node);
    w.__realVoice.notifications.push({ cls: node.className, text: (node.textContent || '').trim().slice(0, 300) });
  });
  new MutationObserver(scan).observe(document, { childList: true, subtree: true });
  const originalPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function play(this: HTMLMediaElement) {
    const entry: Played = { src: this.currentSrc || this.src || '', startedAt: -1, endedAt: -1, maxTime: 0, playing: false };
    w.__realVoice.played.push(entry);
    this.addEventListener('playing', () => {
      entry.playing = true;
      entry.src = this.currentSrc || entry.src;
      if (entry.startedAt < 0) entry.startedAt = performance.now();
      entry.endedAt = -1;
    });
    const finish = () => { if (entry.playing) entry.endedAt = performance.now(); };
    this.addEventListener('ended', finish);
    this.addEventListener('pause', finish);
    this.addEventListener('timeupdate', () => { entry.maxTime = Math.max(entry.maxTime, this.currentTime); });
    return originalPlay.call(this);
  };
}

const recorded = (page: Page): Promise<Recorder> => page.evaluate(() => (window as unknown as { __realVoice: Recorder }).__realVoice);
const now = (page: Page): Promise<number> => page.evaluate(() => performance.now());

async function snap(page: Page, testInfo: TestInfo, name: string) {
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  const file = path.join(ARTIFACTS, `${name}.png`);
  await page.screenshot({ path: file });
  await testInfo.attach(name, { path: file, contentType: 'image/png' });
}

/** Index of the last report/finished notice and of the last assistant message in document order, plus counts. */
async function chatShape(page: Page) {
  return page.evaluate((notice) => {
    const nodes = Array.from(document.querySelectorAll(`${notice}, [data-testid="message-assistant"]`));
    const kind = (node: Element) => (node.matches('[data-testid="message-assistant"]') ? 'a'
      : (node.getAttribute('data-action') || 'n'));
    const sequence = nodes.map(kind);
    const lastEvent = Math.max(sequence.lastIndexOf('report'), sequence.lastIndexOf('finished'));
    return { sequence, lastEvent, assistantAfterEvents: lastEvent < 0 ? 0 : sequence.slice(lastEvent + 1).filter((k) => k === 'a').length };
  }, NOTICE);
}

test.describe(`real voice call orchestration: ${SLUG}`, () => {
  test.skip(!ENABLED, 'Dev-only real voice call: run through scripts/voice_call_orchestration_web_real_test.py.');
  test.use({
    permissions: ['microphone'],
    launchOptions: {
      executablePath: process.env.OPENMATES_PROOF_CHROME || undefined,
      args: ['--disable-save-password-bubble', '--disable-features=AutofillSaveCardInfoToAccountSignedIn,PasswordImport',
        '--use-mock-keychain', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
        `--use-file-for-fake-audio-capture=${path.join(SPEECH_DIR, `${SLUG}.wav`)}`],
    },
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.orchestration-continuity,chat-orchestration.events.automatic-interpretation
  test('a spawned chat started in a call reports back and its report is interpreted once, spoken after the current answer',
    async ({ page }: { page: Page }, testInfo: TestInfo) => {
      test.setTimeout(900_000);
      expect(getTestAccount().email, 'test account credentials').toBeTruthy();
      expect(fs.existsSync(path.join(SPEECH_DIR, `${SLUG}.wav`)), 'generated speaker audio').toBe(true);
      await page.setViewportSize({ width: 1400, height: 1000 });
      const log = createSignupLogger('VOICE_REAL_ORCHESTRATION');
      const screenshot = createStepScreenshotter(log);
      await page.addInitScript(installRecorders);

      await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
      await loginToTestAccount(page, log, screenshot);
      await setChatSidebarOpen(page, true, log);
      const chatsBefore = await page.getByTestId('chat-item').count();
      let started = false;
      try {
        await page.locator('[data-testid="voice-call-start"]:visible').click();
        started = true;
        const privacy = page.getByTestId('notification').filter({ hasText: 'Before your first voice call' });
        if (await privacy.isVisible({ timeout: 3_000 }).catch(() => false)) {
          await privacy.getByRole('button', { name: 'Continue', exact: true }).click();
        }
        await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now', { timeout: 45_000 });

        const heardA = page.getByTestId('message-user').filter({ hasText: /separate new chat|poem about the sea/i });
        await expect(heardA).toHaveCount(1, { timeout: 60_000 });
        log(`heard: ${(await heardA.first().textContent())?.trim()}`);

        // A new sidebar chat appears and the creator chat shows the started notice.
        const startedNotice = page.locator(`${NOTICE}[data-action="started"]`);
        await expect(startedNotice.first()).toBeVisible({ timeout: 240_000 });
        await expect.poll(() => page.getByTestId('chat-item').count(), { timeout: 60_000, message: 'spawned chat in the sidebar' })
          .toBeGreaterThan(chatsBefore);
        await snap(page, testInfo, `${SLUG}-01-started-notice`);

        // Utterance B arrives while the spawned chat works.
        const heardB = page.getByTestId('message-user').filter({ hasText: /capital of France/i });
        await expect(heardB).toHaveCount(1, { timeout: 120_000 });
        const tHeardB = await now(page);
        log(`heard: ${(await heardB.first().textContent())?.trim()}`);
        const mute = page.getByTestId('voice-call-mute');
        if (await mute.isEnabled()) {
          await mute.click();  // the looped file must not repeat the requests
          await expect(mute).toHaveAttribute('aria-pressed', 'true');
        }
        const paris = page.getByTestId('message-assistant').filter({ hasText: /Paris/i });
        await expect(paris.first()).toBeVisible({ timeout: 150_000 });
        await snap(page, testInfo, `${SLUG}-02-paris-answer`);

        // The spawned chat's report / finished event arrives in the creator chat.
        await expect(page.locator(`${NOTICE}[data-action="report"], ${NOTICE}[data-action="finished"]`).first())
          .toBeVisible({ timeout: 420_000 });
        log(`event notices: ${JSON.stringify((await chatShape(page)).sequence)}`);

        // Exactly one interpreting assistant message follows the events, and it is spoken.
        await expect.poll(async () => (await chatShape(page)).assistantAfterEvents, { timeout: 240_000,
          message: 'one automatic interpreting assistant message after the events' }).toBeGreaterThanOrEqual(1);
        await expect.poll(async () => {
          const speech = (await recorded(page)).played.filter((e) => e.playing && e.startedAt >= tHeardB && !e.src.includes(ACK_ROOT));
          return speech.length >= 2 && speech.every((e) => e.endedAt > e.startedAt);
        }, { timeout: 240_000, message: 'Paris answer and interpretation audio played to the end' }).toBe(true);
        const shape = await chatShape(page);
        expect(shape.assistantAfterEvents, 'exactly one automatic interpreting turn').toBe(1);
        await snap(page, testInfo, `${SLUG}-03-events-and-interpretation`);

        // Ordering: the interpretation is spoken only after the Paris answer finished playing.
        const speech = (await recorded(page)).played.filter((e) => e.playing && e.startedAt >= tHeardB && !e.src.includes(ACK_ROOT))
          .sort((a, b) => a.startedAt - b.startedAt);
        const interpretation = speech[speech.length - 1];
        const parisEnd = Math.max(...speech.slice(0, -1).map((e) => e.endedAt));
        log(`played audio: ${JSON.stringify(speech.map((e) => ({ start: Math.round(e.startedAt), end: Math.round(e.endedAt),
          seconds: Math.round(e.maxTime * 10) / 10 })))}`);
        log(`interpretation: audio start ${Math.round(interpretation.startedAt)} ms, Paris audio end ${Math.round(parisEnd)} ms, `
          + `assistant messages after events ${shape.assistantAfterEvents}`);
        expect(interpretation.startedAt, 'interpretation starts after the Paris answer finished').toBeGreaterThanOrEqual(parisEnd);
        expect(interpretation.maxTime, 'interpretation audio really advances').toBeGreaterThan(1.5);

        // No second automatic answer for the same events.
        await page.waitForTimeout(30_000);
        expect((await chatShape(page)).assistantAfterEvents, 'no second automatic answer within 30 s').toBe(1);
        expect(speech.length, 'no extra speech without a new answer').toBe(
          (await recorded(page)).played.filter((e) => e.playing && e.startedAt >= tHeardB && !e.src.includes(ACK_ROOT)).length);

        await page.getByTestId('voice-call-hangup').click();
        started = false;
        await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
        const problems = (await recorded(page)).notifications.filter((n) => /notification-(error|warning)/.test(n.cls));
        expect(problems, 'no error or warning notification during the call').toEqual([]);
        await snap(page, testInfo, `${SLUG}-04-ended`);
      } finally {
        if (started) await page.getByTestId('voice-call-hangup').click({ timeout: 5_000 }).catch(() => undefined);
        await deleteActiveChat(page, log, screenshot, `${SLUG}-cleanup`);
      }
    });
});
