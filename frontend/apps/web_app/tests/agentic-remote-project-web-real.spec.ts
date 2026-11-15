/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Real-inference, dev-only Flow 2 from the web app: in a Project whose files live in a folder on
 * the user's connected machine, one chat goes from a Specification with Checks to a Plan, writes
 * code and unit tests into the machine folder, runs the tests there, shows the preview and commits.
 * Then the Project views (Specifications, Checks, files on the machine, Timeline) are shown at
 * laptop size and again at phone size.
 *
 * Needs the remote-access host of the machine running and connected, serving the Project folder.
 * Run through scripts/agentic_remote_project_web_real_test.py; never in CI, no mocks.
 * OPENMATES_FLOW2_PROJECT_NAME names the existing machine Project (default "Garden Planner").
 */
export {};

import type { Locator, Page } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const {
  focusMessageEditor, loginToTestAccount, sendMessage, waitForAssistantMessage,
} = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const L = ['web-laptop'];
const B = ['web-laptop', 'web-phone'];
const proofContract = defineVideoProof({
  id: 'agentic-remote-project-web-real',
  title: 'Flow 2 in the web app: Specification to commit in a Project on a connected machine',
  surface: 'web',
  devices: ['web-laptop', 'web-phone'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'spec', text: 'The writing focus starts at once and the chat shows the new Specification and its Checks.', checkpoint: 'flow2-specification', devices: L },
    { id: 'plan', text: 'The planner focus writes the Plan.', checkpoint: 'flow2-plan', devices: L },
    { id: 'code', text: 'The assistant writes the code and unit tests into the folder on the machine.', checkpoint: 'flow2-code', devices: L },
    { id: 'tests', text: 'The unit tests run on the machine and the reply reports the result.', checkpoint: 'flow2-tests', devices: L },
    { id: 'preview', text: 'The preview shows the app with the harvest log.', checkpoint: 'flow2-preview', devices: L },
    { id: 'commit', text: 'The changes are committed on the machine.', checkpoint: 'flow2-commit', devices: L },
    { id: 'specs-view', text: 'The Project overview lists the Specification and its Checks.', checkpoint: 'flow2-project-specs', devices: B },
    { id: 'files-view', text: 'The Project files show the folder on the machine.', checkpoint: 'flow2-project-files', devices: B },
    { id: 'timeline-view', text: 'The Timeline tab of the Project opens.', checkpoint: 'flow2-project-timeline', devices: B },
  ],
  assertions: [
    { id: 'flow2.specification', checkpoint: 'flow2-specification', visual: 'A Specification card is in the chat.', devices: L },
    { id: 'flow2.commit', checkpoint: 'flow2-commit', visual: 'The last reply reports the commit on the machine.', devices: L },
    { id: 'flow2.project_specs', checkpoint: 'flow2-project-specs', visual: 'The Specifications and Checks sections are visible in the Project.', devices: B },
    { id: 'flow2.project_files', checkpoint: 'flow2-project-files', visual: 'The files panel of the Project is visible.', devices: B },
    { id: 'flow2.project_timeline', checkpoint: 'flow2-project-timeline', visual: 'The Timeline panel of the Project is visible.', devices: B },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});
type Proof = ReturnType<typeof createVideoProofRuntime>;

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const PROJECT_NAME = process.env.OPENMATES_FLOW2_PROJECT_NAME || 'Garden Planner';
const TURN_TIMEOUT = 600_000;
const MODEL_QUERY = 'gemini-3.8-flash';
const MODEL_NAME = /Gemini 3\.8 Flash/i;

const FEATURE = 'I would like the Garden Planner to keep a harvest log: for each bed I can record a harvest with a date, '
  + 'the crop and its weight in grams, see the total harvested per bed this season, and delete a wrong entry. '
  + 'Read the existing files of the project first.';

// The chat of the laptop run, reopened by the phone run.
let flowChatTitle = '';

