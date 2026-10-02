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
  focusMessageEditor,
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

function syntheticMarker(prefix: string): string {
  // Keep transport identity checks independent of phone-number PII detection.
  return `${prefix}-${randomUUID().replace(/[0-9]/g, (digit: string) => String.fromCharCode(103 + Number(digit)))}`;
}

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
      processHandle.stderr.off('data', onStderr);
      processHandle.off('exit', onExit);
    };
    const onStderr = (chunk: Buffer) => {
      diagnostics = `${diagnostics}${chunk.toString()}`.slice(-32_000);
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
    processHandle.stderr.on('data', onStderr);
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
  // Use the browser's authenticated fetch and CSRF context; bound cleanup so
  // a failed composer cannot conceal the actual assertion behind an overlay.
  const status = await page.evaluate(async ({ apiBaseUrl, targetId }) => {
    const response = await fetch(`${apiBaseUrl}/v1/projects/${targetId}?confirmation_project_id=${encodeURIComponent(targetId)}`, { method: 'DELETE', credentials: 'include' });
    return response.status;
  }, { apiBaseUrl: API_BASE_URL, targetId: projectId });
  expect(status, 'disposable hosted Project cleanup').toBeGreaterThanOrEqual(200);
  expect(status, 'disposable hosted Project cleanup').toBeLessThan(300);
}

