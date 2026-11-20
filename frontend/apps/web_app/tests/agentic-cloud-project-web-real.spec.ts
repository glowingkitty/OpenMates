/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Real-inference, dev-only cloud agentic coding flow with the web app as the sending client: a recipe
 * app request creates a hosted Project and application, a command turn installs and builds in the
 * Project workspace, a test turn records a browser test and commits, then preview, Project files and
 * Timeline are shown at laptop and phone size. A last test asks for a Specification with Checks and a
 * Plan in the same Project (separate so a failure there does not hide the earlier steps).
 * The web runs every hosted Project file job through the Rust core in the shared Worker.
 *
 * Run through scripts/agentic_cloud_project_web_real_test.py; never in CI, no mocks. The CLI is not used.
 */
export {};

import type { Locator, Page } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const {
  focusMessageEditor, loginToTestAccount, sendMessage, startNewChat, waitForAssistantMessage,
} = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { expandActivity } = require('./helpers/assistant-activity');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');
const { naturalProjectName } = require('./helpers/project-names');

const STORAGE_DIAGNOSTIC = /CLIENT_DECRYPT|decryption failed|DUPLICATE PREVENTED|replaceMessageById|replaced a stale local segment|Final AI message|recover|Conflict|sealed|interim|Skipping content regression|could not be applied|Remote command/i;

const L = ['web-laptop'];
const B = ['web-laptop', 'web-phone'];
const proofContract = defineVideoProof({
  id: 'agentic-cloud-project-web-real',
  title: 'Cloud agentic coding from the web app: recipe app, build, recorded test and commit in a hosted Project',
  surface: 'web',
  devices: ['web-laptop', 'web-phone'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'app-built', text: 'The chat shows the recipe app, its file changes and the new Project.', checkpoint: 'cloud-app-embed', devices: L },
    { id: 'commands', text: 'The install and build commands ran in the Project workspace.', checkpoint: 'cloud-commands', devices: L },
    { id: 'test-recorded', text: 'The recorded browser test opens with its video beside the step timeline.', checkpoint: 'cloud-test-result', devices: L },
    { id: 'commit', text: 'The reply names the commit by its short id.', checkpoint: 'cloud-commit', devices: L },
    { id: 'preview', text: 'The app runs in the live preview.', checkpoint: 'cloud-preview', devices: L },
    { id: 'files-view', text: 'The Project files show the folder with the application card.', checkpoint: 'cloud-project-files', devices: B },
    { id: 'timeline-view', text: 'The Timeline of the Project shows the commit.', checkpoint: 'cloud-project-timeline', devices: B },
    { id: 'spec-plan', text: 'A new chat in the Project writes a Specification and a Plan.', checkpoint: 'cloud-spec-plan', devices: L },
  ],
  assertions: [
    { id: 'cloud.app_embed', checkpoint: 'cloud-app-embed', visual: 'An application card and a File changed card are in the chat.', devices: L },
    { id: 'cloud.test_result', checkpoint: 'cloud-test-result', visual: 'The test result fullscreen shows a video and a step timeline.', devices: L },
    { id: 'cloud.commit', checkpoint: 'cloud-commit', visual: 'The last reply quotes a 7-character commit id.', devices: L },
    { id: 'cloud.project_files', checkpoint: 'cloud-project-files', visual: 'The folder lists the application card and files.', devices: B },
    { id: 'cloud.project_timeline', checkpoint: 'cloud-project-timeline', visual: 'The Timeline panel shows the commit.', devices: B },
    { id: 'cloud.spec_plan', checkpoint: 'cloud-spec-plan', visual: 'A Specification card and a Plan card are in the chat.', devices: L },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});
type Proof = ReturnType<typeof createVideoProofRuntime>;

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const TURN_TIMEOUT = 840_000;
const MODEL_QUERY = 'gemini-3.8-flash';
const MODEL_NAME = /Gemini 3\.8 Flash/i;

