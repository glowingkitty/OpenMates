/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (dev-only real-stack run; the runner records the Playwright video and screenshots of every checkpoint)
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Real voice call that starts a spawned main chat and speaks its report (dev-only:
 * scripts/voice_call_orchestration_web_real_test.py). No mocks.
 *
 * A voice call starts in a new chat with the microphone muted at once; a request typed during the
 * call starts a spawned main chat that searches the web and reports back (speech-to-text dropped or
 * split a spoken start-chat request too often for a reliable proof). One WAV is the fake
 * microphone: 90 s of silence, a question about penguins and 90 s of silence, looped by Chromium from
 * the moment the call opens the microphone; the spec mutes at once and unmutes for the question.
 * Checked: the spawned chat appears with its started notice; the unrelated spoken question is
 * answered and spoken here, without writing to the spawned chat; the report/finished notices
 * arrive during the call; exactly one automatic interpreting assistant message follows them, is
 * spoken without overlapping any other speech, and nothing answers the same events again within 30 s.
 * Held out of isolated CI: real provider inference with the personal dev account.
 */
import type { Page, TestInfo } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const { expect, test } = require('@playwright/test');
const { deleteActiveChat, loginToTestAccount, sendMessage, setChatSidebarOpen, startNewChat } = require('./helpers/chat-test-helpers');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const ENABLED = process.env.VOICE_CALL_REAL_DEV === '1';
const SPEECH_DIR = process.env.VOICE_CALL_REAL_SPEECH_DIR || '';
const ARTIFACTS = 'artifacts';
const SLUG = 'chat-report-spoken';
const ACK_ROOT = '/audio/assistant-acknowledgements/';
const NOTICE = '[data-testid="chat-orchestration-event"]';
// The brief's own search wording must not turn the creator turn into a news search
// (chat-orchestration.spawn.brief-not-answered-here).
const SPAWN_REQUEST =
  "Start a new chat titled 'Ocean news' with the brief: search the web for three recent ocean conservation news " +
  'headlines and summarize each in one sentence, then report back to me.';

type Played = { src: string; startedAt: number; endedAt: number; maxTime: number; playing: boolean };
type Recorder = { notifications: { cls: string; text: string }[]; played: Played[]; eventsAt: number };