function requireDirectDevRealInference(): void {
  // The dev proof harness runs this spec in an E2B sandbox, which sets CI=1 for its tools; only the
  // harness sets OPENMATES_PROOF_REAL_DEV (it refuses to start under CI itself). GitHub CI never does.
  const harnessRun = process.env.OPENMATES_PROOF_REAL_DEV === '1';
  if (process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1' || (process.env.CI && !harnessRun)) {
    throw new Error('Real-inference Flow 2 proof is dev-only and must never run in CI.');
  }
  if (process.env.E2E_USE_MOCKS || process.env.E2E_USE_LIVE_MOCKS) {
    throw new Error('This proof requires real inference; mock replay must be disabled.');
  }
  if (!new URL(BASE_URL).hostname.includes('.dev.')) {
    throw new Error('This proof may target only the dev web host.');
  }
}

async function shot(page: Page, testInfo: any, name: string): Promise<void> {
  const body = await page.screenshot();
  await testInfo.attach(name, { body, contentType: 'image/png' });
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
}

/** Opens the machine Project through in-app navigation (a reload can drop the session). */
async function openProject(page: Page): Promise<void> {
  await page.getByTestId('projects-nav-link').click();
  await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 60_000 });
  // The Projects start screen lists recent Projects as landing cards (WorkspaceHomeShell itemTestId).
  const card = page.getByTestId('project-landing-card').filter({ hasText: PROJECT_NAME }).first();
  await expect(card, `machine Project "${PROJECT_NAME}"`).toBeVisible({ timeout: 60_000 });
  await card.click();
  await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
}

async function insertModelMention(page: Page): Promise<void> {
  await page.keyboard.insertText(` @${MODEL_QUERY}`);
  const dropdown = page.getByTestId('mention-dropdown');
  await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: MODEL_NAME }).first())
    .toBeVisible({ timeout: 10_000 });
  await page.keyboard.press('Tab');
  await expect(dropdown).not.toBeVisible({ timeout: 3_000 });
}

/** Sends `prompt` with the pinned model; `prefix` is raw mention text such as `@focus:code:write_specification`. */
async function send(page: Page, prompt: string, prefix = '', kind = 'follow-up'): Promise<void> {
  const editor = page.getByTestId('message-editor');
  await focusMessageEditor(editor);
  if (prefix) {
    await page.keyboard.insertText(prefix);
    // A raw @focus mention is plain text; close any suggestion list it opened.
    await page.keyboard.insertText(' ');
    if (await page.getByTestId('mention-dropdown').isVisible()) await page.keyboard.press('Escape');
  }
  await insertModelMention(page);
  await sendMessage(page, ` ${prompt}`, undefined, undefined, kind, { preserveExistingContent: true });
}

/** Approves pending Project file cards and test commands while a turn runs. */
async function approvePending(page: Page, testInfo: any): Promise<void> {
  const writes = page.locator('[data-testid="project-file-approval-card"][data-status="pending"]');
  while (await writes.count() > 0) {
    await writes.last().getByTestId('project-file-approve').click();
    await page.waitForTimeout(1_000);
  }
  const command = page.locator('[data-testid="remote-command-review-card"]')
    .filter({ has: page.getByTestId('remote-command-approve') }).last();
  if (await command.count() > 0 && await command.getByTestId('remote-command-approve').isVisible()) {
    const argv = (await command.getByTestId('remote-command-argv').textContent()) ?? '';
    await shot(page, testInfo, 'command-review');
    // Only a test run is approved; anything else is declined so the proof never runs other commands.
    if (/\b(test|vitest|jest)\b/i.test(argv)) await command.getByTestId('remote-command-approve').click();
    else await command.getByTestId('remote-command-reject').click();
  }
}

