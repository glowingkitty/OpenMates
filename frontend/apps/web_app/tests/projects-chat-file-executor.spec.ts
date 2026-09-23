/* eslint-disable @typescript-eslint/no-require-imports */
/** Real-inference browser coverage for hosted and remote Project file execution. */
export {};

import type { ChildProcessWithoutNullStreams } from 'node:child_process';
import type { Locator, Page, Response } from '@playwright/test';

const { spawn, spawnSync } = require('node:child_process');
const { chmodSync, mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const { randomUUID } = require('node:crypto');
const { test, expect } = require('./helpers/cookie-audit');
const {
  deleteActiveChat,
  loginToTestAccount,
  sendMessage,
  startNewChat,
  waitForAssistantMessage,
  waitForChatReady,
} = require('./helpers/chat-test-helpers');
const { closeFullscreen } = require('./helpers/embed-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL
  || BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');
const REPO_ROOT = resolve(__dirname, '../../../..');
const CLI_DIR = resolve(REPO_ROOT, 'frontend/packages/openmates-cli');

interface RemoteFixtureEvent {
  event: string;
  project_id?: string;
  project_name?: string;
  source_id?: string;
  path?: string;
  content_base64?: string;
  size_bytes?: number;
  path_privacy_verified?: boolean;
}

function requireDirectDevRealInference(): void {
  if (process.env.CI || process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1') {
    throw new Error('Browser Project real-inference verification is dev-only and must never run in CI or an isolated CI job.');
  }
  if (process.env.OPENMATES_PROJECT_CHAT_REAL_AI !== '1') {
    throw new Error('Set OPENMATES_PROJECT_CHAT_REAL_AI=1 to acknowledge this targeted dev-only real-inference run.');
  }
  if (process.env.E2E_USE_MOCKS || process.env.E2E_USE_LIVE_MOCKS) {
    throw new Error('Browser Project file verification requires real inference; mock replay must be disabled.');
  }
  if (!new URL(BASE_URL).hostname.includes('.dev.') || !new URL(API_BASE_URL).hostname.includes('.dev.')) {
    throw new Error('Browser Project real-inference verification may target only the dev web and API hosts.');
  }
  if (!TEST_EMAIL || !TEST_PASSWORD || !TEST_OTP_KEY) {
    throw new Error('Browser Project real-inference verification requires OPENMATES_TEST_ACCOUNT_* credentials.');
  }
}

function runChecked(command: string, args: string[], cwd = REPO_ROOT, env = process.env): void {
  const result = spawnSync(command, args, { cwd, env, encoding: 'utf-8' });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed:\n${result.stdout}\n${result.stderr}`);
  }
}

function waitForFixtureEvent(
  processHandle: ChildProcessWithoutNullStreams,
  eventName: string,
  timeoutMs = 60_000,
): Promise<RemoteFixtureEvent> {
  return new Promise((resolvePromise, reject) => {
    let buffered = '';
    let diagnostics = '';
    const cleanup = () => {
      clearTimeout(timeout);
      processHandle.stdout.off('data', onData);
      processHandle.off('exit', onExit);
    };
    const onData = (chunk: Buffer) => {
      const text = chunk.toString();
      diagnostics = `${diagnostics}${text}`.slice(-32_000);
      buffered += text;
      const lines = buffered.split('\n');
      buffered = lines.pop() ?? '';
      for (const line of lines) {
        try {
          const payload = JSON.parse(line) as RemoteFixtureEvent;
          if (payload.event !== eventName) continue;
          cleanup();
          resolvePromise(payload);
          return;
        } catch {
          // CLI status lines are intentionally mixed with structured fixture events.
        }
      }
    };
    const onExit = (code: number | null) => {
      cleanup();
      reject(new Error(`Remote fixture exited before ${eventName} (${code}): ${diagnostics}`));
    };
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error(`Timed out waiting for ${eventName}: ${diagnostics}`));
    }, timeoutMs);
    processHandle.stdout.on('data', onData);
    processHandle.once('exit', onExit);
  });
}

async function createProject(page: Page, name: string, writeMode: 'always_ask' | 'apply_and_show'): Promise<string> {
  await page.goto('/projects', { waitUntil: 'domcontentloaded' });
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
  return projectId as string;
}

async function deleteProject(page: Page, projectId: string): Promise<void> {
  await page.goto(`/projects#project-id=${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
  const deleted = page.waitForResponse(
    (response: Response) => response.request().method() === 'DELETE'
      && new URL(response.url()).pathname === `/v1/projects/${projectId}`
      && response.ok(),
  );
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByTestId('project-delete-button').click();
  await deleted;
}

async function sendWithProjectMention(
  page: Page,
  projectName: string,
  prompt: string,
  accessMode: 'read' | 'read_write',
): Promise<void> {
  const editor = page.getByTestId('message-editor');
  await editor.click();
  await page.keyboard.insertText(`@${projectName}`);
  const dropdown = page.getByTestId('mention-dropdown');
  await expect(dropdown).toBeVisible({ timeout: 15_000 });
  const projectResult = dropdown
    .locator('[data-testid="mention-result"][data-mention-type="project"]')
    .filter({ hasText: projectName })
    .first();
  await expect(projectResult).toBeVisible({ timeout: 15_000 });
  await projectResult.click();
  const accessChip = editor.getByTestId('project-access-chip');
  await expect(accessChip).toBeVisible();
  if (await accessChip.getAttribute('data-project-access-mode') !== accessMode) {
    await accessChip.click();
  }
  await expect(accessChip).toHaveAttribute('data-project-access-mode', accessMode);
  await sendMessage(page, ` ${prompt}`, undefined, undefined, 'project-file', { preserveExistingContent: true });
}

async function approvePendingWrite(page: Page, path: string, expectedChange: string): Promise<void> {
  const pending = page.locator('[data-testid="project-file-approval-card"][data-status="pending"]')
    .filter({ hasText: path })
    .last();
  await expect(pending).toBeVisible({ timeout: 240_000 });
  await expect(pending.getByTestId('project-file-change-diff')).toContainText(expectedChange);
  await pending.getByTestId('project-file-approve').click();
  await expect(pending).toHaveCount(0, { timeout: 60_000 });
  await expect(page.locator('[data-testid="project-file-approval-card"][data-status="applied"]')
    .filter({ hasText: path }).last()).toBeVisible({ timeout: 120_000 });
}

async function waitForTurnCompletion(page: Page): Promise<void> {
  await waitForAssistantMessage(page, { timeout: 300_000 });
  await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-processing', 'false', {
    timeout: 300_000,
  });
}

