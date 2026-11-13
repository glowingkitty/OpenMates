/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: required reason=real_inference_dev_only (Project Memories press style reused in a second chat)
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Real-inference, dev-only: a press style the assistant saved into a Project's Memories is
 * reused in a second chat of the same Project. Run through
 * scripts/press_release_project_memory_web_real_test.py; never in CI, no mocks.
 *
 * "3,000" appears only in the saved style (About paragraph), never in the news prompt.
 */
export {};

import type { Page, Response } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const {
  deleteActiveChat, focusMessageEditor, loginToTestAccount, sendMessage, startNewChat, waitForAssistantMessage,
} = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { naturalProjectName } = require('./helpers/project-names');

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL
  || BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');
const TURN_TIMEOUT = 420_000;

const STYLE = "Our press style: always write 'Example Solar' (never 'ExampleSolar'), product name 'SunShare' in camel case, plain and friendly tone, no superlatives, English with AP style, end with ###. About paragraph: Example Solar GmbH, based in Leipzig, makes plug-in balcony solar kits for renters. Founded in 2021, the company has equipped more than 3,000 apartments in Germany.";
const NEWS = "All synthetic test data. Company: Example Solar GmbH, Leipzig, founded 2021, 24 employees, makes balcony solar kits for renters. News: on 18 November 2026 we launch SunShare, an app that lets neighbours in one building pool their balcony solar power. Pilot: 120 households in Leipzig saved on average 11 percent on electricity over six months (our own pilot data, May to October 2026). Available from 18 November in Germany, free for Example Solar customers, 2 EUR a month otherwise, at example.org/sunshare. Quote from Mara Example, CEO: she wants renters to share energy like they share a stairwell. Media contact: Jonas Example, press officer, press@example.org, +49 341 0000000. Release for immediate publication.";

function requireDirectDevRealInference(): void {
  if (process.env.CI || process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1') {
    throw new Error('Real-inference Project Memories proof is dev-only and must never run in CI.');
  }
  if (process.env.E2E_USE_MOCKS || process.env.E2E_USE_LIVE_MOCKS) {
    throw new Error('This proof requires real inference; mock replay must be disabled.');
  }
  if (!new URL(BASE_URL).hostname.includes('.dev.')) {
    throw new Error('This proof may target only the dev web host.');
  }
}

async function createProject(page: Page, name: string, writeMode: 'always_ask' | 'apply_and_show'): Promise<string> {
  // In-app navigation only: a full reload drops a session that is not "stay logged in".
  await page.getByTestId('projects-nav-link').click();
  await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30_000 });
  const created = page.waitForResponse(
    (response: Response) => response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/v1/projects'
      && response.ok(),
  );
  await page.getByTestId('project-input-textarea').fill(name);
  await page.getByTestId('project-input-submit').click();
  await page.getByTestId(`project-write-policy-${writeMode.replaceAll('_', '-')}`).check();
  await page.getByTestId('project-write-policy-confirm').click();
  const response = await created;
  expect(response.request().postDataJSON()).toMatchObject({ write_mode: writeMode });
  const body = await response.json() as { project?: { project_id?: string } };
  const projectId = body.project?.project_id;
  expect(projectId).toMatch(/^[0-9a-f-]{36}$/i);
  // Creating a Project opens its full-page detail view, which hides the chat
  // composer; return to the chat view so the next step can start a chat.
  await page.getByTestId('chats-nav-link').click();
  await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 60_000 });
  return projectId as string;
}

async function deleteProject(page: Page, projectId: string): Promise<void> {
  const status = await page.evaluate(async ({ apiBaseUrl, targetId }) => {
    const response = await fetch(`${apiBaseUrl}/v1/projects/${targetId}?confirmation_project_id=${encodeURIComponent(targetId)}`, { method: 'DELETE', credentials: 'include' });
    return response.status;
  }, { apiBaseUrl: API_BASE_URL, targetId: projectId });
  expect(status, 'disposable Project cleanup').toBeGreaterThanOrEqual(200);
  expect(status, 'disposable Project cleanup').toBeLessThan(300);
}

async function sendWithProjectMention(
  page: Page, projectId: string, projectName: string, prompt: string, accessMode: 'read' | 'read_write',
): Promise<void> {
  const editor = page.getByTestId('message-editor');
  await page.bringToFront();
  await focusMessageEditor(editor);
  const projectQuery = projectName.trim().split(/\s+/).at(-1);
  expect(projectQuery).toBeTruthy();
  await page.keyboard.insertText(`@${projectQuery}`);
  const projectResult = page
    .locator('.mention-dropdown .mention-result')
    .filter({ hasText: projectName })
    .filter({ hasText: 'Project context' })
    .first();
  await expect(projectResult).toBeVisible({ timeout: 30_000 });
  await projectResult.click();
  const accessChip = editor.getByTestId('project-access-chip');
  await expect(accessChip).toBeVisible();
  if (await accessChip.getAttribute('data-project-access-mode') !== accessMode) {
    await accessChip.click();
  }
  await expect(accessChip).toHaveAttribute('data-project-access-mode', accessMode);
  const mention = accessChip.locator('xpath=ancestor::*[@data-type="generic-mention"][1]');
  await expect(mention).toHaveAttribute('data-project-id', projectId);
  await expect(mention).toHaveAttribute('data-mention-syntax', `@project:${projectId}:${accessMode}`);
  await page.bringToFront();
  await expect.poll(() => page.evaluate(() => document.hasFocus()), { timeout: 5_000 }).toBe(true);
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await focusMessageEditor(editor);
  await page.keyboard.press('End');
  await sendMessage(page, ` ${prompt}`, undefined, undefined, 'project-file', { preserveExistingContent: true });
}

