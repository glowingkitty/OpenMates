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
const { observeTaskJobPersistence } = require('./helpers/task-job-proof');
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
    { id: 'active-plan', text: 'Chat settings show the active Plan with its saved Tasks and progress.', checkpoint: '07-active-plan-panel', devices: ['web-laptop'] },
  ],
  assertions: [
    { id: 'spec_sub_chats.layered_focus', checkpoint: '01-write-specification-over-project', visual: 'The focus pill shows the Project focus with Write specification on top.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.spec_and_checks', checkpoint: '02-specification-and-checks', visual: 'A Specification embed and Check embeds are visible.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.sub_chat_cards', checkpoint: '03-plan-card-and-sub-chats', visual: 'A Plan card and at least two sub-chat cards follow the approval message.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.assumption_link', checkpoint: '04-assumption-sub-chat', visual: 'The sub-chat shows a Sub-chat header pill and an origin event linking the main chat that reads "Checks:" with the assumption; the focus pill shows the Project and no sub-chats toggle is next to it.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.task_link', checkpoint: '05-task-sub-chat', visual: 'The sub-chat origin event names the main chat and reads "Works on:" with the Task, and the focus pill shows the Project.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.plan_buttons', checkpoint: '06-plan-open-chat-buttons', visual: 'The Plan fullscreen shows open-chat buttons next to assumptions and Tasks.', devices: ['web-laptop'] },
    { id: 'spec_sub_chats.active_plan', checkpoint: '07-active-plan-panel', visual: 'The chat settings Plan tab shows the progress bar and a saved Task with its working-chat link.', devices: ['web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';

const TURN_TIMEOUT = 420_000;
const STAGE_TIMEOUT = 600_000;
const MAX_TURNS = 10;
const MODEL_QUERY = 'gemini-3.8-flash';
const MODEL_NAME = /Gemini 3\.8 Flash/i;

const FEATURE_REQUEST = 'I want to add a software feature to this garden planner. Help me write a Specification and its Checks for watering reminders for each garden bed before we implement it.';
const FACTS = 'Move fast: use your recommendations for everything and treat this as my answer to all open questions. '
  + 'Keep exactly these two open assumptions: "browsers allow scheduled notifications" and "users water at most once a day". '
  + 'One specification is fine.';
const CONFIRM = 'Yes, that is right. Use your recommendations and go on to the next step.';
const APPROVE = 'I approve the Specification and its Checks. Check the open assumptions in their own sub-chats before creating the Tasks.';
const IMPLEMENT = 'Good. Start implementing the Tasks now, each in its own sub-chat.';

async function insertModelMention(page: Page): Promise<void> {
  await page.keyboard.insertText(`@${MODEL_QUERY}`);
  const dropdown = page.getByTestId('mention-dropdown');
  await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: MODEL_NAME }).first())
    .toBeVisible({ timeout: 10_000 });
  await page.keyboard.press('Tab');
  await expect(dropdown).not.toBeVisible({ timeout: 3_000 });
}

async function sendWithModel(page: Page, prompt: string, kind: string, projectId?: string): Promise<void> {
  // Sending while a reply or its server follow-up is still running queues the
  // message behind it; a user waits for the answer first.
  await waitForIdle(page);
  const editor = page.getByTestId('message-editor');
  // The message field can collapse after a reply. Use its focus shortcut to
  // open the editor without hitting a focus-pill or activity button.
  if (!await editor.getByRole('textbox').isVisible()) await page.keyboard.press('Shift+Enter');
  await expect(editor.getByRole('textbox')).toBeVisible();
  await focusMessageEditor(editor);
  if (projectId) {
    // The first message carries the Project mention that binds the chat.
    await page.keyboard.press('End');
    await page.keyboard.press('Space');
  } else {
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.press('Backspace');
  }
  await insertModelMention(page);
  if (projectId) {
    await expect(editor.locator(`[data-mention-type="project"][data-project-id="${projectId}"]`)).toBeVisible();
  }
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
  // More than three sub-chats in one turn wait for the user's go; the user here starts them all.
  const startAll = page.getByTestId('sub-chat-confirm-start-all');
  let idleSince = 0;
  let busyControls: string[] = [];
  await expect.poll(async () => {
    if (await startAll.isVisible()) {
      await startAll.click();
      idleSince = 0;
      return false;
    }
    busyControls = await busy.evaluateAll((elements) => elements.map((element) => element.getAttribute('data-testid') ?? 'unknown'));
    if (busyControls.length > 0) {
      idleSince = 0;
      return false;
    }
    idleSince ||= Date.now();
    return Date.now() - idleSince >= 5_000;
  }, { timeout: TURN_TIMEOUT, intervals: [1_000] }).toBe(true).catch((error: Error) => {
    throw new Error(`Chat did not settle. Visible work controls: ${busyControls.join(', ') || 'none'}`, { cause: error });
  });
}

