/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Real-inference, dev-only web proof of layered focuses in a Project chat.
 *
 * The Project focus stays active as the base; a request for a new feature layers the built-in
 * Write specification focus on top (countdown proposal), ending that layer leaves the Project
 * focus active, and a Focus stored in the Project (Add a new provider) layers the same way.
 * The override note under the first layered answer is model-written, so it is only recorded.
 * Run through scripts/project_layered_focus_web_real_test.py; never in CI, no mocks.
 */
export {};

import type { Page } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const {
  focusMessageEditor, loginToTestAccount, sendMessage, waitForAssistantMessage,
} = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { naturalProjectName } = require('./helpers/project-names');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const proofContract = defineVideoProof({
  id: 'project-layered-focus-web-real',
  title: 'A more specific focus layers over the Project focus and ends without dropping it',
  surface: 'web',
  devices: ['web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'spec-layered', text: 'A new feature request layers Write specification over the Project focus.', checkpoint: '01-write-specification-layered', devices: ['web-laptop'] },
    { id: 'layer-ended', text: 'Ending the layer leaves the Project focus active.', checkpoint: '02-layer-ended-project-active', devices: ['web-laptop'] },
    { id: 'project-focus-layered', text: 'A Focus stored in the Project layers over the Project focus.', checkpoint: '03-project-focus-layered', devices: ['web-laptop'] },
  ],
  assertions: [
    { id: 'layering.spec_layer', checkpoint: '01-write-specification-layered', visual: 'The focus banner names the Project and Write specification; the reply asks scope questions.', devices: ['web-laptop'] },
    { id: 'layering.layer_end', checkpoint: '02-layer-ended-project-active', visual: 'The Write specification banner is gone and the Project focus is still shown.', devices: ['web-laptop'] },
    { id: 'layering.project_focus', checkpoint: '03-project-focus-layered', visual: 'The banner names the Project and Add a new provider; the reply follows its process.', devices: ['web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const API_BASE_URL = BASE_URL.replace('://app.', '://api.');
const TURN_TIMEOUT = 420_000;
const SPEC_FOCUS_ID = 'code-write_specification';
const PROVIDER_FOCUS_NAME = 'Add a new provider';
// Real-inference proofs pin Gemini 3.8 Flash and fail when another model answered.
const MODEL_QUERY = 'gemini-3.8-flash';
const MODEL_NAME = /Gemini 3\.8 Flash/i;

const FEATURE_REQUEST = 'I want a new feature for my garden planner that reminds me when to water each bed.';
const STOP_LAYER = "Let's stop the specification focus for now and just talk about the project.";
const PROVIDER_REQUEST = 'Please add a weather data provider to this project.';
const SEED_FOCUS = `Please create a Project Focus named "${PROVIDER_FOCUS_NAME}". It applies when I want to add a new data `
  + 'provider or integration. Its process: research the official API, write the wrapper, add tests, and ask me before '
  + 'adding any dependency.';

function requireDirectDevRealInference(): void {
  // The dev proof harness runs this spec in an E2B sandbox, which sets CI=1 for its tools; only the
  // harness sets OPENMATES_PROOF_REAL_DEV (it refuses to start under CI itself). GitHub CI never does.
  const harnessRun = process.env.OPENMATES_PROOF_REAL_DEV === '1';
  if (process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1' || (process.env.CI && !harnessRun)) {
    throw new Error('Real-inference layered focus proof is dev-only and must never run in CI.');
  }
  if (process.env.E2E_USE_MOCKS || process.env.E2E_USE_LIVE_MOCKS) {
    throw new Error('This proof requires real inference; mock replay must be disabled.');
  }
  if (!new URL(BASE_URL).hostname.includes('.dev.')) {
    throw new Error('This proof may target only the dev web host.');
  }
}

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

async function waitForTurn(page: Page, assistantsBefore: number): Promise<void> {
  await expect.poll(() => page.getByTestId('message-assistant').count(), { timeout: TURN_TIMEOUT, intervals: [2_000] })
    .toBeGreaterThan(assistantsBefore);
  await waitForAssistantMessage(page, { timeout: TURN_TIMEOUT });
  await waitForIdle(page);
  const generatedBy = page.getByTestId('message-assistant').last().getByTestId('generated-by');
  await expect(generatedBy).toBeVisible({ timeout: 120_000 });
  await expect(generatedBy).toContainText(MODEL_NAME);
}

async function send(page: Page, prompt: string, kind: string): Promise<void> {
  const before = await page.getByTestId('message-assistant').count();
  await sendWithModel(page, prompt, kind);
  await waitForTurn(page, before);
}

let proof: { checkpoint(id: string): Promise<void> } | null = null;

async function shot(page: Page, testInfo: any, name: string): Promise<void> {
  await proof?.checkpoint(name);
  await testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' });
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
}

/** Creates a Project through the start screen and returns its id and name. */
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

/**
 * Starts a fresh chat and binds it to the Project with an @Project mention, the way a user names a
 * Project in any chat. The Project focus becomes active when the first message is sent.
 */
async function startProjectChat(page: Page, projectId: string, projectName: string): Promise<void> {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page).not.toHaveURL(/chat-id=/);
  await page.getByTestId('message-field').click();
  const editor = page.getByTestId('message-editor');
  await expect(editor).toBeVisible({ timeout: 60_000 });
  await focusMessageEditor(editor);
  // Start from an empty composer: Project creation may leave its own @Project chip behind.
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.press('Backspace');
  const projectQuery = projectName.trim().split(/\s+/).at(-1);
  expect(projectQuery).toBeTruthy();
  await page.keyboard.type(`@${projectQuery}`, { delay: 60 });
  const projectResult = page.locator('.mention-dropdown .mention-result')
    .filter({ hasText: projectName }).filter({ hasText: 'Project context' }).first();
  // Project mention results load every Project's settings and sources before ranking, which is slow on
  // accounts with many Projects; the time it took is logged so a slow dropdown stays visible in the run.
  const mentionStarted = Date.now();
  await expect(projectResult).toBeVisible({ timeout: 120_000 });
  console.log(`[project-mention] dropdown result after ${Date.now() - mentionStarted} ms`);
  await projectResult.click();
  const mention = editor.locator(`[data-type="generic-mention"][data-mention-type="project"][data-project-id="${projectId}"]`);
  await expect(mention, 'the new chat is bound to the Project').toBeVisible({ timeout: 30_000 });
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

async function chatProjectId(page: Page): Promise<string | undefined> {
  const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1]
    || await page.locator('[data-action="message-input"]').last().getAttribute('data-current-chat-id');
  expect(chatId).toBeTruthy();
  return page.evaluate(async ({ apiBaseUrl, id }) => {
    const response = await fetch(`${apiBaseUrl}/v1/projects/focus/current?chat_id=${encodeURIComponent(id as string)}`, { credentials: 'include' });
    if (!response.ok) throw new Error(`Project authority query failed: ${response.status}`);
    const body = await response.json() as { focus?: { project_id?: string } | null };
    return body.focus?.project_id;
  }, { apiBaseUrl: API_BASE_URL, id: chatId });
}

/** Records whether the first layered answer carries a blockquote override note; never fails on it. */
async function recordOverrideNote(page: Page, testInfo: any, layered: RegExp, label: string): Promise<void> {
  const quotes = await page.getByTestId('message-assistant').last().locator('blockquote').allTextContents();
  const note = quotes.find((text) => layered.test(text));
  const outcome = quotes.length === 0 ? 'no blockquote note' : note ? 'note mentions the layered focus' : 'blockquote without layered focus mention';
  console.log(`[override-note] ${label}: ${outcome}`);
  await testInfo.attach(`override-note-${label}`, { body: outcome, contentType: 'text/plain' });
}

/**
 * Sends a request that should layer a focus and proves the countdown card was shown and completed.
 * The card is watched from before the send: once the turn ends, the reply folds its activity into the
 * "Activated '<focus>'" summary, so looking for the card afterwards depends on timing.
 */
async function sendAndActivateLayered(page: Page, prompt: string, kind: string, barSelector: string): Promise<void> {
  const before = await page.getByTestId('message-assistant').count();
  const counting = page.waitForSelector(barSelector, { state: 'attached', timeout: TURN_TIMEOUT });
  const activated = page.waitForSelector(`${barSelector}.activated`, { state: 'attached', timeout: TURN_TIMEOUT });
  await sendWithModel(page, prompt, kind);
  // Let the countdown complete; do not cancel it.
  await expect(counting, 'the layered focus is proposed with a countdown card').resolves.toBeTruthy();
  await expect(activated, 'the countdown completes and the focus is activated').resolves.toBeTruthy();
  await waitForTurn(page, before);
}

async function pillLabel(page: Page): Promise<string> {
  return ((await page.getByTestId('focus-pill-label').first().textContent()) ?? '').trim();
}

test.describe('Layered focuses over the Project focus (real inference, dev only)', () => {
  test.describe.configure({ mode: 'serial', retries: 0 });
  test.use({ actionTimeout: 60_000, navigationTimeout: 60_000 });

  test.beforeAll(() => {
    requireDirectDevRealInference();
  });

  // contract-test: direct surface=gui.web assertions=focus-modes.project-layering,focus-modes.layer-end,focus-modes.override-note
  test('new feature request layers Write specification over the Project focus', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(1_800_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1280, height: 900 });
    proof = createVideoProofRuntime(proofContract, {
      device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    await skipIfFeaturesDisabled(test, page, ['platform:plans']);
    await loginToTestAccount(page);
    let projectId = '';
    try {
      const project = await createProject(page, 'Garden planner');
      projectId = project.id;
      await startProjectChat(page, project.id, project.name);

      await sendAndActivateLayered(page, FEATURE_REQUEST, 'layer-feature-request',
        `[data-testid="focus-mode-bar"][data-focus-id="${SPEC_FOCUS_ID}"]`);
      await expect(page.getByTestId('focus-pill'), 'the Project focus is the base of the chat')
        .toContainText(project.name.split(':')[0], { timeout: 60_000 });
      await expect.poll(() => pillLabel(page), { timeout: 60_000 }).toMatch(/Write specification/i);
      expect(await pillLabel(page), 'the banner is qualified with the Project').toContain(project.name.split(':')[0]);
      await waitForIdle(page);
      await recordOverrideNote(page, testInfo, /specification/i, 'spec-layer');
      await shot(page, testInfo, '01-write-specification-layered');

      await send(page, STOP_LAYER, 'layer-stop');
      await expect.poll(() => pillLabel(page), { timeout: 60_000 }).not.toMatch(/Write specification/i);
      await expect(page.getByTestId('focus-pill')).toBeVisible();
      expect(await chatProjectId(page), 'the Project focus is still the chat authority').toBe(projectId);
      await shot(page, testInfo, '02-layer-ended-project-active');
    } finally {
      if (projectId) await deleteProject(page, projectId);
    }
  });

  // contract-test: direct surface=gui.web assertions=focus-modes.project-layering,focus-modes.override-note
  test("a Project's own Focus layers over the Project focus", async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(2_400_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1280, height: 900 });
    proof = createVideoProofRuntime(proofContract, {
      device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    await loginToTestAccount(page);
    let projectId = '';
    try {
      const project = await createProject(page, 'Open source library');
      projectId = project.id;

      // Seed the stored Project Focus through the product's own authoring job: the chat suggests
      // "Create Focus", the user clicks it, answers its questions and saves the reviewed draft.
      await startProjectChat(page, project.id, project.name);
      await send(page, SEED_FOCUS, 'seed-focus');
      const action = page.getByTestId('project-authoring-action').first();
      await expect(action, 'the assistant offers to create the Project Focus').toBeVisible({ timeout: 120_000 });
      await action.click();
      const save = page.getByTestId('project-authoring-save').first();
      for (let turn = 0; turn < 4 && !(await save.isVisible().catch(() => false)); turn += 1) {
        await expect.poll(async () => (await save.isVisible()) || (await page.getByTestId('project-authoring-question').count()) > 0,
          { timeout: TURN_TIMEOUT, intervals: [2_000] }).toBe(true);
        if (await save.isVisible()) break;
        await send(page, 'Use your best judgement and keep it short.', `seed-focus-answer-${turn}`);
      }
      await expect(save, 'the Focus draft is ready to save').toBeVisible({ timeout: TURN_TIMEOUT });
      await save.click();
      await expect(page.getByTestId('project-authoring-save').first()).toContainText(/saved/i, { timeout: 120_000 });

      // A fresh chat in the Project starts with only the Project focus active.
      await page.goto(`/projects/${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
      await startProjectChat(page, project.id, project.name);

      await sendAndActivateLayered(page, PROVIDER_REQUEST, 'layer-project-focus',
        `[data-testid="focus-mode-bar"]:has-text("${PROVIDER_FOCUS_NAME}")`);
      await expect.poll(() => pillLabel(page), { timeout: 60_000 }).toContain(PROVIDER_FOCUS_NAME);
      expect(await pillLabel(page)).toContain(project.name.split(':')[0]);
      await waitForIdle(page);
      await recordOverrideNote(page, testInfo, /provider|focus/i, 'project-focus-layer');
      await shot(page, testInfo, '03-project-focus-layered');
    } finally {
      if (projectId) await deleteProject(page, projectId);
    }
  });
});
