/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Real-inference web proof of the Life coaching "Life compass" focus.
 *
 * A synthetic burned-out founder ("Ana", invented) describes her situation. The focus
 * activates, asks one question at a time, reflects issues and strengths, agrees on small
 * steps that become Tasks and, after a clear yes, saves a "Life compass" Memory. In a later
 * chat the Memory is approved in the permission dialog and the reply follows up on the
 * agreed steps. The user's replies are fixed (no persona model), chosen by what the last
 * reply asks, so a failure points at the product, not at role-play.
 * Runs in the `real_inference` CI group (isolated per-run stack, no mocks) and manually
 * against dev through scripts/life_compass_focus_web_real_test.py.
 */
export {};

import type { Page } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const {
  deleteActiveChat, focusMessageEditor, loginToTestAccount, sendMessage, startNewChat, waitForAssistantMessage,
} = require('./helpers/chat-test-helpers');
const { requireRealInference } = require('./helpers/real-inference-guard');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { expandActivity } = require('./helpers/assistant-activity');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const proofContract = defineVideoProof({
  id: 'life-compass-focus-web-real',
  title: 'Life compass turns an exhausted founder\'s situation into agreed steps, Tasks and a consented Memory',
  surface: 'web',
  devices: ['web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'focus-active', text: 'Life compass activates and asks one gentle question.', checkpoint: '01-focus-active', devices: ['web-laptop'] },
    { id: 'reflect', text: 'It names the biggest issues and strengths and asks if that is right.', checkpoint: '02-issues-and-strengths', devices: ['web-laptop'] },
    { id: 'tasks', text: 'The steps the user picked become Tasks.', checkpoint: '03-steps-as-tasks', devices: ['web-laptop'] },
    { id: 'memory', text: 'After a clear yes, the context is saved as an encrypted Memory.', checkpoint: '04-memory-saved', devices: ['web-laptop'] },
    { id: 'follow-up', text: 'A week later, a new chat loads the approved Memory and asks how the steps went.', checkpoint: '05-follow-up', devices: ['web-laptop'] },
  ],
  assertions: [
    { id: 'life_compass.active', checkpoint: '01-focus-active', visual: 'The Life compass focus bar is activated above the first reply.', devices: ['web-laptop'] },
    { id: 'life_compass.reflect', checkpoint: '02-issues-and-strengths', visual: 'The reply lists issues and strengths and asks for confirmation.', devices: ['web-laptop'] },
    { id: 'life_compass.tasks', checkpoint: '03-steps-as-tasks', visual: 'Created Tasks for the agreed steps are visible in the chat.', devices: ['web-laptop'] },
    { id: 'life_compass.memory', checkpoint: '04-memory-saved', visual: 'The notice "The assistant saved a memory: Life compass" is visible.', devices: ['web-laptop'] },
    { id: 'life_compass.follow_up', checkpoint: '05-follow-up', visual: 'The later reply recalls the agreed steps after the Memory was approved.', devices: ['web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const TURN_TIMEOUT = 300_000;
const MAX_TURNS = 8;
const FOCUS_ID = 'life_coaching-life_compass';
const MEMORY_TITLE = 'Life compass';
const MODEL_QUERY = 'gemini-3.8-flash';
const MODEL_NAME = /Gemini 3\.8 Flash/i;
const NOTICE = '[data-testid="context-entry-event"][data-kind="memory"][data-source="assistant"]';

const OPENING = "I run a small software startup, I'm exhausted all the time and honestly I don't enjoy my life "
  + "anymore. Everything is work. I don't even know where to start changing that.";
const FACTS = "I work about 70 hours a week, sleep around five hours and answer emails until midnight. I used to "
  + "go climbing but haven't in a year. I barely see my partner. I'm proud of my team and that I never give up.";
const CONFIRM = "Yes, that's right.";
const CHOOSE = 'I like the first two steps. Please add them as todos for me.';
const REMEMBER = 'Yes, please remember that for next time.';
const MORE = "That's all for now, let's continue.";
const FOLLOW_UP = "Hi again. It's been a week since we talked about my exhaustion and the steps we agreed. "
  + 'I went climbing on Saturday and loved it, but I still answered emails late most evenings. How do we continue?';

async function insertModelMention(page: Page): Promise<void> {
  await page.keyboard.insertText(`@${MODEL_QUERY}`);
  const dropdown = page.getByTestId('mention-dropdown');
  await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: MODEL_NAME }).first())
    .toBeVisible({ timeout: 10_000 });
  await page.keyboard.press('Tab');
  await expect(dropdown).not.toBeVisible({ timeout: 3_000 });
}

async function sendWithModel(page: Page, prompt: string, kind: string): Promise<void> {
  const editor = page.getByTestId('message-editor');
  await focusMessageEditor(editor);
  await insertModelMention(page);
  await sendMessage(page, ` ${prompt}`, undefined, undefined, kind, { preserveExistingContent: true });
}

/** The turn is over when the stop button and typing indicator stay hidden for 5 s. */
async function waitForIdle(page: Page): Promise<void> {
  const busy = page.locator('[data-testid="stop-processing-button"]:visible, [data-testid="typing-indicator"]:visible');
  let idleSince = 0;
  await expect.poll(async () => {
    if (await busy.count() > 0) {
      idleSince = 0;
      return false;
    }
    idleSince ||= Date.now();
    return Date.now() - idleSince >= 5_000;
  }, { timeout: TURN_TIMEOUT, intervals: [1_000] }).toBe(true);
}

/**
 * Assistant-saved Memories load as "ask first": any turn, also in the chat that just saved one,
 * can pause on the permission dialog. The user includes Life compass, as a real user would.
 */
async function includeMemoryIfAsked(page: Page): Promise<void> {
  const dialog = page.getByTestId('app-settings-memories-permission-dialog');
  if (!(await dialog.isVisible().catch(() => false))) return;
  await expect(dialog.getByText(MEMORY_TITLE, { exact: true })).toBeVisible({ timeout: 10_000 });
  await dialog.getByTestId('btn-include').click();
}

async function waitForTurn(page: Page, assistantsBefore: number): Promise<void> {
  await expect.poll(async () => {
    await includeMemoryIfAsked(page);
    return page.getByTestId('message-assistant').count();
  }, { timeout: TURN_TIMEOUT, intervals: [2_000] }).toBeGreaterThan(assistantsBefore);
  await waitForAssistantMessage(page, { timeout: TURN_TIMEOUT });
  await waitForIdle(page);
  const generatedBy = page.getByTestId('message-assistant').last().getByTestId('generated-by');
  await expect(generatedBy).toBeVisible({ timeout: 120_000 });
  await expect(generatedBy).toContainText(MODEL_NAME);
}

/** Created Tasks show up as a tasks embed or as "created" Task event lines in the chat. */
async function createdTaskCount(page: Page): Promise<number> {
  await expandActivity(page);
  const embeds = await page.locator('[data-testid="embed-preview"][data-app-id="tasks"]').count();
  const events = await page.getByTestId('system-message-text').filter({ hasText: / created\b/ }).count();
  return embeds + events;
}

/** Picks the fixed reply that answers what the last assistant message asks. */
function nextReply(text: string, state: { facts: boolean; confirmed: boolean; tasks: boolean; saved: boolean }): string {
  if (!state.facts) return FACTS;
  // Answer the closing question only: earlier sentences ("pick up right here") are not questions.
  const question = (text.match(/[^.!?\n]*\?/g) ?? []).pop() ?? '';
  if (!state.saved && /remember|save|memory/i.test(question)) return REMEMBER;
  if (!state.confirmed && /(right|accurate|fit|correct|sound)\b/i.test(question)) {
    state.confirmed = true;
    return CONFIRM;
  }
  if (!state.tasks && /step|try|todo|task|realistic|start/i.test(question)) return CHOOSE;
  return MORE;
}

let proof: { checkpoint(id: string): Promise<void> } | null = null;

async function shot(page: Page, testInfo: any, name: string): Promise<void> {
  await proof?.checkpoint(name);
  const body = await page.screenshot();
  await testInfo.attach(name, { body, contentType: 'image/png' });
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
}

test.describe('Life compass focus: steps as Tasks, consented Memory, follow-up (real inference, dev only)', () => {
  test.describe.configure({ mode: 'serial', retries: 0 });
  test.use({ actionTimeout: 60_000, navigationTimeout: 60_000 });

  test.beforeAll(() => {
    requireRealInference('Real-inference Life compass proof', BASE_URL);
  });

  // contract-test: direct surface=gui.web assertions=life-compass.activation,life-compass.flow,life-compass.next-steps,life-compass.memory-consent,life-compass.follow-up
  test('activates, agrees steps as Tasks, saves a Memory on yes and follows up in a later chat', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(3_000_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1280, height: 900 });
    proof = createVideoProofRuntime(proofContract, {
      device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    await skipIfFeaturesDisabled(test, page, ['app:life_coaching', 'platform:tasks']);
    await loginToTestAccount(page);
    await startNewChat(page);

    let assistants = await page.getByTestId('message-assistant').count();
    await sendWithModel(page, OPENING, 'life-compass-opening');
    await waitForTurn(page, assistants);
    await expandActivity(page);
    await expect(page.locator(`[data-testid="focus-mode-bar"].activated[data-focus-id="${FOCUS_ID}"]`).first(),
      'Life compass activates for a request about life direction').toBeVisible({ timeout: 120_000 });
    await shot(page, testInfo, '01-focus-active');
    const firstChatId = await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id');
    expect(firstChatId).toBeTruthy();

    const notice = page.locator(NOTICE);
    const state = { facts: false, confirmed: false, tasks: false, saved: false };
    let reflected = false;
    for (let turn = 1; turn <= MAX_TURNS && !(state.tasks && state.saved); turn += 1) {
      const lastText = (await page.getByTestId('message-assistant').last().textContent()) ?? '';
      const reply = nextReply(lastText, state);
      state.facts = true;
      assistants = await page.getByTestId('message-assistant').count();
      await sendWithModel(page, reply, `life-compass-turn-${turn}`);
      await waitForTurn(page, assistants);
      const text = (await page.getByTestId('message-assistant').last().textContent()) ?? '';
      if (!reflected && /strength|good at|proud|stärke/i.test(text)) {
        reflected = true;
        await shot(page, testInfo, '02-issues-and-strengths');
      }
      if (!state.tasks && await createdTaskCount(page) > 0) {
        state.tasks = true;
        await page.getByTestId('message-assistant').last().scrollIntoViewIfNeeded();
        await shot(page, testInfo, '03-steps-as-tasks');
      }
      if (!state.saved && await notice.count() > 0) {
        state.saved = true;
        await expect(notice.first().getByTestId('context-entry-event-label'))
          .toHaveText(`The assistant saved a memory: ${MEMORY_TITLE}`);
        await notice.first().scrollIntoViewIfNeeded();
        await shot(page, testInfo, '04-memory-saved');
      }
    }
    expect(reflected, 'the focus named issues and strengths').toBe(true);
    expect(state.tasks, 'the agreed steps became Tasks').toBe(true);
    expect(state.saved, 'the Memory was saved after a clear yes').toBe(true);

    // Later chat: the saved Memory is asked for, approved, and the reply follows up on the steps.
    await startNewChat(page);
    assistants = await page.getByTestId('message-assistant').count();
    await sendWithModel(page, FOLLOW_UP, 'life-compass-follow-up');
    await waitForTurn(page, assistants);
    const followUp = (await page.getByTestId('message-assistant').last().textContent()) ?? '';
    expect(followUp, 'the follow-up reacts to the reported progress').toMatch(/climb|email/i);
    await shot(page, testInfo, '05-follow-up');
    await deleteActiveChat(page);

    // Cleanup: Undo the Memory in the first chat, then delete it.
    await page.goto(`/#chat-id=${encodeURIComponent(firstChatId as string)}`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', firstChatId as string, { timeout: 60_000 });
    await expect(notice.first()).toBeVisible({ timeout: 30_000 });
    await notice.first().getByTestId('context-entry-event-undo').click();
    await expect(notice.first()).toHaveAttribute('data-undone', 'true', { timeout: 20_000 });
    await deleteActiveChat(page);
  });
});