// Same prompt texts as cli-native-agentic-app-real.spec.ts; the model mention is inserted as a real mention.
const PROMPT = 'Build me a simple recipe web app where I can add recipes with ingredients and steps and see them in a list. Keep it small.';
const COMMAND_PROMPT = 'Install the app dependencies and run its production build in web-app, then tell me whether the build passed and which files the commands changed.';
const TEST_PROMPT = 'Add a browser test that adds one recipe and checks it appears in the list, run it, and commit when it passes.';
const SPEC_PROMPT = 'Write a Specification with Checks for adding a search box that filters recipes by name, then write a Plan for it.';

// Shared by the serial tests: the Project this run created (named by the assistant) and its chat.
let projectName = '';
let projectLabel = naturalProjectName('Recipe keeper');
let appChatTitle = '';

function requireDirectDevRealInference(): void {
  const harnessRun = process.env.OPENMATES_PROOF_REAL_DEV === '1';
  if (process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1' || (process.env.CI && !harnessRun)) {
    throw new Error('Real-inference cloud Project proof is dev-only and must never run in CI.');
  }
  if (process.env.E2E_USE_MOCKS || process.env.E2E_USE_LIVE_MOCKS) {
    throw new Error('This proof requires real inference; mock replay must be disabled.');
  }
  if (!new URL(BASE_URL).hostname.includes('.dev.')) throw new Error('This proof may target only the dev web host.');
}

async function shot(page: Page, testInfo: any, name: string): Promise<void> {
  await testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' });
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
}

function watchStorage(page: Page, testInfo: any): void {
  const path = testInfo.outputPath('storage-diagnostics.log');
  require('node:fs').writeFileSync(path, '');
  page.on('console', (message) => {
    const text = message.text();
    if (message.type() === 'debug' || !STORAGE_DIAGNOSTIC.test(text)) return;
    require('node:fs').appendFileSync(path, `${new Date().toISOString()} ${message.type()} ${text.slice(0, 300)}\n`);
  });
}

async function insertModelMention(page: Page): Promise<void> {
  await page.keyboard.insertText(` @${MODEL_QUERY}`);
  const dropdown = page.getByTestId('mention-dropdown');
  await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: MODEL_NAME }).first()).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press('Tab');
  await expect(dropdown).not.toBeVisible({ timeout: 3_000 });
}

/** Sends `prompt` with the pinned model mention typed into the web composer. */
async function send(page: Page, prompt: string, kind = 'follow-up'): Promise<void> {
  await focusMessageEditor(page.getByTestId('message-editor'));
  await page.keyboard.press('End');
  await insertModelMention(page);
  await sendMessage(page, ` ${prompt}`, undefined, undefined, kind, { preserveExistingContent: true });
}

function lastAssistant(page: Page): Locator {
  return page.getByTestId('message-assistant').last();
}

async function hasAnswerText(page: Page): Promise<boolean> {
  const text = (await lastAssistant(page).innerText()).replace(/Activated '[^']*'/g, '').replace(/generated by[^\n]*/gi, '');
  return text.replace(/\s+/g, ' ').trim().length > 40;
}

/** Approves pending Project file cards while a turn runs (the web executes the file job in the Rust core). */
async function approvePending(page: Page): Promise<void> {
  const writes = page.locator('[data-testid="project-file-approval-card"][data-status="pending"]');
  while (await writes.count() > 0) {
    await writes.last().getByTestId('project-file-approve').click();
    await page.waitForTimeout(1_000);
  }
}

/** The turn is over when it has answer text and no stop button or typing indicator shows for 8 s. */
async function waitForTurn(page: Page): Promise<void> {
  await waitForAssistantMessage(page, { timeout: TURN_TIMEOUT });
  const busy = page.locator('[data-testid="stop-processing-button"]:visible, [data-testid="typing-indicator"]:visible');
  let idleSince = 0;
  await expect.poll(async () => {
    await approvePending(page);
    if (await busy.count() > 0 || !(await hasAnswerText(page))) { idleSince = 0; return false; }
    idleSince ||= Date.now();
    return Date.now() - idleSince >= 8_000;
  }, { timeout: TURN_TIMEOUT, intervals: [2_000] }).toBe(true);
  const generatedBy = lastAssistant(page).getByTestId('generated-by');
  await expect(generatedBy).toBeVisible({ timeout: 120_000 });
  await expect(generatedBy).toContainText(MODEL_NAME);
}