async function expectProjectFocusPill(page: Page, projectName: string): Promise<void> {
  const pill = page.getByTestId('focus-pill');
  await expect(pill).toBeVisible({ timeout: 30_000 });
  await expect(pill.getByTestId('focus-pill-label')).toHaveText(`Work on ${projectName}`);
  await expect(pill.getByTestId('focus-pill-toggle').locator('input[type="checkbox"]')).toBeChecked();
}

async function currentChatId(page: Page): Promise<string> {
  const fromUrl = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
  const chatId = fromUrl
    || await page.locator('[data-action="message-input"]').last().getAttribute('data-current-chat-id');
  expect(chatId).toBeTruthy();
  return chatId as string;
}

async function deactivateProjectFocusAndVerify(page: Page, projectId: string): Promise<void> {
  const chatId = await currentChatId(page);
  const deactivated = page.waitForResponse(
    (response: Response) => response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/v1/projects/focus/deactivate'
      && response.ok(),
  );
  await page.getByTestId('focus-pill-toggle').locator('input[type="checkbox"]').click();
  await deactivated;
  await expect(page.getByTestId('focus-pill')).toHaveCount(0, { timeout: 30_000 });
  const authority = await page.evaluate(async ({ apiBaseUrl, activeChatId }) => {
    const response = await fetch(
      `${apiBaseUrl}/v1/projects/focus/current?chat_id=${encodeURIComponent(activeChatId)}`,
      { credentials: 'include' },
    );
    return { status: response.status, body: await response.json() as { focus?: { project_id?: string } | null } };
  }, { apiBaseUrl: API_BASE_URL, activeChatId: chatId });
  expect(authority.status).toBe(200);
  expect(authority.body.focus?.project_id).not.toBe(projectId);
  expect(authority.body.focus ?? null).toBeNull();
}

async function readFullscreenCodeLines(overlay: Locator): Promise<string[]> {
  const source = overlay.getByTestId('code-fullscreen-code');
  await expect(source).toBeVisible({ timeout: 30_000 });
  return source.locator('.code-line-text').allTextContents();
}

