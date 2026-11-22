/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Real-inference proof, in an isolated per-run CI stack, that an approved Specification hands its work to
 * sub-chats: one per open assumption and one per Task, all inheriting the Project focus, while the main
 * chat itself runs no research or code tools after the approval. Replies are fixed (no persona model).
 * Uses @Gemini-3.8-Flash and fails when another model answered.
 */
export {};

import type { Locator, Page } from '@playwright/test';

const { test, expect } = require('./console-monitor');
const {
  deleteActiveChat, focusMessageEditor, loginToTestAccount, sendMessage, waitForAssistantMessage,
} = require('./helpers/chat-test-helpers');
const { getTestAccount } = require('./signup-flow-helpers');
const { expandActivity } = require('./helpers/assistant-activity');
const { naturalProjectName } = require('./helpers/project-names');
const { requireRealInference } = require('./helpers/real-inference-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const proofContract = defineVideoProof({
  id: 'spec-sub-chats-web-real',
  title: 'An approved Specification hands its assumption checks and Tasks to sub-chats in the Project',
  surface: 'web',
  devices: ['web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'spec-focus', text: 'In a Project chat, Write specification activates on top of the Project focus.', checkpoint: '01-write-specification-over-project', devices: ['web-laptop'] },
    { id: 'spec-drafted', text: 'The Specification and its Checks are drafted before approval.', checkpoint: '02-specification-and-checks', devices: ['web-laptop'] },
    { id: 'plan-sub-chats', text: 'After approval the Plan card appears and the main chat starts sub-chats instead of doing the work itself.', checkpoint: '03-plan-card-and-sub-chats', devices: ['web-laptop'] },
    { id: 'assumption-chat', text: 'An assumption sub-chat says which assumption it checks and keeps the Project focus.', checkpoint: '04-assumption-sub-chat', devices: ['web-laptop'] },
    { id: 'task-chat', text: 'A Task sub-chat says which Task it works on and keeps the Project focus.', checkpoint: '05-task-sub-chat', devices: ['web-laptop'] },
    { id: 'plan-links', text: 'The Plan lists open-chat buttons for its assumptions and Tasks.', checkpoint: '06-plan-open-chat-buttons', devices: ['web-laptop'] },
  ],
  assertions: [
    { id: 'spec_sub_chats.layered_focus', checkpoint: '01-write-specification-over-project', visual: 'The focus pill shows the Project focus with Write specification on top.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.spec_and_checks', checkpoint: '02-specification-and-checks', visual: 'A Specification embed and Check embeds are visible.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.sub_chat_cards', checkpoint: '03-plan-card-and-sub-chats', visual: 'A Plan card and at least two sub-chat cards follow the approval message.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.assumption_link', checkpoint: '04-assumption-sub-chat', visual: 'The sub-chat banner reads "Checks:" with the assumption, and the focus pill shows the Project.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.task_link', checkpoint: '05-task-sub-chat', visual: 'The sub-chat banner reads "Works on:" with the Task, and the focus pill shows the Project.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.plan_buttons', checkpoint: '06-plan-open-chat-buttons', visual: 'The Plan fullscreen shows open-chat buttons next to assumptions and Tasks.', devices: ['web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';

const TURN_TIMEOUT = 420_000;
const STAGE_TIMEOUT = 600_000;
const MAX_TURNS = 10;
const MODEL_QUERY = 'gemini-3.8-flash';
const MODEL_NAME = /Gemini 3\.8 Flash/i;

const FEATURE_REQUEST = 'I want a new feature that reminds me when to water each bed.';
const FACTS = 'Move fast: use your recommendations for everything and treat this as my answer to all open questions. '
  + 'Keep these as open assumptions: "browsers allow scheduled notifications" and "users water at most once a day". '
  + 'One specification is fine.';
const CONFIRM = 'Yes, that is right. Use your recommendations and go on to the next step.';
const APPROVE = 'I approve the Specification and its Checks.';

async function insertModelMention(page: Page): Promise<void> {
  await page.keyboard.insertText(`@${MODEL_QUERY}`);
  const dropdown = page.getByTestId('mention-dropdown');
  await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: MODEL_NAME }).first())
    .toBeVisible({ timeout: 10_000 });
  await page.keyboard.press('Tab');
  await expect(dropdown).not.toBeVisible({ timeout: 3_000 });
}

async function sendWithModel(page: Page, prompt: string, kind: string): Promise<void> {
  await focusMessageEditor(page.getByTestId('message-editor'));
  await page.keyboard.press('End');
  await insertModelMention(page);
  await sendMessage(page, ` ${prompt}`, undefined, undefined, kind, { preserveExistingContent: true });
}

/** Idle when nothing is in flight for 5 s (stop button, typing indicator, streaming or queued messages). */
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

async function send(page: Page, prompt: string, kind: string): Promise<void> {
  const before = await lastAssistantId(page);
  await sendWithModel(page, prompt, kind);
  await waitForTurn(page, before);
}

let proof: { checkpoint(id: string): Promise<void> } | null = null;

async function shot(page: Page, testInfo: any, name: string): Promise<void> {
  await proof?.checkpoint(name);
  await testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' });
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
}

async function createProject(page: Page, topic: string): Promise<{ id: string; name: string }> {
  const name = naturalProjectName(topic);
  await page.goto('/projects');
  await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30_000 });
  const created = page.waitForResponse((response: any) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/v1/projects' && response.ok());
  await page.getByTestId('project-input-textarea').fill(name);
  await page.getByTestId('project-input-submit').click();
  await page.getByTestId('project-write-policy-apply-and-show').check();
  await page.getByTestId('project-write-policy-confirm').click();
  const id = (await (await created).json()).project.project_id as string;
  await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 30_000 });
  return { id, name };
}