async function sendWithProjectMention(
  page: Page,
  projectId: string,
  projectName: string,
  prompt: string,
  accessMode: 'read' | 'read_write',
): Promise<void> {
  const editor = page.getByTestId('message-editor');
  await page.bringToFront();
  await focusMessageEditor(editor);
  // A space ends mention search, so use the fixture's unique suffix to find
  // multiword Project names through the same keystrokes a user emits.
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
  // Project file execution is intentionally limited to a foreground origin
  // client. Headless Chromium does not always foreground its only page at
  // launch, so make that real protocol condition explicit before sending.
  await page.bringToFront();
  await expect.poll(() => page.evaluate(() => document.hasFocus()), { timeout: 5_000 }).toBe(true);
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await focusMessageEditor(editor);
  await page.keyboard.press('End');
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

async function logChatVersion(page: Page, phase: string): Promise<void> {
  const chatId = await currentChatId(page);
  const version = await page.evaluate((id) => new Promise<number | null>((resolveVersion, rejectVersion) => {
    const open = indexedDB.open('chats_db');
    open.onerror = () => rejectVersion(open.error);
    open.onsuccess = () => {
      const db = open.result;
      const transaction = db.transaction('chats', 'readonly');
      const request = transaction.objectStore('chats').get(id);
      request.onsuccess = () => resolveVersion(request.result?.messages_v ?? null);
      request.onerror = () => rejectVersion(request.error);
      transaction.oncomplete = () => db.close();
    };
  }), chatId);
  console.log('Hosted chat version:', phase, version);
}

async function deactivateProjectFocusAndVerify(page: Page, projectId: string): Promise<void> {
  const chatId = await currentChatId(page);
  const deactivated = page.waitForResponse(
    (response: Response) => response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/v1/projects/focus/deactivate'
      && response.ok(),
    { timeout: 30_000 },
  );
  // Toggle's checkbox is intentionally zero-sized; users click its visible label.
  await page.getByTestId('focus-pill-toggle').click();
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

  // contract-test: direct surface=gui.web assertions=projects.files.hosted-ciphertext-commit,projects.files.expected-base,projects.files.exact-patch,projects.files.chat-focus-required,projects.files.write-policy-enforcement,projects.focus.mention-activation,projects.focus.inferred-consent,projects.focus.mention-history
  test('creates and updates an encrypted hosted file through explicit Project focus and approval', async ({ page }: { page: Page }) => {
    test.setTimeout(900_000);
    const projectName = `Browser hosted ${randomUUID().slice(0, 8)}`;
    const path = 'proofs/browser-hosted-proof.txt';
    const marker = syntheticMarker('hosted');
    const sentWebSocketMessages: Array<Record<string, unknown>> = [];
    const readOperations = new Set<string>();
    const persistedRecoveryJobs = new Set<string>();
    const advertisedCapabilities = new Set<string>();
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Network.enable');
    cdp.on('Network.webSocketCreated', ({ url }: { url: string }) => {
      const values = new URL(url).searchParams.get('client_capabilities') || '';
      values.split(',').filter(Boolean).forEach((capability) => advertisedCapabilities.add(capability));
    });
    cdp.on('Network.webSocketFrameSent', ({ response }: { response: { payloadData: string } }) => {
      try {
        const message = JSON.parse(response.payloadData) as Record<string, unknown>;
        sentWebSocketMessages.push(message);
        if (message.type === 'project_file_operation_result') {
          const payload = message.payload as { status?: string; result?: { code?: string; reason?: string } };
          console.log('Project executor outcome:', payload.status, payload.result?.code ?? payload.result?.reason ?? '');
        }
      } catch {
        // Binary/control frames and non-JSON traffic are irrelevant here.
      }
    });
    cdp.on('Network.webSocketFrameReceived', ({ response }: { response: { payloadData: string } }) => {
      try {
        const message = JSON.parse(response.payloadData) as { type?: string; payload?: { status?: string; state?: string; job_id?: string; code?: string; operation?: string; operation_id?: string; arguments?: { path?: string } } };
        if (message.type === 'recovery_job_persisted' && message.payload?.state === 'TERMINAL' && message.payload.job_id) {
          persistedRecoveryJobs.add(message.payload.job_id);
        }
        if (message.type === 'project_file_operation_request' && message.payload?.operation === 'read_text'
          && message.payload.arguments?.path === path && message.payload.operation_id) {
          readOperations.add(message.payload.operation_id);
        }
        if (message.type === 'commit_embed_revision_result') {
          console.log('Hosted commit outcome:', message.payload?.status, message.payload?.code ?? '');
        }
      } catch {
        // Keep diagnostics to public outcome codes; never log ciphertext or keys.
      }
    });
    let projectId: string | null = null;
    let chatUrl: string | null = null;
    try {
      projectId = await createProject(page, projectName, 'always_ask');
      console.log('Disposable hosted Project:', projectId, projectName);
      // First-party ciphertext routes must be readable with browser cookies;
      // wildcard CORS would fail here before spending any inference budget.
      const missingEmbedId = randomUUID();
      const transportStatuses = await page.evaluate(async ({ apiBaseUrl, targetProjectId, embedId }) => {
        const scope = `project_id=${encodeURIComponent(targetProjectId)}`;
        const paths = [
          `/v1/embeds/${embedId}/encrypted?${scope}`,
          `/v1/embeds/${embedId}/revision-receipts/transport-proof?${scope}&chat_id=transport-proof&proposal_digest=${'a'.repeat(64)}`,
        ];
        return Promise.all(paths.map(async (endpoint) =>
          (await fetch(`${apiBaseUrl}${endpoint}`, { credentials: 'include' })).status));
      }, { apiBaseUrl: API_BASE_URL, targetProjectId: projectId, embedId: missingEmbedId });
      expect(transportStatuses, 'hosted ciphertext CORS must preserve opaque missing-file responses').toEqual([404, 404]);
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await startNewChat(page);
      await waitForChatReady(page);
      await expect.poll(() => advertisedCapabilities.has('project_file_jobs'), {
        message: 'the real browser Project executor must register before inference', timeout: 30_000,
      }).toBe(true);
      console.log('Hosted Project proof: browser advertised its installed Project executor.');

      await sendWithProjectMention(
        page,
        projectId,
        projectName,
        `Use the active Project file tools now. Create exactly one file named ${path} with exactly these two lines and a final newline:\n${marker}\noriginal\nThen read the file back. Do not use code.run or give me instructions to perform the edit.`,
        'read_write',
      );
      chatUrl = page.url();
      await expectProjectFocusPill(page, projectName);
      console.log('Hosted Project proof: explicit mention activated the named focus.');
      await approvePendingWrite(page, path, marker);
      // The initial response can finish before its asynchronous read-back.
      // Verify that requested operation before revoking focus for the next turn.
      await expect.poll(() => sentWebSocketMessages.some((message) => {
        const payload = message.payload as { operation_id?: string; status?: string; result?: { content?: string } };
        return message.type === 'project_file_operation_result' && payload.status === 'completed'
          && readOperations.has(payload.operation_id ?? '') && payload.result?.content === `${marker}\noriginal\n`;
      }), { message: 'the created file must be read back before switching off Project access', timeout: 180_000 }).toBe(true);
      await expect.poll(() => persistedRecoveryJobs.size, {
        message: 'the final asynchronous answer must be durably encrypted before reload', timeout: 180_000,
      }).toBeGreaterThan(0);
      await waitForTurnCompletion(page);
      console.log('Hosted Project proof: first encrypted file revision applied.');
      await logChatVersion(page, 'before reload');

      await page.reload({ waitUntil: 'domcontentloaded' });
      await waitForChatReady(page);
      await expectProjectFocusPill(page, projectName);
      await logChatVersion(page, 'after reload');
      console.log('Hosted Project proof: named focus survived reload.');
      const historyMention = page.getByTestId('project-mention-link').filter({ hasText: `@${projectName.replace(/\s+/g, '-')}` }).first();
      await expect(historyMention).toBeVisible({ timeout: 30_000 });
      await expect(historyMention).toHaveAttribute('href', `#project-id=${projectId}`);

      // Natural-language routing must request consent after focus is switched off.
      await deactivateProjectFocusAndVerify(page, projectId);
      await logChatVersion(page, 'after focus off');
      console.log('Hosted Project proof: focus off revoked server Project authority.');
      await page.bringToFront();
      await page.evaluate(() => window.dispatchEvent(new Event('focus')));
      const completedJobsBeforeFollowup = persistedRecoveryJobs.size;

      await sendMessage(
        page,
        `In my existing Project named "${projectName}", read ${path}, then use an exact Project update patch to change only the second line from original to updated. Preserve the first line and final newline. Request access to this Project through its focus mode so I can confirm it, then perform the edit and read it back.`,
      );
      const followupPreflight = sentWebSocketMessages.filter((message) => message.type === 'chat_turn_preflight').at(-1);
      const routing = (followupPreflight?.payload as { inference_request?: { project_focus_candidates?: Array<{ project_id: string }> } })?.inference_request;
      expect(routing?.project_focus_candidates?.some((candidate) => candidate.project_id === projectId),
        'natural-language routing must carry the existing Project without granting access').toBe(true);
      await expect(page.getByTestId('project-focus-consent')).toBeVisible({ timeout: 240_000 });
      await expect(page.getByTestId('focus-pill')).toHaveCount(0);
      const beforeConsent = await page.evaluate(async ({ apiBaseUrl, chatId }) => {
        const response = await fetch(`${apiBaseUrl}/v1/projects/focus/current?chat_id=${encodeURIComponent(chatId)}`, { credentials: 'include' });
        return (await response.json()).focus;
      }, { apiBaseUrl: API_BASE_URL, chatId: await currentChatId(page) });
      expect(beforeConsent).toBeNull();
      console.log('Hosted Project proof: natural-language request waits without Project authority.');
      await page.getByTestId('project-focus-grant').click();
      await expectProjectFocusPill(page, projectName);
      await approvePendingWrite(page, path, 'updated');
      await expect.poll(() => sentWebSocketMessages.some((message) => {
        const payload = message.payload as { operation_id?: string; status?: string; result?: { content?: string } };
        return message.type === 'project_file_operation_result' && payload.status === 'completed'
          && readOperations.has(payload.operation_id ?? '') && payload.result?.content === `${marker}\nupdated\n`;
      }), { message: 'the updated file must be read back before revoking Project access', timeout: 180_000 }).toBe(true);
      await expect.poll(() => persistedRecoveryJobs.size, {
        message: 'the second asynchronous answer must also be durably encrypted', timeout: 180_000,
      }).toBeGreaterThan(completedJobsBeforeFollowup);
      await waitForTurnCompletion(page);
      console.log('Hosted Project proof: consent resumed the chat and applied the exact update.');
      await deactivateProjectFocusAndVerify(page, projectId);

      // Opening the Project through the historical mention must leave focus off.
      await historyMention.click();
      await expect(page).toHaveURL(new RegExp(`project-id=${projectId}`));
      await page.getByRole('tab', { name: 'Files', exact: true }).click();
      const folder = page.getByTestId('project-virtual-folder-card').filter({ hasText: 'proofs' }).first();
      await expect(folder).toBeVisible({ timeout: 30_000 });
      await folder.click();
      const item = page.getByTestId('project-item-card').filter({ hasText: 'browser-hosted-proof.txt' }).first();
      await expect(item).toBeVisible({ timeout: 30_000 });
      const hostedPreview = item.locator('.unified-embed-preview');
      await expect(hostedPreview).toHaveAttribute('aria-disabled', 'false', { timeout: 30_000 });
      await hostedPreview.click();
      const overlay = page.getByTestId('embed-fullscreen-overlay').last();
      await expect(overlay).toBeVisible({ timeout: 30_000 });
      expect(await readFullscreenCodeLines(overlay)).toEqual([marker, 'updated', '']);
      await expect(overlay.getByTestId('embed-version-timeline')).toBeVisible({ timeout: 30_000 });
      await expect(overlay.getByTestId('version-dot-2')).toBeVisible();
      await closeFullscreen(page, overlay);
      console.log('Hosted Project proof: historical mention opened the Project and both revisions.');

      await page.goto(chatUrl!, { waitUntil: 'domcontentloaded' });
      await waitForChatReady(page);
      await expect(page.getByTestId('focus-pill')).toHaveCount(0);
      await deleteActiveChat(page);
      chatUrl = null;

      const encryptedCommits = sentWebSocketMessages.filter((message) => message.type === 'commit_embed_revision');
      expect(encryptedCommits).toHaveLength(2);
      expect(JSON.stringify(encryptedCommits)).not.toContain(marker);
      for (const message of encryptedCommits) {
        const payload = message.payload as { head?: { encrypted_content?: unknown } };
        expect(typeof payload.head?.encrypted_content).toBe('string');
      }
    } catch (error) {
      console.error('Hosted Project proof failed:', error instanceof Error ? error.message : String(error));
      const diagnostics = await page.evaluate(() => {
        const state = window as unknown as { __openmatesLastPreflightDebug?: { step?: string }; __openmatesLastSendDebug?: { step?: string } };
        return { preflightStep: state.__openmatesLastPreflightDebug?.step, sendStep: state.__openmatesLastSendDebug?.step };
      }).catch(() => ({}));
      console.error('Hosted transport steps:', diagnostics);
      console.error('Recent WebSocket event types:', sentWebSocketMessages.slice(-12).map((message) => message.type));
      console.error('Preflight versions:', sentWebSocketMessages.filter((message) => message.type === 'chat_turn_preflight')
        .map((message) => {
          const payload = message.payload as { expected_messages_v?: number; encrypted_chat_metadata?: unknown };
          return { expected: payload.expected_messages_v, createsChat: Boolean(payload.encrypted_chat_metadata) };
        }));
      if (!chatUrl && page.url().includes('chat-id=')) chatUrl = page.url();
      await page.screenshot({ path: test.info().outputPath('hosted-project-before-cleanup.png'), fullPage: true }).catch(() => undefined);
      throw error;
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
    const fixtureDeviceIdentity = `cli:project-browser-test:${randomUUID()}`;
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
        OPENMATES_CLI_DEVICE_IDENTITY: fixtureDeviceIdentity,
      },
    );
    const marker = syntheticMarker('remote');
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
          OPENMATES_CLI_DEVICE_IDENTITY: fixtureDeviceIdentity,
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
        fixture.project_id as string,
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

      await page.goto(`/#project-id=${encodeURIComponent(fixture.project_id as string)}`, { waitUntil: 'domcontentloaded' });
      await page.getByRole('tab', { name: 'Files', exact: true }).click();
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);
      // A Project with one connected source opens that root directly in Files.
      const sourceBrowser = page.getByTestId('project-remote-browser');
      await expect(sourceBrowser).toBeVisible({ timeout: 30_000 });
      const sourceFolder = sourceBrowser.locator('[data-testid="project-remote-entry"][data-kind="directory"]')
        .filter({ hasText: /\bsrc\b/ });
      await expect(sourceFolder.getByTestId('project-remote-cloud-badge')).toBeVisible();
      await sourceFolder.locator('.unified-embed-preview').click();
      const preview = sourceBrowser.getByTestId('project-remote-preview-card').filter({ hasText: 'remote-demo.ts' });
      await expect(preview).toBeVisible({ timeout: 30_000 });
      await preview.locator('.unified-embed-preview').click();
      const overlay = page.getByTestId('project-remote-fullscreen-overlay');
      await expect(overlay).toBeVisible({ timeout: 30_000 });
      expect(await readFullscreenCodeLines(overlay)).toEqual([
        `export const remoteDemo = "${marker}";`,
        'export const imported = true;',
        '',
      ]);
      await closeFullscreen(page, overlay);
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);
    } finally {
      if (chatUrl) {
        await page.goto(chatUrl, { waitUntil: 'domcontentloaded' }).catch(() => undefined);
        await deleteActiveChat(page);
      }
      if (bridge.exitCode === null) {
        const bridgeExit = new Promise<void>((resolvePromise) => {
          const timeout = setTimeout(resolvePromise, 5000);
          bridge.once('exit', () => {
            clearTimeout(timeout);
            resolvePromise();
          });
        });
        bridge.kill('SIGTERM');
        await bridgeExit;
        if (bridge.exitCode === null) bridge.kill('SIGKILL');
      }
      rmSync(fixtureStateDir, { recursive: true, force: true });
    }
  });
});
