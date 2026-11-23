/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Real-inference web proof of the Code app's "Write specification" focus.
 *
 * A bakery owner asks for a spec; the focus walks scope, requirements and design with
 * confirmations, drafts a Specification and Checks as embeds, asks for approval and only
 * then creates the Plan and its Tasks. The user's replies are fixed (no persona model), so
 * a failure points at the product, not at the test's role-play.
 * Runs in the `real_inference` CI group (isolated per-run stack, no mocks) and manually
 * against dev through scripts/spec_authoring_focus_web_real_test.py.
 */
export {};

import type { Locator, Page } from '@playwright/test';

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
  id: 'spec-authoring-focus-web-real',
  title: 'The Write specification focus turns a bakery idea into an approved Specification, Plan and Tasks',
  surface: 'web',
  devices: ['web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'focus-active', text: 'The Write specification focus is active and asks about the idea and its scope.', checkpoint: '01-focus-active-scope-questions', devices: ['web-laptop'] },
    { id: 'phase-confirmed', text: 'Each phase ends with a summary, open assumptions and a confirmation question.', checkpoint: '02-requirements-or-design', devices: ['web-laptop'] },
    { id: 'spec-drafted', text: 'The Specification and its acceptance Checks appear as embeds before any Plan.', checkpoint: '03-specification-and-checks', devices: ['web-laptop'] },
    { id: 'spec-card-visible', text: 'The Specification card is visible in the answer without expanding the used-app summary, also at phone width.', checkpoint: '03b-specification-card-phone', devices: ['web-laptop'] },
    { id: 'spec-readable', text: 'The Specification opens as a readable document.', checkpoint: '04-specification-fullscreen', devices: ['web-laptop'] },
    { id: 'plan-and-tasks', text: 'After approval the Plan and its Tasks are created.', checkpoint: '05-plan-and-tasks', devices: ['web-laptop'] },
  ],
  assertions: [
    { id: 'spec_focus.active', checkpoint: '01-focus-active-scope-questions', visual: 'The focus bar for Write specification is activated above the first reply.', devices: ['web-laptop'] },
    { id: 'spec_focus.phase_summary', checkpoint: '02-requirements-or-design', visual: 'The reply lists requirements or design decisions and asks the user to confirm.', devices: ['web-laptop'] },
    { id: 'spec_focus.spec_and_checks', checkpoint: '03-specification-and-checks', visual: 'A Specification embed and at least one Check embed are visible, with no Plan yet.', devices: ['web-laptop'] },
    { id: 'spec_focus.spec_card_visible', checkpoint: '03b-specification-card-phone', visual: 'At phone width the Specification card shows in the answer below a collapsed used-app summary.', devices: ['web-laptop'] },
    { id: 'spec_focus.spec_fullscreen', checkpoint: '04-specification-fullscreen', visual: 'The Specification fullscreen shows requirements with ids.', devices: ['web-laptop'] },
    { id: 'spec_focus.plan_tasks', checkpoint: '05-plan-and-tasks', visual: 'A Plan embed and created Tasks follow the approval message.', devices: ['web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const TURN_TIMEOUT = 420_000;
const MAX_TURNS = 10;
const FOCUS_ID = 'code-write_specification';
// Real-inference proofs pin Gemini 3.8 Flash and fail when another model answered.
const MODEL_QUERY = 'gemini-3.8-flash';
const MODEL_NAME = /Gemini 3\.8 Flash/i;

const OPENING = "Hi! I run a small sourdough bakery in Leipzig. I'd like customers to order bread online before "
  + "they come in. Can you help me write a proper specification for that before anyone builds it?";
const FACTS = "Here is everything at once. Customers are locals and regulars ordering on their phones. They pick "
  + "up in the shop between 7:00 and 13:00, no delivery. They pay online by card when ordering. Orders close at "
  + "18:00 the day before pickup because the dough is started then. We bake at most 40 loaves of each kind per "
  + "day: country loaf, rye and spelt. Staff need a simple list of the day's orders to tick off at the counter. "
  + "Out of scope for now: delivery, loyalty points, cakes. One specification is fine.";
const CONFIRM = 'Yes, that is right. Please go on to the next step.';
const APPROVE = 'Yes, I approve the Specification and its Checks as drafted. Please create the Plan and the Tasks.';

/** Inserts the Gemini 3.8 Flash mention through the dropdown at the caret. */
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

/** The turn is over when nothing is in flight for 5 s: no stop button, typing indicator or "Working"
 * placeholder, no streaming answer, and no user message still sending or queued. A focus phase change can
 * start a follow-up answer after a short pause, so the stop button alone ends the turn too early. */
async function waitForIdle(page: Page): Promise<void> {
  const busy = page.locator([
    '[data-testid="stop-processing-button"]:visible',
    '[data-testid="typing-indicator"]:visible',
    '[data-testid="pending-assistant-response"]',
    '[data-testid="message-assistant"][data-streaming="true"]',
    '[data-testid="message-user"][data-status="sending"]',
    '[data-testid="queued-followup-controls"]',
  ].join(', '));
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

/** Id of the newest rendered assistant message. The chat renders a window of messages, so with long
 * replies an older message unmounts while a new one mounts and the count alone can stay the same. */
async function lastAssistantId(page: Page): Promise<string | null> {
  const ids = await page.getByTestId('message-assistant').evaluateAll((elements) =>
    elements.map((element) => element.getAttribute('data-message-id') ?? '').filter(Boolean));
  return ids.at(-1) ?? null;
}

async function waitForTurn(page: Page, lastBefore: string | null): Promise<void> {
  await expect.poll(async () => {
    const last = await lastAssistantId(page);
    return last !== null && last !== lastBefore;
  }, { timeout: TURN_TIMEOUT, intervals: [2_000] }).toBe(true);
  await waitForAssistantMessage(page, { timeout: TURN_TIMEOUT });
  await waitForIdle(page);
  const generatedBy = page.getByTestId('message-assistant').last().getByTestId('generated-by');
  await expect(generatedBy).toBeVisible({ timeout: 120_000 });
  await expect(generatedBy).toContainText(MODEL_NAME);
}

/**
 * Plans skill results by their components' own test ids: the shared preview shell
 * renders them under other app ids (the Specification card as "design", the Check
 * card as "code"), so data-app-id="plans" never matches.
 */
const PLANS_EMBED_TESTIDS: Record<'specification' | 'check' | 'create', string> = {
  specification: 'specification-embed-card',
  check: 'check-preview',
  create: 'plan-embed-preview',
};

function plansEmbed(page: Page, skillId: keyof typeof PLANS_EMBED_TESTIDS): Locator {
  return page.getByTestId(PLANS_EMBED_TESTIDS[skillId]);
}

/** Hand-off Tasks show up as a tasks embed or as "created" Task event lines in the chat. */
async function createdTaskCount(page: Page): Promise<number> {
  await expandActivity(page);
  const embeds = await page.locator('[data-testid="embed-preview"][data-app-id="tasks"]').count();
  const events = await page.getByTestId('system-message-text').filter({ hasText: / created\b/ }).count();
  return embeds + events;
}

let proof: { checkpoint(id: string): Promise<void> } | null = null;

async function shot(page: Page, testInfo: any, name: string): Promise<void> {
  await proof?.checkpoint(name);
  const body = await page.screenshot();
  await testInfo.attach(name, { body, contentType: 'image/png' });
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
}

test.describe('Write specification focus guides an idea to an approved Spec, Plan and Tasks (real inference, dev only)', () => {
  test.describe.configure({ mode: 'serial', retries: 0 });
  test.use({ actionTimeout: 60_000, navigationTimeout: 60_000 });

  test.beforeAll(() => {
    requireRealInference('Real-inference Specification focus proof', BASE_URL);
  });

  // contract-test: direct surface=gui.web assertions=focus-modes.guided-spec-authoring
  test('phases with confirmations, Specification and Checks before approval, Plan and Tasks after', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(3_600_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1280, height: 900 });
    proof = createVideoProofRuntime(proofContract, {
      device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    await skipIfFeaturesDisabled(test, page, ['platform:plans', 'platform:tasks']);
    await loginToTestAccount(page);
    await startNewChat(page);

    let assistants = await lastAssistantId(page);
    await sendWithModel(page, OPENING, 'spec-opening');
    await waitForTurn(page, assistants);

    await expandActivity(page);
    const focusBar = page.locator(`[data-testid="focus-mode-bar"][data-focus-id="${FOCUS_ID}"]`);
    await expect(focusBar.first(), 'the Write specification focus is offered').toBeVisible({ timeout: 120_000 });
    await expect(page.locator(`[data-testid="focus-mode-bar"].activated[data-focus-id="${FOCUS_ID}"]`).first())
      .toBeVisible({ timeout: 60_000 });
    await shot(page, testInfo, '01-focus-active-scope-questions');

    let approvedAt = -1;
    let specShown = false;
    for (let turn = 1; turn <= MAX_TURNS; turn += 1) {
      // XUDR8: the drafted Specification must be visible in the answer without
      // expanding "Used the Plans app", so count it in the collapsed view first.
      const specCount = await page.getByTestId('assistant-activity-answer-cards')
        .getByTestId(PLANS_EMBED_TESTIDS.specification).count();
      if (specCount > 0 && !specShown) {
        // Phone view of the collapsed answer: the card shows below "Used the Plans app".
        const viewport = page.viewportSize();
        await page.setViewportSize({ width: 390, height: 844 });
        await page.getByTestId('assistant-activity-answer-cards')
          .getByTestId(PLANS_EMBED_TESTIDS.specification).last().scrollIntoViewIfNeeded();
        await page.waitForTimeout(1_000);
        await shot(page, testInfo, '03b-specification-card-phone');
        if (viewport) await page.setViewportSize(viewport);
      }
      await expandActivity(page);
      const lastText = (await page.getByTestId('message-assistant').last().textContent()) ?? '';
      if (specCount > 0 && !specShown) {
        specShown = true;
        expect(await plansEmbed(page, 'create').count(), 'no Plan before the Specification is approved').toBe(0);
        expect(await createdTaskCount(page), 'no Tasks before the Specification is approved').toBe(0);
        await expect(plansEmbed(page, 'check').first(), 'acceptance Checks are drafted with the Specification')
          .toBeVisible({ timeout: 30_000 });
        await shot(page, testInfo, '03-specification-and-checks');
        await plansEmbed(page, 'specification').last().click();
        await page.waitForTimeout(2_000);
        await shot(page, testInfo, '04-specification-fullscreen');
        await page.keyboard.press('Escape');
      }
      // Approval may be asked again in later replies, after the Specification's reply.
      const asksApproval = specShown && /approv/i.test(lastText);
      let reply = turn === 1 ? FACTS : CONFIRM;
      if (asksApproval && approvedAt < 0) {
        reply = APPROVE;
        approvedAt = turn;
      }
      assistants = await lastAssistantId(page);
      await sendWithModel(page, reply, `spec-turn-${turn}`);
      await waitForTurn(page, assistants);
      if (turn === 2) await shot(page, testInfo, '02-requirements-or-design');
      if (approvedAt > 0) {
        await expandActivity(page);
        if (await plansEmbed(page, 'create').count() > 0) break;
      }
    }

    expect(approvedAt, 'the assistant asked for approval of the drafted Specification').toBeGreaterThan(0);
    await expandActivity(page);
    await expect(plansEmbed(page, 'create').first(), 'the Plan is created after approval').toBeVisible({ timeout: TURN_TIMEOUT });
    await expect.poll(() => createdTaskCount(page), { timeout: TURN_TIMEOUT, intervals: [2_000] })
      .toBeGreaterThan(0);
    await page.getByTestId('message-assistant').last().scrollIntoViewIfNeeded();
    await shot(page, testInfo, '05-plan-and-tasks');
    await deleteActiveChat(page);
  });
});