async function openProject(page: Page): Promise<void> {
  await page.getByTestId('projects-nav-link').click();
  await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 60_000 });
  const card = page.getByTestId('project-landing-card').filter({ hasText: projectName }).first();
  await expect(card, `the Project "${projectName}" created by this run`).toBeVisible({ timeout: 60_000 });
  await card.click();
  await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
}

/** Files view (folder with the application card) and Timeline (the commit) of the Project. */
async function showProjectViews(page: Page, testInfo: any, label: string, proof: Proof): Promise<void> {
  await openProject(page);
  await page.getByTestId('project-tab-folders').click();
  await proof.assert('cloud.project_files', () => expect(page.getByTestId('project-folders-panel')).toBeVisible({ timeout: 60_000 }));
  const folder = page.getByTestId('project-virtual-folder-card').filter({ hasText: 'web-app' }).first();
  await expect(folder, 'the web-app folder in the Project files').toBeVisible({ timeout: 60_000 });
  await shot(page, testInfo, `${label}-20-files`);
  await folder.click();
  const card = page.getByTestId('project-item-card').first();
  await expect(card, 'application card in the folder').toContainText(/files/, { timeout: 60_000 });
  await page.waitForTimeout(2_000);
  await shot(page, testInfo, `${label}-21-files-web-app`);
  await proof.checkpoint('cloud-project-files');

  await page.getByTestId('project-tab-timeline').click();
  await proof.assert('cloud.project_timeline', async () => {
    await expect(page.getByTestId('project-timeline-panel')).toBeVisible({ timeout: 60_000 });
    await expect(page.locator('[data-testid^="project-timeline-commit-toggle-"]').first(), 'a commit in the Timeline').toBeVisible({ timeout: 60_000 });
  });
  await page.waitForTimeout(2_000);
  await shot(page, testInfo, `${label}-22-timeline`);
  await proof.checkpoint('cloud-project-timeline');
}