/** In-page recorders: notifications and media playback with start/end times (performance.now). */
function installRecorders() {
  const w = window as unknown as { __realVoice: Recorder };
  w.__realVoice = { notifications: [], played: [], eventsAt: -1 };
  const seen = new WeakSet<Element>();
  const scan = () => {
    document.querySelectorAll('[data-testid="notification"]').forEach((node) => {
      if (seen.has(node)) return;
      seen.add(node);
      w.__realVoice.notifications.push({ cls: node.className, text: (node.textContent || '').trim().slice(0, 300) });
    });
    // First moment a report/finished notice of a spawned chat is in the page.
    if (w.__realVoice.eventsAt < 0 && document.querySelector(
      '[data-testid="chat-orchestration-event"][data-action="report"], [data-testid="chat-orchestration-event"][data-action="finished"]')) {
      w.__realVoice.eventsAt = performance.now();
    }
  };
  new MutationObserver(scan).observe(document, { childList: true, subtree: true });
  const originalPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function play(this: HTMLMediaElement) {
    const entry: Played = { src: this.currentSrc || this.src || '', startedAt: -1, endedAt: -1, maxTime: 0, playing: false };
    w.__realVoice.played.push(entry);
    // One element can be reused for the next track: a listener only follows its own source.
    const own = () => !entry.src || !this.currentSrc || this.currentSrc === entry.src;
    this.addEventListener('playing', () => {
      if (entry.startedAt >= 0 && !own()) return;
      entry.playing = true;
      entry.src = this.currentSrc || entry.src;
      if (entry.startedAt < 0) entry.startedAt = performance.now();
      entry.endedAt = -1;
    });
    const finish = () => { if (entry.playing) entry.endedAt = performance.now(); };
    for (const name of ['ended', 'pause', 'emptied', 'abort']) this.addEventListener(name, () => { if (own() || name === 'emptied') finish(); });
    this.addEventListener('timeupdate', () => { if (own()) entry.maxTime = Math.max(entry.maxTime, this.currentTime); });
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

/**
 * Document-order sequence of orchestration notices and assistant messages ('q' = the penguin
 * answer, 'a' = any other assistant message) and how many non-penguin assistant messages follow
 * the first report/finished notice: the automatic interpreting turn(s).
 */
async function chatShape(page: Page) {
  return page.evaluate((notice) => {
    const nodes = Array.from(document.querySelectorAll(`${notice}, [data-testid="message-assistant"]`));
    const kind = (node: Element) => (node.matches('[data-testid="message-assistant"]')
      ? (/penguin/i.test(node.textContent || '') ? 'q' : 'a')
      : (node.getAttribute('data-action') || 'n'));
    const sequence = nodes.map(kind);
    const firstEvent = sequence.findIndex((k) => k === 'report' || k === 'finished');
    return { sequence, assistantAfterEvents: firstEvent < 0 ? 0 : sequence.slice(firstEvent + 1).filter((k) => k === 'a').length };
  }, NOTICE);
}


// Worker-level launch options (fake microphone file) must be set at file level.
test.use({
  permissions: ['microphone'],
  launchOptions: {
    executablePath: process.env.OPENMATES_PROOF_CHROME || undefined,
    args: ['--disable-save-password-bubble', '--disable-features=AutofillSaveCardInfoToAccountSignedIn,PasswordImport',
      '--use-mock-keychain', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
      `--use-file-for-fake-audio-capture=${path.join(SPEECH_DIR, `${SLUG}.wav`)}`],
  },
});

test.describe(`real voice call orchestration: ${SLUG}`, () => {
  test.skip(!ENABLED, 'Dev-only real voice call: run through scripts/voice_call_orchestration_web_real_test.py.');
  // contract-test: direct surface=gui.web assertions=video-call.chat.orchestration-continuity,chat-orchestration.events.automatic-interpretation,chat-orchestration.spawn.brief-not-answered-here,chat-orchestration.skills.answer-own-questions-here
  test('a spawned chat reports back during a call and its report is interpreted once, spoken without cutting off other speech',
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
      await startNewChat(page, log);

      let started = false;
      try {
        const tCallStart = await now(page);
        await page.locator('[data-testid="voice-call-start"]:visible').first().click();
        started = true;
        // A fresh account sees the voice privacy notice first; it can appear after the click returns.
        const status = page.getByTestId('voice-call-status-text');
        const privacy = page.getByTestId('notification').filter({ hasText: 'Before your first voice call' });
        await expect.poll(async () => {
          if (await privacy.isVisible().catch(() => false)) {
            await privacy.getByRole('button', { name: 'Continue', exact: true }).click().catch(() => undefined);
          }
          return (await status.textContent().catch(() => ''))?.trim();
        }, { timeout: 60_000, message: 'call connected' }).toBe('Listening · You can speak now');
        const mute = page.getByTestId('voice-call-mute');
        await mute.click();  // the looped question is spoken only after the spawn request
        await expect(mute).toHaveAttribute('aria-pressed', 'true');

        // Typed during the call: start the spawned chat. The brief's search wording stays in the brief.
        await sendMessage(page, SPAWN_REQUEST, log, screenshot, 'spawn-request');
        await expect(page).toHaveURL(/chat-id=[0-9a-f]{8}-/, { timeout: 30_000 });
        const startedNotice = page.locator(`${NOTICE}[data-action="started"]`);
        await expect(startedNotice.first()).toBeVisible({ timeout: 240_000 });
        await expect.poll(() => page.getByTestId('chat-item').count(), { timeout: 60_000, message: 'spawned chat in the sidebar' })
          .toBeGreaterThan(chatsBefore + 1);  // the creator chat and the spawned chat
        await expect.poll(() => page.getByTestId('message-assistant').count(), { timeout: 120_000,
          message: 'creator turn confirmed the start' }).toBeGreaterThanOrEqual(1);
        // The bar shows "Microphone muted" only while nothing is spoken and no turn is working.
        await expect(status, 'start confirmation spoken, call idle').toHaveText('Microphone muted', { timeout: 150_000 });
        await snap(page, testInfo, `${SLUG}-01-started-notice`);

        // An unrelated spoken question while the spawned chat works is answered here.
        await mute.click();
        await expect(mute).toHaveAttribute('aria-pressed', 'false');
        const heardB = page.getByTestId('message-user').filter({ hasText: /penguin/i });
        await expect(heardB).toHaveCount(1, { timeout: 240_000 });  // at most one loop of the file
        log(`heard: ${(await heardB.first().textContent())?.trim()}`);
        if (await mute.isEnabled()) {
          await mute.click();  // the looped file must not repeat the question
          await expect(mute).toHaveAttribute('aria-pressed', 'true');
        }
        const answer = page.getByTestId('message-assistant').filter({ hasText: /penguin/i });
        await expect(answer.first()).toBeVisible({ timeout: 150_000 });
        await expect(answer.first(), 'the question is answered here, not written to the spawned chat')
          .not.toContainText('Used the OpenMates app');
        await snap(page, testInfo, `${SLUG}-02-question-answer`);

        // The spawned chat's report / finished event arrives in the creator chat.
        await expect(page.locator(`${NOTICE}[data-action="report"], ${NOTICE}[data-action="finished"]`).first())
          .toBeVisible({ timeout: 420_000 });
        const tEvents = (await recorded(page)).eventsAt;
        expect(tEvents, 'events seen by the page recorder').toBeGreaterThan(0);
        log(`event notices: ${JSON.stringify((await chatShape(page)).sequence)}`);

        // Exactly one interpreting assistant message follows the events, and it is spoken.
        await expect.poll(async () => (await chatShape(page)).assistantAfterEvents, { timeout: 240_000,
          message: 'one automatic interpreting assistant message after the events' }).toBeGreaterThanOrEqual(1);
        await expect.poll(async () => {
          const speech = (await recorded(page)).played.filter((e) => e.playing && e.startedAt >= tCallStart && !e.src.includes(ACK_ROOT));
          return speech.length >= 2 && speech.every((e) => e.endedAt > e.startedAt);
        }, { timeout: 240_000, message: 'question answer and interpretation audio played to the end' }).toBe(true);
        const shape = await chatShape(page);
        expect(shape.assistantAfterEvents, 'exactly one automatic interpreting turn').toBe(1);
        await snap(page, testInfo, `${SLUG}-03-events-and-interpretation`);

        // Never cut off: every assistant speech in the call starts only after the previous one ended.
        const speech = (await recorded(page)).played.filter((e) => e.playing && e.startedAt >= tCallStart && !e.src.includes(ACK_ROOT))
          .sort((a, b) => a.startedAt - b.startedAt);
        log(`played audio: ${JSON.stringify(speech.map((e) => ({ start: Math.round(e.startedAt), end: Math.round(e.endedAt),
          seconds: Math.round(e.maxTime * 10) / 10 })))}`);
        for (let k = 1; k < speech.length; k += 1) {
          expect(speech[k].startedAt, `speech ${k} starts after speech ${k - 1} ended`).toBeGreaterThanOrEqual(speech[k - 1].endedAt);
        }
        log(`interpretation: assistant messages after events ${shape.assistantAfterEvents}, call speech tracks ${speech.length}`);
        expect(speech.every((e) => e.maxTime > 1), 'every speech track really advances').toBe(true);
        expect(speech.some((e) => e.startedAt >= tEvents), 'the interpretation is spoken in the call after the events arrived').toBe(true);

        // No second automatic answer for the same events.
        await page.waitForTimeout(30_000);
        expect((await chatShape(page)).assistantAfterEvents, 'no second automatic answer within 30 s').toBe(1);
        expect(speech.length, 'no extra speech without a new answer').toBe(
          (await recorded(page)).played.filter((e) => e.playing && e.startedAt >= tCallStart && !e.src.includes(ACK_ROOT)).length);

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