async function lastAssistantId(page: Page): Promise<string | null> {
  const ids = await page.getByTestId('message-assistant').evaluateAll((elements) =>
    elements.map((element) => element.getAttribute('data-message-id') ?? '').filter(Boolean));
  return ids.at(-1) ?? null;
}

/** True when the last reply only activated a focus: the server's follow-up reply is still to come. */
async function onlyFocusActivated(page: Page): Promise<boolean> {
  const last = page.getByTestId('message-assistant').last();
  const text = (await last.innerText().catch(() => '')).replace(/\s+/g, ' ');
  if (!/Focus activated/i.test(text)) return false;
  const prose = await last.getByTestId('message-content').last().evaluate((element) => {
    const copy = element.cloneNode(true) as HTMLElement;
    copy.querySelectorAll('[data-testid*="embed"], [class*="embed"], [data-testid*="tool"], [data-testid*="focus"]')
      .forEach((node) => node.remove());
    return (copy.textContent ?? '').replace(/\s+/g, ' ').trim().length;
  }).catch(() => 0);
  return prose < 20;
}

async function waitForTurn(page: Page, lastBefore: string | null): Promise<void> {
  await expect.poll(async () => {
    const last = await lastAssistantId(page);
    return last !== null && last !== lastBefore;
  }, { timeout: TURN_TIMEOUT, intervals: [2_000] }).toBe(true);
  await waitForAssistantMessage(page, { timeout: TURN_TIMEOUT });
  await waitForIdle(page);
  // A focus activation ends its own message; the answer follows in a server
  // follow-up. Sending before it starts collides with that queued hand-off.
  if (await onlyFocusActivated(page)) {
    const activation = await lastAssistantId(page);
    await expect.poll(async () => (await lastAssistantId(page)) !== activation || !(await onlyFocusActivated(page)),
      { message: 'the answer follows the focus activation', timeout: TURN_TIMEOUT, intervals: [2_000] }).toBe(true);
    await waitForIdle(page);
  }
  const generatedBy = page.getByTestId('message-assistant').last().getByTestId('generated-by');
  await expect(generatedBy).toBeVisible({ timeout: 120_000 });
  await expect(generatedBy).toContainText(MODEL_NAME);
}