test.describe('Cloud agentic coding from the web app (real inference, dev only)', () => {
  test.describe.configure({ mode: 'serial', retries: 0 });
  test.use({ actionTimeout: 60_000, navigationTimeout: 60_000 });
  test.beforeAll(() => { requireDirectDevRealInference(); });

  // contract-test: direct surface=gui.web assertions=projects.files.hosted-ciphertext-commit,projects.files.write-policy-enforcement,code-run.cloud.commands,code-run.commands.files-through-file-tools
  test('laptop: recipe app, commands, recorded test, commit, preview and Project views', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(5_400_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1440, height: 900 });
    const proof = createVideoProofRuntime(proofContract, {
      device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    watchStorage(page, testInfo);
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await loginToTestAccount(page);
    await startNewChat(page);

    // a. The recipe app: Project creation, application card and file changes from the web file-job path.
    await send(page, PROMPT, 'new-chat');
    await waitForTurn(page);
    await expandActivity(page);
    await shot(page, testInfo, 'laptop-01-app-turn');
    const created = page.getByTestId('project-created-card').first();
    await expect(created, 'Project creation card in the chat (Project link)').toBeVisible({ timeout: 60_000 });
    projectName = ((await created.getByTestId('project-created-name').first().textContent()) ?? '').trim();
    expect(projectName, 'the assistant named the Project').not.toBe('');
    projectLabel = projectName || projectLabel;
    await proof.assert('cloud.app_embed', async () => {
      await expect(page.locator('[data-testid="embed-preview"][data-app-id="code"]').first(), 'application card').toBeVisible({ timeout: 60_000 });
      await expect(page.getByTestId('project-file-approval-card').first(), '"File changed" card from the web file job').toBeVisible({ timeout: 60_000 });
      await expect(page.getByTestId('project-file-change-diff').first(), 'diff of a file change').toBeAttached({ timeout: 60_000 });
    });
    appChatTitle = ((await page.getByTestId('chat-title').first().textContent().catch(() => '')) ?? '').trim();
    await proof.checkpoint('cloud-app-embed');

    // b. Install and build: code-run cards with exit code 0, and the synced-back lockfile as a diff card.
    const fileCardsBefore = await page.getByTestId('project-file-approval-card').count();
    await send(page, COMMAND_PROMPT);
    await waitForTurn(page);
    await expandActivity(page);
    await shot(page, testInfo, 'laptop-02-commands');
    const reply = lastAssistant(page);
    await expect(reply.locator('[data-testid="embed-preview"][data-app-id="code"]').first(), 'terminal/code-run card of the command turn').toBeVisible({ timeout: 60_000 });
    const cardText = (await reply.innerText()).replace(/\s+/g, ' ');
    // Each command is its own bash code card (terminal.sh); the install lockfile below proves the
    // install ran, and no card or reply may report a non-zero exit.
    expect(cardText, 'the dependency install ran as a command').toMatch(/\b(npm|pnpm|yarn)\s+(i|install|ci)\b/i);
    expect(cardText, 'the production build ran as a command').toMatch(/\b(npm|pnpm|yarn)\s+(run\s+)?build\b|\bvite\s+build\b/i);
    expect(cardText, 'no command of the turn exited non-zero').not.toMatch(/exit(?:ed)?(?:\s+with)?(?:\s+code)?:?\s*[1-9]\d*\b/i);
    await expect(page.getByTestId('project-file-approval-card').filter({ hasText: /package-lock\.json|pnpm-lock\.yaml|yarn\.lock/ }).first(),
      'lockfile synced back as a diff card').toBeVisible({ timeout: 60_000 });
    expect(await page.getByTestId('project-file-approval-card').count(), 'new file cards after commands').toBeGreaterThan(fileCardsBefore);
    await proof.checkpoint('cloud-commands');

    // c. Recorded browser test and the commit by its short id.
    await send(page, TEST_PROMPT);
    await waitForTurn(page);
    await expandActivity(page);
    await shot(page, testInfo, 'laptop-03-test-turn');
    const card = page.locator('[data-testid="embed-preview"][data-skill-id="test_result"]').last();
    await expect(card, 'test result card in chat').toBeVisible({ timeout: 90_000 });
    await card.evaluate((el: Element) => el.scrollIntoView({ block: 'center' }));
    await page.waitForTimeout(500);
    await shot(page, testInfo, 'laptop-04-test-result-card');
    const expand = await card.getByTestId('result-preview-expand').boundingBox();
    expect(expand, 'test result expand control').not.toBeNull();
    if (expand) await page.mouse.click(expand.x + expand.width / 2, expand.y + expand.height / 2);
    await proof.assert('cloud.test_result', async () => {
      await expect(page.getByTestId('test-result-fullscreen-body')).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId('test-result-video'), 'recorded test video').toBeVisible({ timeout: 60_000 });
      await expect(page.getByTestId('test-result-timeline'), 'step timeline').toBeVisible();
    });
    await page.getByTestId('test-result-video').evaluate((el: HTMLVideoElement) => { el.muted = true; return el.play(); }).catch(() => undefined);
    await page.waitForTimeout(4_000);
    // The step timings (earlier proof: 2 s video against a 19.6 s duration) as their own attachment.
    await testInfo.attach('test-result-step-timeline', { body: await page.getByTestId('test-result-timeline').screenshot(), contentType: 'image/png' });
    await shot(page, testInfo, 'laptop-05-test-result-fullscreen');
    await proof.checkpoint('cloud-test-result');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(1_000);
    const replyText = await lastAssistant(page).innerText();
    await proof.assert('cloud.commit', async () => {
      expect(replyText, 'reply quotes the commit by a 7-character short id').toMatch(/\b[0-9a-f]{7}\b/);
      expect(replyText, 'reply must not show a 40-character commit id').not.toMatch(/\b[0-9a-f]{40}\b/);
    });
    await shot(page, testInfo, 'laptop-06-commit-reply');
    await proof.checkpoint('cloud-commit');

    // d. Preview from the application card, then the Project views.
    await page.goto(`${BASE_URL}/`);
    const openedChat = page.getByTestId('chat-title').filter({ hasText: appChatTitle }).first();
    if (appChatTitle && await openedChat.count() > 0) await openedChat.click();
    const app = page.locator('[data-testid="embed-preview"][data-app-id="code"]').first();
    await expect(app, 'application card for the preview').toBeVisible({ timeout: 90_000 });
    await app.getByTestId('result-preview-expand').click();
    const start = page.getByTestId('application-start-preview');
    const frame = page.getByTestId('application-preview-iframe');
    await expect(start.or(frame).first(), 'application fullscreen').toBeVisible({ timeout: 30_000 });
    if (await start.isVisible() && await start.isEnabled()) await start.click();
    await expect(frame, 'running application preview').toBeVisible({ timeout: 240_000 });
    await expect(page.frameLocator('[data-testid="application-preview-iframe"]').locator('body')).not.toBeEmpty({ timeout: 60_000 });
    await shot(page, testInfo, 'laptop-07-preview');
    await proof.checkpoint('cloud-preview');
    const stop = page.getByTestId('application-stop-preview');
    if (await stop.isVisible() && await stop.isEnabled()) await stop.click();
    await page.keyboard.press('Escape');

    await showProjectViews(page, testInfo, 'laptop', proof);
    await proof.attach();
  });

  // contract-test: direct surface=gui.web assertions=projects.files.hosted-ciphertext-commit
  test('phone: the Project files and Timeline', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(900_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 390, height: 844 });
    const proof = createVideoProofRuntime(proofContract, {
      device: 'web-phone', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    expect(projectName, 'the laptop test created a Project').not.toBe('');
    await loginToTestAccount(page);
    await showProjectViews(page, testInfo, 'phone', proof);
    await proof.attach();
  });

  // Last: a failure here (for example a missing Specification embed) must not hide the steps above.
  // contract-test: direct surface=gui.web assertions=code-run.tests.recorded-evidence,projects.files.hosted-ciphertext-commit
  test('laptop: a new chat in the Project writes a Specification with Checks and a Plan', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(1_800_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    expect(projectName, 'the laptop test created a Project').not.toBe('');
    await page.setViewportSize({ width: 1440, height: 900 });
    const proof = createVideoProofRuntime(proofContract, {
      device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    watchStorage(page, testInfo);
    await loginToTestAccount(page);
    await openProject(page);
    await page.getByTestId('project-tab-folders').click();
    await expect(page.getByTestId('project-folders-panel')).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('project-folder-create-menu-button').click();
    await expect(page.getByTestId('project-create-menu')).toBeVisible();
    await page.getByTestId('project-create-chat').click();
    await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('message-field').click();
    await send(page, SPEC_PROMPT, 'project-chat');
    await waitForTurn(page);
    await expandActivity(page);
    await shot(page, testInfo, 'laptop-30-spec-plan');
    const specCard = page.locator('[data-testid="message-assistant"] [data-testid="specification-embed-card"]');
    const planCard = page.locator('[data-testid="message-assistant"] [data-testid="plan-embed-preview"]');
    const missing: string[] = [];
    if (await specCard.count() === 0) missing.push('Specification card (specification-embed-card)');
    if (await planCard.count() === 0) missing.push('Plan card (plan-embed-preview)');
    await proof.assert('cloud.spec_plan', async () => {
      expect(missing, `artifacts that did not show in the reply: ${missing.join(', ') || 'none'}`).toEqual([]);
    });
    await proof.checkpoint('cloud-spec-plan');
    await proof.attach();
  });
});
