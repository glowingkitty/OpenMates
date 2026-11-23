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
 *  - a turn that pauses for a Memory approval still answers aloud after Include (memory scenario);
 *  - a form started by a typed message continues by voice in the same chat: the spoken answer is
 *    filled through the same Browse session and the spoken reply asks one question (form scenario;
 *    the form link lives outside the repository in VOICE_CALL_FORM_PROMPT);
 *  - with Projects switched off as on production, the spoken turn is still sent and answered
 *    (production-features scenario, issue F74ES);
 *  - no error or warning notification appears, in particular not
 *    "canonical embed revision changed or is immutable".
 * Held out of isolated CI: real provider inference with the personal dev account.
 */
import type { Page, TestInfo } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const { expect, test: playwrightTest } = require('@playwright/test');
const { withProofAudio } = require('./helpers/proof-audio');
const {
  deleteActiveChat, loginToTestAccount, sendMessage, setChatSidebarOpen, startNewChat, waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const { expandActivity } = require('./helpers/assistant-activity');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const ENABLED = process.env.VOICE_CALL_REAL_DEV === '1';
const SPEECH_DIR = process.env.VOICE_CALL_REAL_SPEECH_DIR || '';
// Chromium takes its fake microphone file at launch, and launch options cannot
// differ per describe group, so one run covers one scenario (the runner's --scenario).
const SCENARIO = process.env.VOICE_CALL_REAL_SCENARIO || '';
const ARTIFACTS = 'artifacts';
// Proof videos carry the call's sound: the spoken question (fake microphone), the Mate's speech
// and every chime, muxed in sync into video-with-audio.webm (tests/helpers/proof-audio.ts).
const test = withProofAudio(playwrightTest);

interface Scenario {
  slug: string;
  question: string;
  heard: RegExp;
  answer: RegExp;
  videos: boolean;
  /** Saves an ask-first Memory by a typed message first; the spoken question then needs it. */
  memory?: boolean;
  /** Starts filling a web form by a typed message first; the call continues it in that chat. */
  form?: boolean;
  /** An earlier spoken turn in the same call, answered before `question` is spoken. */
  firstTurn?: { heard: RegExp; answer: RegExp };
  /** Runs with Projects switched off the way production answers (404 FEATURE_DISABLED). */
  projectsDisabled?: boolean;
}

// The typed request with the form link (kept out of the repository; passed by the runner).
const FORM_PROMPT = process.env.VOICE_CALL_FORM_PROMPT || '';
const BROWSE_EMBED = '[data-testid="embed-preview"][data-app-id="web"][data-skill-id="browse"]';

const MEMORY_TITLE = 'Job application profile';
const MEMORY_SAVE_PROMPT = `Save a memory titled "${MEMORY_TITLE}" for my job applications: I work as a sales lead at `
  + 'Example Retail GmbH. Ask me before using it in later chats.';
const MEMORY_NOTICE = '[data-testid="context-entry-event"][data-kind="memory"][data-source="assistant"]';

// The runner generates <slug>.wav for each scenario from `question`; keep both lists in sync
// through scripts/voice_call_web_real_test.py SCENARIOS.
const SCENARIOS: Scenario[] = [
  { slug: 'capital', question: 'What is the capital of France?', heard: /capital of France/i,
    answer: /Paris/i, videos: false },
  // F74ES: production has Projects switched off, so every Project route answers 404
  // FEATURE_DISABLED. A spoken turn must still be sent and answered aloud.
  { slug: 'production-features', question: 'What is the capital of France?', heard: /capital of France/i,
    answer: /Paris/i, videos: false, projectsDisabled: true },
  { slug: 'black-hole', question: 'How does a black hole work? Show me a video example.', heard: /black hole/i,
    answer: /black hole|gravity|event horizon/i, videos: true },
  // The reported DGZVY failure: the call turn pauses for a Memory approval and the continuation
  // must still be spoken in the Mate's voice.
  { slug: 'memory', question: 'Which employer should I mention in my cover letter? Use my saved job application profile memory.',
    heard: /cover letter/i, answer: /Example Retail/i, videos: false, memory: true },
  // Two consecutive spoken turns in one call, the second needing a Memory approval: every word of
  // both turns arrives, the Mate stays, and the included Memory shows by name.
  { slug: 'two-turns-memory', question: 'Which employer should I mention in my cover letter? Use my saved job application profile memory.',
    heard: /cover letter/i, answer: /Example Retail/i, videos: false, memory: true,
    firstTurn: { heard: /capital of France/i, answer: /Paris/i } },
  // Marco's "fill a form together" flow by voice: one spoken answer, one spoken question back.
  { slug: 'form', question: "I'm not sure. What would you suggest? Please go with your suggestion.",
    heard: /suggest/i, answer: /\?/, videos: false, form: true },
];

/** The approved turn names every included Memory by its title (never the generic "Memories" label). */
async function expectIncludedMemoryTitles(page: Page, log: (message: string) => void, when: string): Promise<void> {
  const titles = page.getByTestId('included-memory-pill').getByTestId('included-memory-title');
  await expect(titles.filter({ hasText: MEMORY_TITLE })).toHaveCount(1, { timeout: 20_000 });
  const shown = (await titles.allTextContents()).map((text) => text.trim());
  log(`included memories ${when}: ${shown.join(', ')}`);
  expect(shown.filter((title) => title === 'Memories'), `every included Memory is titled ${when}`).toEqual([]);
}

/** Settings > Memories rows titled MEMORY_TITLE (left over from an aborted run when non-empty). */
async function leftoverMemoryRows(page: Page) {
  await page.getByTestId('profile-container').click();
  const menu = page.locator('[data-testid="settings-menu"].visible');
  await expect(menu).toBeVisible({ timeout: 10_000 });
  await menu.getByRole('menuitem', { name: /^Memories$/i }).first().click();
  const editor = page.locator('[data-testid="memories-editor"][data-source="personal"]');
  await expect(editor).toBeVisible({ timeout: 20_000 });
  return editor.getByTestId('memory-row').filter({ hasText: MEMORY_TITLE });
}

/** Typed chat in which the assistant saves the ask-first Memory; returns that chat's id. */
async function saveMemoryFirst(page: Page, log: any, screenshot: any): Promise<string> {
  const leftovers = await leftoverMemoryRows(page);
  expect(await leftovers.count(), `Leftover "${MEMORY_TITLE}" Memory; delete it in Settings > Memories`).toBe(0);
  await page.getByTestId('icon-button-close').click();
  await startNewChat(page, log);
  await sendMessage(page, MEMORY_SAVE_PROMPT, log, screenshot, 'save-job-application-profile');
  await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
  await expect(page.locator(MEMORY_NOTICE)).toHaveCount(1, { timeout: 90_000 });
  const chatId = await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id');
  expect(chatId).toBeTruthy();
  log('memory saved for the voice question');
  await startNewChat(page, log);
  return chatId as string;
}

/** Typed first turn that opens the form with Browse; the call then continues in this chat. */
async function startFormFirst(page: Page, log: any, screenshot: any) {
  await startNewChat(page, log);
  await sendMessage(page, FORM_PROMPT, log, screenshot, 'form-typed-request');
  await waitForAssistantMessage(page, { which: 'last', timeout: 300_000, logCheckpoint: log });
  await expect(page.getByTestId('stop-processing-button')).toHaveCount(0, { timeout: 300_000 });
  await expandActivity(page);
  await expect(page.getByTestId('message-assistant').last().locator(BROWSE_EMBED).first(),
    'the typed form request opens the form with Browse').toBeVisible({ timeout: 30_000 });
  log('form opened with Browse by the typed request');
}

/** Undo the save notice so reruns start clean, then delete that typed chat. */
async function removeSavedMemory(page: Page, chatId: string, log: any, screenshot: any) {
  await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`), { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId, { timeout: 60_000 });
  const notice = page.locator(MEMORY_NOTICE);
  await expect(notice).toHaveCount(1, { timeout: 30_000 });
  if (await notice.getAttribute('data-undone') !== 'true') {
    await notice.getByTestId('context-entry-event-undo').click();
    await expect(notice).toHaveAttribute('data-undone', 'true', { timeout: 20_000 });
  }
  log('saved memory removed');
  await deleteActiveChat(page, log, screenshot, 'memory-save-chat-cleanup');
}

/** Answers like production, where Projects are switched off: the feature list says so and every
 * Project route returns 404 FEATURE_DISABLED (backend_config.yml). Context routes also cover the
 * shared Worker's requests, which is where the Rust core reads the chat's Project focus. */
async function switchProjectsOff(page: Page, projectRequests: string[]): Promise<void> {
  await page.context().route('**/v1/features/availability', async (route) => {
    const response = await route.fetch();
    if (!response.ok()) throw new Error(`Feature availability failed (${response.status()}).`);
    const data = await response.json();
    await route.fulfill({ response, json: { ...data,
      disabled: [...new Set([...(data.disabled ?? []), 'platform:projects'])] } });
  });
  await page.context().route('**/v1/projects/**', (route) => {
    projectRequests.push(new URL(route.request().url()).pathname);
    return route.fulfill({ status: 404, json: { detail: 'FEATURE_DISABLED' } });
  });
}

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

test.use({
  permissions: ['microphone'],
  launchOptions: {
    executablePath: process.env.OPENMATES_PROOF_CHROME || undefined,
    args: ['--disable-save-password-bubble', '--disable-features=AutofillSaveCardInfoToAccountSignedIn,PasswordImport',
      '--use-mock-keychain', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
      ...(SCENARIO ? [`--use-file-for-fake-audio-capture=${path.join(SPEECH_DIR, `${SCENARIO}.wav`)}`] : [])],
  },
});

for (const scenario of SCENARIOS) {
  test.describe(`real voice call: ${scenario.slug}`, () => {
    test.skip(!ENABLED, 'Dev-only real voice call: run through scripts/voice_call_web_real_test.py.');
    test.skip(ENABLED && scenario.slug !== SCENARIO, `This run speaks the ${SCENARIO || '(none)'} question only.`);

    // contract-test: direct surface=gui.web assertions=video-call.chat.transcripts,video-call.audio.localized-waiting,video-call.audio.spoken-rich-response
    test(`a spoken question in a new chat is transcribed, answered aloud${scenario.videos ? ' with videos' : ''} and raises no error`,
      async ({ page }: { page: Page }, testInfo: TestInfo) => {
        test.skip(Boolean(scenario.form) && !FORM_PROMPT, 'VOICE_CALL_FORM_PROMPT names no form request.');
        test.setTimeout(scenario.form ? 900_000 : 420_000);
        expect(getTestAccount().email, 'test account credentials').toBeTruthy();
        expect(fs.existsSync(path.join(SPEECH_DIR, `${scenario.slug}.wav`)), 'generated speaker audio').toBe(true);
        await page.setViewportSize({ width: 1400, height: 1000 });
        const log = createSignupLogger(`VOICE_REAL_${scenario.slug.toUpperCase()}`);
        const screenshot = createStepScreenshotter(log);
        const consoleErrors: string[] = [];
        // The last browser console lines, printed when the scenario fails (the run may be in a remote sandbox).
        const consoleTail: string[] = [];
        page.on('console', (message) => {
          if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300));
          consoleTail.push(`[${message.type()}] ${message.text().slice(0, 300)}`);
          if (consoleTail.length > 80) consoleTail.shift();
        });
        page.on('pageerror', (error) => consoleTail.push(`[pageerror] ${String(error).slice(0, 300)}`));
        // Acknowledgement clips are fetched and played from blob: URLs, so their path is only visible
        // in the server event that announces them and in the clip download.
        const acknowledgementUrls: string[] = [];
        const clipDownloads: string[] = [];
        page.on('websocket', (socket) => socket.on('framereceived', ({ payload }) => {
          if (typeof payload !== 'string' || !payload.includes('assistant_speech_acknowledgement')) return;
          const frame = JSON.parse(payload) as { type?: string; payload?: { audio_url?: string } };
          if (frame.type === 'assistant_speech_acknowledgement') acknowledgementUrls.push(String(frame.payload?.audio_url ?? ''));
        }));
        page.on('request', (request) => { if (request.url().includes(ACK_ROOT)) clipDownloads.push(new URL(request.url()).pathname); });
        await page.addInitScript(installRecorders);
        const projectRequests: string[] = [];
        if (scenario.projectsDisabled) await switchProjectsOff(page, projectRequests);

        await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
        await loginToTestAccount(page, log, screenshot);
        await setChatSidebarOpen(page, false, log);
        let started = false;
        let memoryChatId: string | null = null;
        try {
          if (scenario.memory) memoryChatId = await saveMemoryFirst(page, log, screenshot);
          if (scenario.form) await startFormFirst(page, log, screenshot);
          let repliesBeforeCall = await page.getByTestId('message-assistant').count();
          const microphone = await page.evaluate(async () => {
            const devices = await navigator.mediaDevices.enumerateDevices();
            return devices.filter((device) => device.kind === 'audioinput').length;
          });
          log(`audio input devices: ${microphone}`);
          await page.locator('[data-testid="voice-call-start"]:visible').click();
          started = true;
          const privacy = page.getByTestId('notification').filter({ hasText: 'Before your first voice call' });
          // A new account sees this notice before its first call; isVisible() does not wait, so wait
          // for either the notice or the live status.
          const listening = page.getByTestId('voice-call-status-text').filter({ hasText: 'Listening · You can speak now' });
          await expect(privacy.or(listening).first()).toBeVisible({ timeout: 45_000 });
          if (await privacy.isVisible()) {
            await privacy.getByRole('button', { name: 'Continue', exact: true }).click();
            log('voice processing acknowledgement saved for this account');
          }
          await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now', { timeout: 45_000 });
          await expect(page.getByTestId('voice-call-bar')).toBeVisible();
          const timerAtStart = await timerSeconds(page);
          await snap(page, testInfo, `${scenario.slug}-01-listening`);

          if (scenario.firstTurn) {
            // First turn: heard in full and answered before the second question is spoken.
            const firstMessage = page.getByTestId('message-user').filter({ hasText: scenario.firstTurn.heard });
            await expect(firstMessage).toHaveCount(1, { timeout: 60_000 });
            const firstReply = page.getByTestId('message-assistant').filter({ hasText: scenario.firstTurn.answer });
            await expect(firstReply).toHaveCount(1, { timeout: 120_000 });
            const firstMate = (await firstReply.first().getByTestId('chat-mate-name').first()
              .textContent().catch(() => ''))?.trim();
            log(`first turn: heard "${(await firstMessage.first().textContent())?.trim()}"; mate ${firstMate || 'unknown'}`);
            await snap(page, testInfo, `${scenario.slug}-01b-first-turn`);
            repliesBeforeCall = await page.getByTestId('message-assistant').count();
          }
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
          if (scenario.memory) {
            // The turn pauses for the Memory approval; nothing is answered before it.
            const dialog = page.getByTestId('app-settings-memories-permission-dialog');
            await expect(dialog).toBeVisible({ timeout: 90_000 });
            await expect(dialog.getByText(MEMORY_TITLE, { exact: true })).toBeVisible({ timeout: 10_000 });
            await expect(page.getByTestId('message-assistant')).toHaveCount(repliesBeforeCall);
            await snap(page, testInfo, `${scenario.slug}-02b-memory-approval`);
            await dialog.getByTestId('btn-include').click();
            await expect(dialog).not.toBeVisible({ timeout: 10_000 });
            log('memory approval included');
          }

          // The spoken question gets its own new reply (the form chat already has one).
          await expect.poll(async () => page.getByTestId('message-assistant').count(), { timeout: 240_000 })
            .toBeGreaterThan(repliesBeforeCall);
          const reply = page.getByTestId('message-assistant').last();
          await expect(reply).toContainText(scenario.answer, { timeout: 240_000 });
          if (scenario.projectsDisabled) {
            // The turn really met production's answer: the core asked for the Project focus and got 404.
            log(`project requests answered FEATURE_DISABLED: ${projectRequests.join(', ')}`);
            expect(projectRequests.some((url) => url.endsWith('/v1/projects/focus/current')),
              'the spoken turn read the Project focus and was answered 404 FEATURE_DISABLED').toBe(true);
          }
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
          if (scenario.memory) await expectIncludedMemoryTitles(page, log, 'while spoken');
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
          log(`acknowledgements: ${JSON.stringify(acknowledgementUrls.map((url) => url.replace(/^https?:\/\/[^/]+/, '')))}; clip downloads: ${JSON.stringify(clipDownloads)}`);
          if (!scenario.form) {
            // Only a call that starts a new chat confirms with the system clip.
            expect(acknowledgementUrls.filter((url) => url.includes(`${ACK_ROOT}system/`)),
              'a new chat confirms once with the neutral system clip').toHaveLength(1);
            expect(clipDownloads.some((url) => url.includes(`${ACK_ROOT}system/`)), 'the system clip is fetched for playback').toBe(true);
          }
          const mateClips = [...acknowledgementUrls, ...clipDownloads].filter((url) => MATE_WAITING_CLIP.test(url));
          if (scenario.firstTurn) {
            // A follow-up turn may wait in the voice of the Mate that answers it, never another one.
            const mate = (await reply.getByTestId('chat-mate-name').first().textContent())?.trim().toLowerCase() ?? '';
            log(`follow-up turn mate: ${mate}; mate clips: ${JSON.stringify(mateClips)}`);
            expect(mate, 'the follow-up reply names its Mate').toBeTruthy();
            expect(mateClips.filter((url) => !url.includes(`${ACK_ROOT}${mate}/`)),
              'no waiting clip of a Mate other than the one that answers').toEqual([]);
          } else {
            expect(mateClips, 'no guessed Mate waiting clip').toHaveLength(0);
          }
          const speech = played.filter((entry) => !entry.src.includes(ACK_ROOT));
          expect(speech.length, 'the reply is played as audio').toBeGreaterThan(0);
          expect(Math.max(...speech.map((entry) => entry.maxTime)), 'reply audio really advances').toBeGreaterThan(1.5);

          const timerNow = await timerSeconds(page);
          log(`call duration: ${timerAtStart}s -> ${timerNow}s`);
          expect(timerNow, 'call duration counter runs').toBeGreaterThan(timerAtStart + 5);
          if (scenario.form) {
            await expandActivity(page);
            const browse = await reply.locator(BROWSE_EMBED).count();
            const questions = ((await reply.innerText()).match(/\?/g) || []).length;
            log(`form voice reply: browse embeds ${browse}; question marks ${questions}`);
            expect(browse, 'the spoken answer is filled through Browse in the same chat').toBeGreaterThan(0);
            expect(questions, 'one question per spoken turn').toBeLessThanOrEqual(2);
          }
          const generatedBy = reply.getByTestId('generated-by');
          if (await generatedBy.isVisible().catch(() => false)) log(`reply generated by: ${(await generatedBy.textContent())?.trim()}`);
          if (scenario.memory) await expectIncludedMemoryTitles(page, log, 'after the reply');
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
        } catch (error) {
          await snap(page, testInfo, `${scenario.slug}-failed`).catch(() => undefined);
          log(`browser console before the failure:\n${consoleTail.join('\n')}`);
          throw error;
        } finally {
          if (started) await page.getByTestId('voice-call-hangup').click({ timeout: 5_000 }).catch(() => undefined);
          const activeChatId = await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id')
            .catch(() => null);
          if (activeChatId !== memoryChatId) await deleteActiveChat(page, log, screenshot, `${scenario.slug}-cleanup`);
          if (memoryChatId) await removeSavedMemory(page, memoryChatId, log, screenshot);
        }
      });
  });
}