/** Approves a Project file approval card when the save step shows one; no-op otherwise. */
async function approveAnyPendingWrite(page: Page): Promise<void> {
  const pending = page.locator('[data-testid="project-file-approval-card"][data-status="pending"]');
  for (let i = 0; i < 5; i += 1) {
    if (await pending.count() === 0) return;
    await pending.last().getByTestId('project-file-approve').click();
    await expect(pending).toHaveCount(0, { timeout: 60_000 });
  }
}

/** Waits for the answer, approving Project file cards that appear while it runs. */
async function waitForTurn(page: Page): Promise<void> {
  await waitForAssistantMessage(page, { timeout: TURN_TIMEOUT });
  await approveAnyPendingWrite(page);
  await waitForIdle(page);
  await approveAnyPendingWrite(page);
  await waitForIdle(page);
}

/**
 * The turn is over when the stop button and typing indicator stay hidden for 5 s; a
 * Project file operation briefly hides them between the paused and resumed phases.
 */
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

test.describe('Press style saved in Project Memories is reused (real inference, dev only)', () => {
  test.describe.configure({ mode: 'serial', retries: 0 });
  // A stuck click must fail within minutes, not consume the whole real-inference run.
  test.use({ actionTimeout: 60_000, navigationTimeout: 60_000 });

  test.beforeAll(() => {
    requireDirectDevRealInference();
  });

  // contract-test: direct surface=gui.web assertions=projects.memories.active-access,projects.focus.mention-activation,app-memories.conversation.explicit-approval
  test('a second chat of the Project writes the press release in the saved style', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(1_800_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1280, height: 900 });
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await loginToTestAccount(page);

    const projectName = naturalProjectName('Press office');
    const projectId = await createProject(page, projectName, 'apply_and_show');
    try {
      // Chat 1: the assistant saves the press style into the Project's Memories.
      await startNewChat(page);
      await sendWithProjectMention(
        page, projectId, projectName,
        `Set up our press style for press releases and save it to this project's Memories so that you ask me before using it (load mode ask first). ${STYLE} Media contact: Jonas Example, press officer, press@example.org. Mara Example, CEO, is usually quoted.`,
        'read_write',
      );
      await waitForTurn(page);
      await sendMessage(page, "Thanks. If the press style is not saved to this project's Memories yet, save it now; otherwise just confirm.");
      await waitForTurn(page);
      await testInfo.attach('01-style-saved', { body: await page.screenshot(), contentType: 'image/png' });
      await page.screenshot({ path: testInfo.outputPath('01-style-saved.png') });
      await deleteActiveChat(page);

      // Chat 2: a new chat of the same Project reuses the saved style.
      await startNewChat(page);
      await sendWithProjectMention(
        page, projectId, projectName,
        `Write a press release as a Word document about our app launch. ${NEWS} Skip all questions and the fact check, use your recommended headline and write it now. In your chat reply, also quote the release's About paragraph word for word.`,
        'read_write',
      );
      // The Ask first Project Memory is offered by title and loads only after approval.
      const consent = page.getByTestId('app-settings-memories-permission-dialog');
      await expect(consent, 'Ask first approval for the saved Project press style').toBeVisible({ timeout: TURN_TIMEOUT });
      await testInfo.attach('02a-ask-first-approval', { body: await page.screenshot(), contentType: 'image/png' });
      await page.screenshot({ path: testInfo.outputPath('02a-ask-first-approval.png') });
      await consent.getByTestId('btn-include').click();
      await expect(consent).not.toBeVisible({ timeout: 30_000 });
      await waitForTurn(page);
      // "3,000" exists only in the saved Project Memory; document pages are images, so the reply text carries the check.
      const reply = page.locator('[data-testid="message-assistant"]').last();
      await expect(reply, 'the saved style (not the news prompt) supplies "3,000"').toContainText('3,000', { timeout: 120_000 });
      const docEmbed = page.locator('[data-testid="embed-preview"][data-app-id="docs"][data-status="finished"]').last();
      await expect(docEmbed).toBeVisible({ timeout: TURN_TIMEOUT });
      await docEmbed.getByTestId('result-preview-expand').click();
      await expect(page.getByTestId('doc-artifact-pages')).toBeVisible({ timeout: 60_000 });
      await page.waitForTimeout(2_000);
      await testInfo.attach('03-document', { body: await page.screenshot(), contentType: 'image/png' });
      await page.screenshot({ path: testInfo.outputPath('03-document.png') });
      await page.keyboard.press('Escape');
      await testInfo.attach('02-reuse-release', { body: await page.screenshot(), contentType: 'image/png' });
      await page.screenshot({ path: testInfo.outputPath('02-reuse-release.png') });
      await deleteActiveChat(page);
    } finally {
      await deleteProject(page, projectId);
    }
  });
});