test.describe('Browser Project file chat execution (real inference, dev only)', () => {
  test.describe.configure({ retries: 0 });

  test.beforeAll(() => {
    requireDirectDevRealInference();
  });

  test.beforeEach(async ({ page }: { page: Page }) => {
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await loginToTestAccount(page);
  });

  // contract-test: direct surface=gui.web assertions=projects.files.hosted-ciphertext-commit,projects.files.expected-base,projects.files.exact-patch,projects.files.chat-focus-required,projects.files.write-policy-enforcement
  test('creates and updates an encrypted hosted file through explicit Project focus and approval', async ({ page }: { page: Page }) => {
    test.setTimeout(900_000);
    const projectName = `Browser hosted ${randomUUID().slice(0, 8)}`;
    const path = 'proofs/browser-hosted-proof.txt';
    const marker = `hosted-${randomUUID()}`;
    const sentWebSocketMessages: Array<Record<string, unknown>> = [];
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Network.enable');
    cdp.on('Network.webSocketFrameSent', ({ response }: { response: { payloadData: string } }) => {
      try {
        const message = JSON.parse(response.payloadData) as Record<string, unknown>;
        sentWebSocketMessages.push(message);
      } catch {
        // Binary/control frames and non-JSON traffic are irrelevant here.
      }
    });
    let projectId: string | null = null;
    let chatUrl: string | null = null;
    try {
      projectId = await createProject(page, projectName, 'always_ask');
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await startNewChat(page);
      await waitForChatReady(page);

      await sendWithProjectMention(
        page,
        projectName,
        `Use the active Project file tools now. Create exactly one file named ${path} with exactly these two lines and a final newline:\n${marker}\noriginal\nThen read the file back. Do not use code.run or give me instructions to perform the edit.`,
        'read_write',
      );
      chatUrl = page.url();
      await expectProjectFocusPill(page, projectName);
      await approvePendingWrite(page, path, marker);
      await waitForTurnCompletion(page);

      await page.reload({ waitUntil: 'domcontentloaded' });
      await waitForChatReady(page);
      await expectProjectFocusPill(page, projectName);

      await sendMessage(
        page,
        `Read ${path}, then use an exact Project update patch to change only the second line from original to updated. Preserve the first line and final newline. Read it back after the update.`,
      );
      await approvePendingWrite(page, path, 'updated');
      await waitForTurnCompletion(page);
      await deactivateProjectFocusAndVerify(page, projectId);
      await deleteActiveChat(page);
      chatUrl = null;

      await page.goto(`/projects#project-id=${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
      const folder = page.getByTestId('project-virtual-folder-card').filter({ hasText: 'proofs' }).first();
      await expect(folder).toBeVisible({ timeout: 30_000 });
      await folder.click();
      const item = page.getByTestId('project-item-card').filter({ hasText: 'browser-hosted-proof.txt' }).first();
      await expect(item).toBeVisible({ timeout: 30_000 });
      await expect(item).toHaveAttribute('aria-disabled', 'false', { timeout: 30_000 });
      await item.click();
      const overlay = page.getByTestId('embed-fullscreen-overlay').last();
      await expect(overlay).toBeVisible({ timeout: 30_000 });
      expect(await readFullscreenCodeLines(overlay)).toEqual([marker, 'updated', '']);
      await expect(overlay.getByTestId('embed-version-timeline')).toBeVisible({ timeout: 30_000 });
      await expect(overlay.getByTestId('version-dot-2')).toBeVisible();
      await closeFullscreen(page, overlay);

      const encryptedCommits = sentWebSocketMessages.filter((message) => message.type === 'commit_embed_revision');
      expect(encryptedCommits).toHaveLength(2);
      expect(JSON.stringify(encryptedCommits)).not.toContain(marker);
      for (const message of encryptedCommits) {
        const payload = message.payload as { head?: { encrypted_content?: unknown } };
        expect(typeof payload.head?.encrypted_content).toBe('string');
      }
    } finally {
      await cdp.detach().catch(() => undefined);
      if (chatUrl) {
        await page.goto(chatUrl, { waitUntil: 'domcontentloaded' }).catch(() => undefined);
        await deleteActiveChat(page);
      }
      if (projectId) await deleteProject(page, projectId);
    }
  });

  // contract-test: direct surface=gui.web assertions=projects.files.expected-base,projects.files.exact-patch,projects.files.chat-focus-required,projects.files.no-server-decryption-authority,projects.files.write-policy-enforcement
  test('reads and updates the original remote file through the browser WebSocket executor', async ({ page }: { page: Page }) => {
    test.setTimeout(900_000);
    const fixtureStateDir = mkdtempSync(join(tmpdir(), 'openmates-browser-project-chat-'));
    chmodSync(fixtureStateDir, 0o700);
    runChecked('npm', ['run', 'build'], CLI_DIR);
    runChecked(
      'node',
      ['scripts/openmates_cli_test_account.mjs', 'login', '--api-url', API_BASE_URL, '--web-origin', new URL(BASE_URL).origin],
      REPO_ROOT,
      {
        ...process.env,
        OPENMATES_STATE_DIR: fixtureStateDir,
        OPENMATES_TEST_ACCOUNT_EMAIL: TEST_EMAIL,
        OPENMATES_TEST_ACCOUNT_PASSWORD: TEST_PASSWORD,
        OPENMATES_TEST_ACCOUNT_OTP_KEY: TEST_OTP_KEY,
        OPENMATES_TEST_ACCOUNT_SOURCE_SLOT: '',
      },
    );
    const marker = `remote-${randomUUID()}`;
    const expectedContent = `export const remoteDemo = "${marker}";\nexport const imported = true;\n`;
    let chatUrl: string | null = null;
    const bridge = spawn(
      'node',
      [
        '--experimental-strip-types',
        '--loader',
        './frontend/packages/openmates-cli/tests/loader.mjs',
        'scripts/project_remote_access_live.mjs',
        'serve',
        API_BASE_URL,
      ],
      {
        cwd: REPO_ROOT,
        env: {
          ...process.env,
          OPENMATES_STATE_DIR: fixtureStateDir,
          OPENMATES_REMOTE_HOST_SESSION: join(fixtureStateDir, 'session.json'),
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    ) as ChildProcessWithoutNullStreams;
    bridge.stderr.resume();
    try {
      const fixture = await waitForFixtureEvent(bridge, 'fixture_ready', 90_000);
      expect(fixture.path_privacy_verified).toBe(true);
      expect(fixture.project_id).toBeTruthy();
      expect(fixture.project_name).toBeTruthy();

      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await startNewChat(page);
      await waitForChatReady(page);
      await sendWithProjectMention(
        page,
        fixture.project_name as string,
        `Use the active Project file tools now. Read src/remote-demo.ts, then use an exact Project update patch to replace only the string OpenMates live remote preview with ${marker}. Preserve every other byte and read the file back. Do not use code.run or give me instructions to perform the edit.`,
        'read_write',
      );
      chatUrl = page.url();
      await expectProjectFocusPill(page, fixture.project_name as string);
      await waitForTurnCompletion(page);
      await expect(page.locator('[data-testid="project-file-approval-card"][data-status="applied"]')
        .filter({ hasText: 'src/remote-demo.ts' }).last()).toBeVisible({ timeout: 120_000 });

      const remoteStatePromise = waitForFixtureEvent(bridge, 'remote_file_state');
      bridge.kill('SIGUSR2');
      const remoteState = await remoteStatePromise;
      expect(remoteState.path).toBe('src/remote-demo.ts');
      expect(remoteState.size_bytes).toBe(Buffer.byteLength(expectedContent));
      expect(Buffer.from(remoteState.content_base64 as string, 'base64').toString('utf8')).toBe(expectedContent);
      await deactivateProjectFocusAndVerify(page, fixture.project_id as string);
      await deleteActiveChat(page);
      chatUrl = null;

      await page.goto(`/projects#project-id=${encodeURIComponent(fixture.project_id as string)}`, { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);
      const sourceCard = page.getByTestId('project-remote-source-card').filter({ hasText: 'Live remote source' });
      await expect(sourceCard).toBeVisible({ timeout: 30_000 });
      await page.getByTestId('project-connected-source-root').filter({ hasText: 'Live remote source' }).click();
      await sourceCard.getByTestId('project-remote-entry').filter({ hasText: /^src$/ }).click();
      const preview = sourceCard.getByTestId('project-remote-preview-card').filter({ hasText: 'remote-demo.ts' });
      await expect(preview).toBeVisible({ timeout: 30_000 });
      await preview.getByTestId('project-remote-preview-open').click();
      const overlay = page.getByTestId('project-remote-fullscreen-overlay');
      await expect(overlay).toBeVisible({ timeout: 30_000 });
      expect(await readFullscreenCodeLines(overlay)).toEqual([
        `export const remoteDemo = "${marker}";`,
        'export const imported = true;',
        '',
      ]);
      await closeFullscreen(page, overlay);
    } finally {
      if (chatUrl) {
        await page.goto(chatUrl, { waitUntil: 'domcontentloaded' }).catch(() => undefined);
        await deleteActiveChat(page);
      }
      if (bridge.exitCode === null) {
        bridge.kill('SIGTERM');
        await new Promise<void>((resolvePromise) => bridge.once('exit', () => resolvePromise()));
      }
      rmSync(fixtureStateDir, { recursive: true, force: true });
    }
  });
});