/** Starts a fresh chat bound to the Project with an @Project mention. */
async function startProjectChat(page: Page, projectId: string, projectName: string): Promise<void> {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page).not.toHaveURL(/chat-id=/);
  await page.getByTestId('message-field').click();
  const editor = page.getByTestId('message-editor');
  await expect(editor).toBeVisible({ timeout: 60_000 });
  await focusMessageEditor(editor);
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.press('Backspace');
  await page.keyboard.type(`@${projectName.trim().split(/\s+/).at(-1)}`, { delay: 60 });
  const result = page.locator('.mention-dropdown .mention-result')
    .filter({ hasText: projectName }).filter({ hasText: 'Project context' }).first();
  await expect(result).toBeVisible({ timeout: 120_000 });
  await result.click();
  await expect(editor.locator(`[data-type="generic-mention"][data-mention-type="project"][data-project-id="${projectId}"]`),
    'the new chat is bound to the Project').toBeVisible({ timeout: 30_000 });
}

async function deleteProject(page: Page, projectId: string): Promise<void> {
  await page.goto(`/projects/${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
  const deleted = page.waitForResponse((response: any) => response.request().method() === 'DELETE'
    && new URL(response.url()).pathname === `/v1/projects/${projectId}`);
  page.once('dialog', (dialog: any) => dialog.accept());
  await page.getByTestId('project-more-button').click();
  await page.getByTestId('project-delete-button').click();
  await deleted;
}

const planCard = (page: Page): Locator => page.getByTestId('plan-embed-preview');
const subChatCards = (page: Page): Locator => page.getByTestId('sub-chat-card');

/** Opens sub-chat cards of the main chat one by one until one shows a work link of `kind`. */
async function openSubChatOfKind(page: Page, kind: 'assumption' | 'task'): Promise<Locator> {
  const count = await subChatCards(page).count();
  for (let index = 0; index < count; index += 1) {
    await subChatCards(page).nth(index).click();
    const link = page.getByTestId('sub-chat-work-link');
    await expect(link.first()).toBeVisible({ timeout: 60_000 });
    if ((await link.first().getAttribute('data-kind')) === kind) return link.first();
    await page.getByTestId('sub-chat-work-link-back').click();
    await expect(subChatCards(page).first()).toBeVisible({ timeout: 60_000 });
  }
  throw new Error(`No sub-chat with a ${kind} work link was found among ${count} cards.`);
}

/** Counts research/code tool cards in assistant messages after the approval message. */
async function toolCardsAfterApproval(page: Page, approvalText: string): Promise<number> {
  return page.evaluate((approval) => {
    const messages = Array.from(document.querySelectorAll('[data-testid="message-user"], [data-testid="message-assistant"]'));
    const at = messages.findIndex((el) => el.getAttribute('data-testid') === 'message-user' && (el.textContent ?? '').includes(approval));
    if (at < 0) return 0;
    let total = 0;
    for (const message of messages.slice(at + 1)) {
      if (message.getAttribute('data-testid') !== 'message-assistant') continue;
      total += message.querySelectorAll('[data-testid="embed-preview"][data-app-id="web"]').length;
      total += Array.from(message.querySelectorAll('[data-testid="embed-preview"][data-app-id="code"]'))
        .filter((card) => !card.querySelector('[data-testid="check-preview"]') && !card.matches('[data-testid="check-preview"]')).length;
    }
    return total;
  }, approvalText);
}

test.describe('Approved Specification hands work to sub-chats (real inference, isolated CI)', () => {
  test.describe.configure({ mode: 'serial', retries: 0 });
  test.use({ actionTimeout: 60_000, navigationTimeout: 60_000 });

  // contract-test: direct surface=gui.web assertions=focus-modes.guided-spec-authoring,chat-orchestration.sub-chats.focus-inheritance,chat-orchestration.sub-chats.work-links,plans.sub-chats.assumption-and-task-chats
  test('assumption and Task sub-chats inherit the Project focus and link back to the Plan', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(1_500_000);
    requireRealInference('Spec sub-chats', BASE_URL);
    if (!getTestAccount().email) throw new Error('Real-inference CI requires a provisioned test account.');
    await page.setViewportSize({ width: 1280, height: 900 });
    proof = createVideoProofRuntime(proofContract, {
      device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    await loginToTestAccount(page);
    let projectId = '';
    try {
      const project = await createProject(page, 'Garden planner');
      projectId = project.id;
      const projectLabel = project.name.split(':')[0];
      await startProjectChat(page, project.id, project.name);

      await send(page, FEATURE_REQUEST, 'spec-opening');
      await expandActivity(page);
      await expect(page.locator('[data-testid="focus-mode-bar"].activated[data-focus-id="code-write_specification"]').first(),
        'Write specification activates on top of the Project focus').toBeVisible({ timeout: 120_000 });
      await expect(page.getByTestId('focus-pill')).toContainText(projectLabel, { timeout: 60_000 });
      await shot(page, testInfo, '01-write-specification-over-project');

      let approved = false;
      let specShown = false;
      for (let turn = 1; turn <= MAX_TURNS && !approved; turn += 1) {
        await expandActivity(page);
        specShown ||= await page.getByTestId('specification-embed-card').count() > 0;
        const lastText = (await page.getByTestId('message-assistant').last().textContent()) ?? '';
        if (specShown && await page.getByTestId('check-preview').count() > 0 && /approv/i.test(lastText)) {
          await shot(page, testInfo, '02-specification-and-checks');
          await send(page, APPROVE, 'spec-approval');
          approved = true;
        } else {
          await send(page, turn === 1 ? FACTS : CONFIRM, `spec-turn-${turn}`);
        }
      }
      expect(approved, 'the Specification and Checks were drafted and approved').toBe(true);

      await expect(planCard(page).first(), 'a Plan card appears after approval').toBeVisible({ timeout: STAGE_TIMEOUT });
      await expect.poll(() => subChatCards(page).count(), {
        message: 'one sub-chat per open assumption starts', timeout: STAGE_TIMEOUT, intervals: [3_000],
      }).toBeGreaterThanOrEqual(2);
      await shot(page, testInfo, '03-plan-card-and-sub-chats');
      const mainChatUrl = page.url();

      const assumptionLink = await openSubChatOfKind(page, 'assumption');
      await expect(assumptionLink).toContainText(/Checks:/);
      await expect(page.getByTestId('focus-pill'), 'the assumption sub-chat inherits the Project focus')
        .toContainText(projectLabel, { timeout: 60_000 });
      await shot(page, testInfo, '04-assumption-sub-chat');
      await page.getByTestId('sub-chat-work-link-back').click();
      await expect(subChatCards(page).first()).toBeVisible({ timeout: 60_000 });

      // Tasks are created and their sub-chats start after the assumptions.
      await expect.poll(async () => {
        await openSubChatOfKindSafe(page, 'task');
        return page.getByTestId('sub-chat-work-link').first().getAttribute('data-kind');
      }, { message: 'a Task sub-chat starts', timeout: STAGE_TIMEOUT, intervals: [5_000] }).toBe('task');
      const taskLink = page.getByTestId('sub-chat-work-link').first();
      await expect(taskLink).toContainText(/Works on:/);
      await expect(page.getByTestId('focus-pill'), 'the Task sub-chat inherits the Project focus')
        .toContainText(projectLabel, { timeout: 60_000 });
      await shot(page, testInfo, '05-task-sub-chat');
      await page.getByTestId('sub-chat-work-link-back').click();
      await expect(page).toHaveURL(mainChatUrl);

      await planCard(page).first().click();
      await expect(page.getByTestId('plan-embed-fullscreen')).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId('plan-assumption-open-chat').first()).toContainText('Checking chat');
      await expect(page.getByTestId('plan-task-open-chat').first()).toContainText('Working chat');
      await shot(page, testInfo, '06-plan-open-chat-buttons');
      await page.keyboard.press('Escape');

      await expandActivity(page);
      expect(await toolCardsAfterApproval(page, APPROVE),
        'the main chat ran no web or code tool after the approval').toBe(0);
      await deleteActiveChat(page);
    } finally {
      if (projectId) await deleteProject(page, projectId);
    }
  });
});

/** Opens task sub-chats until one is found; leaves the main chat open when none exists yet. */
async function openSubChatOfKindSafe(page: Page, kind: 'assumption' | 'task'): Promise<void> {
  try {
    await openSubChatOfKind(page, kind);
  } catch {
    // Task sub-chats can start after the assumption chats; the caller's poll retries.
    if (await page.getByTestId('sub-chat-work-link-back').count() > 0) await page.getByTestId('sub-chat-work-link-back').click();
  }
}