async function send(page: Page, prompt: string, kind: string, projectId?: string): Promise<void> {
  const before = await lastAssistantId(page);
  await sendWithModel(page, prompt, kind, projectId);
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

/** Start from the Project's New chat action and check its prefilled mention. */
async function startProjectChat(page: Page, projectId: string): Promise<void> {
  await page.getByTestId('project-tab-folders').click();
  await expect(page.getByTestId('project-folders-panel')).toBeVisible();
  await page.getByTestId('project-folder-create-menu-button').click();
  await page.getByTestId('project-create-chat').click();
  await expect(page).not.toHaveURL(/chat-id=/);
  const editor = page.getByTestId('message-editor');
  await expect(editor).toBeVisible({ timeout: 60_000 });
  if (!await editor.getByRole('textbox').isVisible()) await page.getByTestId('message-field').click();
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
    const origin = page.getByTestId('sub-chat-origin');
    await expect(origin.first()).toBeVisible({ timeout: 60_000 });
    // The work link loads after the origin event renders (data-kind "none" until then).
    await expect.poll(() => origin.first().getAttribute('data-kind'), {
      message: 'the sub-chat work link loads', timeout: 30_000,
    }).not.toBe('none').catch(() => undefined);
    if ((await origin.first().getAttribute('data-kind')) === kind) return origin.first();
    await page.getByTestId('sub-chat-origin-parent-link').click();
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

  // contract-test: direct surface=gui.web assertions=focus-modes.guided-spec-authoring,chat-orchestration.sub-chats.focus-inheritance,chat-orchestration.sub-chats.work-links,plans.sub-chats.assumption-and-task-chats,plans.embed.preview-fullscreen,plans.chat-settings.active-plan
  test('assumption and Task sub-chats inherit the Project focus and link back to the Plan', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(1_500_000);
    requireRealInference('Spec sub-chats', BASE_URL);
    if (!getTestAccount().email) throw new Error('Real-inference CI requires a provisioned test account.');
    await page.setViewportSize({ width: 1280, height: 900 });
    // Plan creation runs in the browser; its refusal codes explain a missing Plan.
    // Sub-chat message storage and sync lines explain a sub-chat showing a sibling's prompt or no reply.
    const subChatTrace: string[] = [];
    const SUB_CHAT_TRACE = /saveMessage called|spawn_sub_chats|sub_chat_(progress|completed)|chat_content_batch|ai_message_persisted|Phase ?1|SubChat|\[TaskJobs\]/i;
    page.on('console', (message) => {
      const line = message.text();
      if (line.startsWith('[PlanCreate]')) console.log(`[browser] ${line.slice(0, 200)}`);
      if (SUB_CHAT_TRACE.test(line)) subChatTrace.push(`${new Date().toISOString()} ${line.slice(0, 400)}`);
    });
    const attachSubChatTrace = () => testInfo.attach('sub-chat-console-trace', { body: subChatTrace.join('\n'), contentType: 'text/plain' });
    proof = createVideoProofRuntime(proofContract, {
      device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    const committedTasks = observeTaskJobPersistence(page);
    await loginToTestAccount(page);
    let projectId = '';
    try {
      const project = await createProject(page, 'Garden planner');
      projectId = project.id;
      const projectLabel = project.name.split(':')[0];
      await startProjectChat(page, project.id);

      await send(page, FEATURE_REQUEST, 'spec-opening', projectId);
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
          const lastReply = page.getByTestId('message-assistant').last();
          // A provider can fail before returning any output. Retry once via the composer
          // when the app explicitly asks the user to retry and no Plan has appeared.
          if (await lastReply.getByText(/The AI service encountered an error.*Please try again/).isVisible()
            && await planCard(page).count() === 0) {
            await send(page, APPROVE, 'spec-approval-retry');
          }
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
      const mainChatId = await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id');
      expect(mainChatId).toBeTruthy();

      const assumptionLink = await openSubChatOfKind(page, 'assumption');
      await expect(assumptionLink).toContainText(/Checks:/);
      // An opened sub-chat shows only its own prompt, answered by the assistant.
      const assumptionText = ((await assumptionLink.getByTestId('sub-chat-origin-work').textContent()) ?? '').replace(/^Checks:\s*/, '').trim();
      await expect.poll(() => page.getByTestId('message-assistant').count(), {
        message: 'the assumption sub-chat shows its assistant reply', timeout: 120_000, intervals: [3_000],
      }).toBeGreaterThan(0);
      const userMessages = page.getByTestId('message-user');
      await expect(userMessages, 'the sub-chat shows only its own prompt').toHaveCount(1);
      // The model writes the sub-chat prompt itself, so it names the assumption's subject rather than quoting it.
      const subject = assumptionText.split(/\s+/).filter((word) => word.length > 6).map((word) => word.toLowerCase());
      const prompt = ((await userMessages.first().textContent()) ?? '').toLowerCase();
      expect(subject.some((word) => prompt.includes(word.slice(0, 6))), `the sub-chat prompt is about "${assumptionText}"`).toBe(true);
      await expect(page.getByTestId('sub-chat-origin-parent-link'), 'the origin event links the main chat').toBeVisible();
      await expect(page.getByTestId('sub-chat-header-pill'), 'the header marks the sub-chat').toBeVisible();
      await expect(page.getByTestId('sub-chat-broadcast-toggle'), 'no sub-chats toggle in the input').toHaveCount(0);
      await expect(page.getByTestId('focus-pill'), 'the assumption sub-chat inherits the Project focus')
        .toContainText(projectLabel, { timeout: 60_000 });
      await shot(page, testInfo, '04-assumption-sub-chat');
      await page.getByTestId('sub-chat-origin-parent-link').click();
      await expect(subChatCards(page).first()).toBeVisible({ timeout: 60_000 });

      // The assumption results come back in a follow-up turn that summarises
      // them, creates the Tasks and asks to start; Task sub-chats start on the go.
      await expect.poll(async () => {
        await expandActivity(page);
        return page.getByTestId('task-embed-card').count();
      }, { message: 'the main chat creates the Tasks after the assumption results', timeout: STAGE_TIMEOUT, intervals: [5_000] })
        .toBeGreaterThan(0);
      await expect.poll(() => committedTasks(mainChatId ?? '').length, {
        message: 'the browser receives an encrypted Task persistence receipt', timeout: 120_000,
      }).toBeGreaterThan(0);
      await planCard(page).first().click();
      await expect(page.getByTestId('plan-task-row').first(), 'the browser saved the staged Tasks to the Plan')
        .toBeVisible({ timeout: 120_000 });
      await page.keyboard.press('Escape');
      await expect(page.getByTestId('plan-embed-fullscreen')).not.toBeVisible();

      await send(page, IMPLEMENT, 'spec-implement');
      await planCard(page).first().click();
      const workingChat = page.getByTestId('plan-task-open-chat').first();
      await expect(workingChat, 'the Plan links a Task sub-chat').toBeVisible({ timeout: STAGE_TIMEOUT });
      await workingChat.click();
      await expect(page.getByTestId('sub-chat-origin').first(), 'opening the Task shows its working chat')
        .toHaveAttribute('data-kind', 'task');
      const taskLink = page.getByTestId('sub-chat-origin-work').first();
      await expect(taskLink).toContainText(/Works on:/);
      await expect(page.getByTestId('focus-pill'), 'the Task sub-chat inherits the Project focus')
        .toContainText(projectLabel, { timeout: 60_000 });
      await shot(page, testInfo, '05-task-sub-chat');
      await page.getByTestId('sub-chat-origin-parent-link').click();
      await expect(page).toHaveURL(mainChatUrl);

      await planCard(page).first().click();
      await expect(page.getByTestId('plan-embed-fullscreen')).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId('plan-assumption-open-chat').first()).toContainText('Checking chat');
      await expect(page.getByTestId('plan-task-open-chat').first()).toContainText('Working chat');
      await expect(page.getByTestId('plan-task-row').first()).toBeVisible();
      await shot(page, testInfo, '06-plan-open-chat-buttons');
      await page.getByTestId('plan-task-open-chat').first().scrollIntoViewIfNeeded();
      await testInfo.attach('plan-working-chat-links', { body: await page.screenshot(), contentType: 'image/png' });
      await page.keyboard.press('Escape');

      const detailsButton = page.getByTestId('chat-details-button');
      if (!await detailsButton.isVisible()) await page.getByTestId('chat-more-button').click();
      await detailsButton.click();
      await page.getByTestId('chat-settings-tab-plan').click();
      const activePlan = page.getByTestId('chat-active-plan-panel');
      await expect(activePlan).toHaveCount(1);
      await expect(activePlan.getByTestId('chat-active-plan-progress-bar')).toBeVisible();
      const activeWorkingChat = activePlan.getByTestId('chat-active-plan-task-open-chat').first();
      await expect(activeWorkingChat).toBeVisible();
      await activeWorkingChat.scrollIntoViewIfNeeded();
      await shot(page, testInfo, '07-active-plan-panel');
      await page.getByTestId('icon-button-close').click();
      await expect(page.getByTestId('settings-menu')).not.toBeVisible();

      await expandActivity(page);
      expect(await toolCardsAfterApproval(page, APPROVE),
        'the main chat ran no web or code tool after the approval').toBe(0);
      await deleteActiveChat(page);
    } catch (error) {
      await attachSubChatTrace();
      const taskErrors = await page.getByTestId('task-embed-validation-error').allTextContents();
      if (taskErrors.length > 0) {
        await testInfo.attach('task-validation-errors', { body: taskErrors.join('\n'), contentType: 'text/plain' });
      }
      await testInfo.attach('failure-before-cleanup', { body: await page.screenshot(), contentType: 'image/png' });
      throw error;
    } finally {
      if (projectId) await deleteProject(page, projectId);
    }
  });
});