/** The turn is over when no stop button or typing indicator shows for 8 s; approvals are answered meanwhile. */
async function waitForTurn(page: Page, testInfo: any): Promise<void> {
  await waitForAssistantMessage(page, { timeout: TURN_TIMEOUT });
  const busy = page.locator('[data-testid="stop-processing-button"]:visible, [data-testid="typing-indicator"]:visible');
  let idleSince = 0;
  await expect.poll(async () => {
    await approvePending(page, testInfo);
    if (await busy.count() > 0) { idleSince = 0; return false; }
    idleSince ||= Date.now();
    return Date.now() - idleSince >= 8_000;
  }, { timeout: TURN_TIMEOUT, intervals: [2_000] }).toBe(true);
  const generatedBy = page.getByTestId('message-assistant').last().getByTestId('generated-by');
  await expect(generatedBy).toBeVisible({ timeout: 120_000 });
  await expect(generatedBy).toContainText(MODEL_NAME);
}

function lastAssistant(page: Page): Locator {
  return page.getByTestId('message-assistant').last();
}

/** Overview (Specifications, Checks), files on the machine and the Timeline of the Project. */
async function showProjectViews(page: Page, testInfo: any, label: string, proof: Proof): Promise<void> {
  await openProject(page);
  await shot(page, testInfo, `${label}-10-project-overview`);
  const specs = page.getByTestId('project-specifications-section');
  await proof.assert('flow2.project_specs', async () => {
    await expect(specs).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('project-checks-section')).toBeVisible({ timeout: 60_000 });
  });
  await specs.scrollIntoViewIfNeeded();
  await proof.checkpoint('flow2-project-specs');
  await shot(page, testInfo, `${label}-11-specifications`);
  const specCard = specs.getByTestId('specification-embed-card').first();
  if (await specCard.count() > 0) {
    await specCard.click();
    await expect(page.getByTestId('spec-requirement').first()).toBeVisible({ timeout: 60_000 });
    await page.waitForTimeout(1_500);
    await shot(page, testInfo, `${label}-12-specification-open`);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(1_000);
  }
  const checks = page.getByTestId('project-checks-section');
  await expect(checks).toBeVisible({ timeout: 60_000 });
  await checks.scrollIntoViewIfNeeded();
  await shot(page, testInfo, `${label}-13-checks`);

  await page.getByTestId('project-tab-folders').click();
  await proof.assert('flow2.project_files', () => expect(page.getByTestId('project-folders-panel')).toBeVisible({ timeout: 60_000 }));
  await page.waitForTimeout(3_000);
  await proof.checkpoint('flow2-project-files');
  await shot(page, testInfo, `${label}-14-files`);
  const webApp = page.getByTestId('project-folders-panel').getByText('web-app', { exact: true }).first();
  if (await webApp.count() > 0) {
    await webApp.click();
    await page.waitForTimeout(3_000);
    await shot(page, testInfo, `${label}-15-files-web-app`);
  }

  await page.getByTestId('project-tab-timeline').click();
  await proof.assert('flow2.project_timeline', () => expect(page.getByTestId('project-timeline-panel')).toBeVisible({ timeout: 60_000 }));
  await page.waitForTimeout(3_000);
  await proof.checkpoint('flow2-project-timeline');
  await shot(page, testInfo, `${label}-16-timeline`);
}

test.describe('Flow 2 from the web app: spec to commit on a connected machine (real inference, dev only)', () => {
  test.describe.configure({ mode: 'serial', retries: 0 });
  test.use({ actionTimeout: 60_000, navigationTimeout: 60_000 });

  test.beforeAll(() => {
    requireDirectDevRealInference();
  });

  // contract-test: direct surface=gui.web assertions=projects.creation.machine-folder,focus-modes.explicit-activation
  test('laptop: specification, checks, plan, code, tests, preview and commit on the machine', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(5_400_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 1440, height: 900 });
    const proof = createVideoProofRuntime(proofContract, {
      device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await loginToTestAccount(page);

    await openProject(page);
    await shot(page, testInfo, 'laptop-00-project-before');
    // The Project already has its overview, so a new chat starts from the Files tab's Create menu.
    await page.getByTestId('project-tab-folders').click();
    await expect(page.getByTestId('project-folders-panel')).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('project-folder-create-menu-button').click();
    await expect(page.getByTestId('project-create-menu')).toBeVisible();
    await page.getByTestId('project-create-chat').click();
    await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 60_000 });

    // 1. Specification and Checks; the named focus activates at once over the Project focus.
    await send(page, `${FEATURE} Please help me write the Specification for this, with its Checks.`,
      '@focus:code:write_specification', 'project-chat');
    await waitForTurn(page, testInfo);
    await shot(page, testInfo, 'laptop-01-specification');
    await proof.assert('flow2.specification', () => expect(page.locator('[data-testid="message-assistant"] [data-testid="specification-embed-card"], [data-testid="embed-preview"][data-app-id="plans"]').first(),
      'a Specification embed in the chat').toBeVisible({ timeout: 120_000 }));
    await proof.checkpoint('flow2-specification');

    // 2. The Plan.
    await send(page, 'Thanks, the Specification looks right. Now create the Plan for implementing it.',
      '@focus:code:project_planner');
    await waitForTurn(page, testInfo);
    await shot(page, testInfo, 'laptop-02-plan');
    await proof.checkpoint('flow2-plan');

    // 3. Code and unit tests written into the machine folder.
    await send(page, 'Please implement the Plan now: write the code and its unit tests into the web-app folder of the project '
      + 'and add the harvest log to web-app/index.html so I can preview it.');
    await waitForTurn(page, testInfo);
    await shot(page, testInfo, 'laptop-03-code');
    await proof.checkpoint('flow2-code');

    // 4. The unit tests run on the machine.
    await send(page, 'Run the unit tests on my machine and tell me the result.');
    await waitForTurn(page, testInfo);
    await shot(page, testInfo, 'laptop-04-tests');
    await proof.checkpoint('flow2-tests');

    // 5. The preview of the app.
    await send(page, 'Show me the preview of the app with the harvest log.');
    await waitForTurn(page, testInfo);
    await shot(page, testInfo, 'laptop-05-preview-reply');
    const preview = page.locator('[data-testid="embed-preview"]').last();
    if (await preview.count() > 0) {
      const expand = preview.getByTestId('result-preview-expand');
      if (await expand.count() > 0) await expand.click(); else await preview.click();
      await page.waitForTimeout(5_000);
      await shot(page, testInfo, 'laptop-06-preview-open');
      await proof.checkpoint('flow2-preview');
      await page.keyboard.press('Escape');
      await page.waitForTimeout(1_000);
    }

    // 6. The commit on the machine.
    await send(page, 'Looks good. Please commit these changes on my machine with a clear commit message.');
    await waitForTurn(page, testInfo);
    await shot(page, testInfo, 'laptop-07-commit');
    await proof.assert('flow2.commit', () => expect(lastAssistant(page)).toContainText(/commit/i));
    await proof.checkpoint('flow2-commit');
    flowChatTitle = ((await page.getByTestId('chat-title').first().textContent().catch(() => '')) ?? '').trim();

    await showProjectViews(page, testInfo, 'laptop', proof);
    await proof.attach();
  });

  // contract-test: direct surface=gui.web assertions=projects.creation.machine-folder
  test('phone: the same Project views and the chat', async ({ page }: { page: Page }, testInfo: any) => {
    test.setTimeout(900_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.setViewportSize({ width: 390, height: 844 });
    const proof = createVideoProofRuntime(proofContract, {
      device: 'web-phone', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
    });
    await loginToTestAccount(page);
    await showProjectViews(page, testInfo, 'phone', proof);
    await proof.attach();
    console.log(`[flow2] laptop chat title: ${flowChatTitle || '(unknown)'}`);
  });
});
