/* eslint-disable @typescript-eslint/no-require-imports */
/** Real-inference regression for an ordinary Project README request without an @ mention. */
export {};

import type { ChildProcessWithoutNullStreams } from 'node:child_process';
import type { Page } from '@playwright/test';

const { spawn, spawnSync } = require('node:child_process');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');
const { chmodSync, mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const { randomUUID } = require('node:crypto');
const { test, expect } = require('./helpers/cookie-audit');
const {
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
const PROMPT = 'can you read the readme from my OpenMates project?';
const README_CONTENT = '# Connected project\n\n![Connected diagram](docs/readme-image.png)\n\n[External docs](https://openmates.org)\n';

interface FixtureEvent {
  event: string;
  project_id?: string;
  project_name?: string;
  source_id?: string;
  path_privacy_verified?: boolean;
}

interface SocketEvent {
  type?: string;
  payload?: {
    task_id?: string;
    operation?: string;
    operation_id?: string;
    embed_id?: string;
    content?: string;
    chat_id?: string;
    tombstone?: boolean;
    arguments?: { path?: string; query?: string; target?: string };
    status?: string;
    is_final_chunk?: boolean;
    awaiting_async_skill_continuation?: boolean;
    awaiting_focus_mode_continuation?: boolean;
    result?: { content?: string; matches?: Array<{ path?: string }>; entries?: Array<{ path?: string }> };
    inference_request?: { project_focus_candidates?: Array<{ project_id?: string }> };
  };
}

interface RetrievalEvent {
  at_utc: string;
  at_epoch_ms: number;
  direction: 'sent' | 'received';
  type: string;
  operation?: string;
  target?: string;
  status?: string;
  final_chunk?: boolean;
  awaiting_async_skill_continuation?: boolean;
  task_id?: string;
  embed_id?: string;
}

// Fixed observed baseline from the retained 2026-10-07 dev run. The browser
// can time the new run, while model token totals require correlated backend logs.
const RETRIEVAL_BASELINE = {
  deployed_revision: '01107756fc8d15afbb59b91567aa9ac2abdc8534',
  focus_to_reference_ms: 41931.68,
  focus_to_final_marker_ms: 59975.189,
  main_input_tokens: 98865,
  main_output_tokens: 3180,
  preprocessing_input_tokens: 67364,
  preprocessing_output_tokens: 10247,
  combined_reported_input_tokens: 166229,
  main_model_iterations: 6,
  continuation_count: 3,
};

function requireDirectDevInference(): void {
  if (process.env.CI || process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1') {
    throw new Error('Project README real-inference coverage runs only on dev, never in CI.');
  }
  if (process.env.OPENMATES_PROJECT_CHAT_REAL_AI !== '1' || process.env.E2E_USE_MOCKS || process.env.E2E_USE_LIVE_MOCKS) {
    throw new Error('Set OPENMATES_PROJECT_CHAT_REAL_AI=1 and disable replay mocks for this real-inference run.');
  }
  if (!new URL(BASE_URL).hostname.includes('.dev.') || !new URL(API_BASE_URL).hostname.includes('.dev.')) {
    throw new Error('Project README real-inference coverage requires dev web and API hosts.');
  }
  if (!TEST_EMAIL || !TEST_PASSWORD || !TEST_OTP_KEY) {
    throw new Error('Project README real-inference coverage requires an isolated OPENMATES_TEST_ACCOUNT_* account.');
  }
}

function runChecked(command: string, args: string[], cwd = REPO_ROOT, env = process.env): void {
  const result = spawnSync(command, args, { cwd, env, encoding: 'utf-8' });
  if (result.status !== 0) throw new Error(`${command} ${args.join(' ')} failed:\n${result.stdout}\n${result.stderr}`);
}

function waitForFixtureEvent(child: ChildProcessWithoutNullStreams, eventName: string, timeoutMs = 90_000): Promise<FixtureEvent> {
  return new Promise((resolvePromise, reject) => {
    let buffered = '';
    let diagnostics = '';
    const cleanup = () => {
      clearTimeout(timeout);
      child.stdout.off('data', onData);
      child.stderr.off('data', onStderr);
      child.off('exit', onExit);
    };
    const onStderr = (chunk: Buffer) => { diagnostics = `${diagnostics}${chunk.toString()}`.slice(-16_000); };
    const onData = (chunk: Buffer) => {
      buffered += chunk.toString();
      const lines = buffered.split('\n');
      buffered = lines.pop() ?? '';
      for (const line of lines) {
        try {
          const event = JSON.parse(line) as FixtureEvent;
          if (event.event !== eventName) continue;
          cleanup();
          resolvePromise(event);
          return;
        } catch { /* CLI status lines are allowed. */ }
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
    child.stdout.on('data', onData);
    child.stderr.on('data', onStderr);
    child.once('exit', onExit);
  });
}

async function currentChatId(page: Page): Promise<string> {
  const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1]
    || await page.locator('[data-action="message-input"]').last().getAttribute('data-current-chat-id');
  expect(chatId).toBeTruthy();
  return chatId as string;
}

async function currentAuthority(page: Page): Promise<{ project_id?: string } | null> {
  const chatId = await currentChatId(page);
  return page.evaluate(async ({ apiBaseUrl, activeChatId }) => {
    const response = await fetch(`${apiBaseUrl}/v1/projects/focus/current?chat_id=${encodeURIComponent(activeChatId)}`, {
      credentials: 'include',
    });
    if (!response.ok) throw new Error(`Project authority query failed: ${response.status}`);
    const body = await response.json() as { focus?: { project_id?: string } | null };
    return body.focus ?? null;
  }, { apiBaseUrl: API_BASE_URL, activeChatId: chatId });
}

async function projectFileState(page: Page, projectId: string, sourceId: string): Promise<{ itemCount: number; sourceStatus: string }> {
  return page.evaluate(async ({ apiBaseUrl, targetProjectId, targetSourceId }) => {
    const root = `${apiBaseUrl}/v1/projects/${encodeURIComponent(targetProjectId)}`;
    const [itemsResponse, sourcesResponse] = await Promise.all([
      fetch(`${root}/items`, { credentials: 'include' }),
      fetch(`${root}/sources`, { credentials: 'include' }),
    ]);
    if (!itemsResponse.ok || !sourcesResponse.ok) {
      throw new Error(`Project state query failed: items ${itemsResponse.status}, sources ${sourcesResponse.status}`);
    }
    const items = await itemsResponse.json() as { items?: unknown[] };
    const sources = await sourcesResponse.json() as { sources?: Array<{ source_id?: string; status?: string }> };
    return {
      itemCount: items.items?.length ?? 0,
      sourceStatus: sources.sources?.find(source => source.source_id === targetSourceId)?.status ?? 'missing',
    };
  }, { apiBaseUrl: API_BASE_URL, targetProjectId: projectId, targetSourceId: sourceId });
}

async function waitForTurnCompletion(page: Page): Promise<void> {
  await waitForAssistantMessage(page, { timeout: 300_000 });
  await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-processing', 'false', { timeout: 300_000 });
}

async function deleteObservedChatAndWaitForAck(page: Page, chatId: string, received: SocketEvent[]): Promise<void> {
  const acknowledged = () => received.some(event => event.type === 'chat_deleted'
    && event.payload?.chat_id === chatId && event.payload.tombstone === true);
  if (acknowledged()) return;
  const sidebar = page.locator('.sidebar');
  await expect(sidebar).toHaveCount(1, { timeout: 10_000 });
  if (await sidebar.evaluate(element => element.classList.contains('closed'))) {
    await page.getByTestId('sidebar-toggle').click({ timeout: 5_000 });
  }
  await expect(sidebar).not.toHaveClass(/closed/, { timeout: 5_000 });
  const row = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`);
  await expect(row).toBeVisible({ timeout: 10_000 });
  await row.click({ button: 'right', timeout: 5_000 });
  const deleteButton = page.getByTestId('chat-context-delete');
  await expect(deleteButton).toBeVisible({ timeout: 5_000 });
  await deleteButton.click({ timeout: 5_000 });
  await deleteButton.click({ timeout: 5_000 });
  await expect.poll(acknowledged, {
    message: 'server must acknowledge deletion of the exact disposable chat', timeout: 30_000,
  }).toBe(true);
  await expect(row).toHaveCount(0, { timeout: 10_000 });
}

test.describe('Plain-language Project README access (real inference, dev only)', () => {
  test.describe.configure({ retries: 0 });
  test.beforeAll(requireDirectDevInference);
  test.beforeEach(async ({ page }: { page: Page }) => {
    // The budget covers login and fixture setup as well as the inference turn.
    test.setTimeout(900_000);
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    page.on('response', (response) => {
      if (new URL(response.url()).pathname === '/v1/auth/login') {
        console.log(`[login] HTTP ${response.status()}`);
      }
    });
    await loginToTestAccount(page, (message: string) => console.log(`[login] ${message}`));
  });

  // contract-test: direct surface=gui.web assertions=projects.focus.inferred-consent,projects.files.chat-focus-required,projects.files.no-server-decryption-authority
  test('ordinary README request waits for consent, reads after activation, and stays blocked after rejection', async ({ page }: { page: Page }) => {
    const stateDir = mkdtempSync(join(tmpdir(), 'openmates-readme-focus-'));
    const deviceIdentity = `cli:readme-focus:${randomUUID()}`;
    chmodSync(stateDir, 0o700);
    runChecked('npm', ['run', 'build'], CLI_DIR);
    runChecked('node', ['scripts/openmates_cli_test_account.mjs', 'login', '--api-url', API_BASE_URL, '--web-origin', new URL(BASE_URL).origin], REPO_ROOT, {
      ...process.env,
      OPENMATES_STATE_DIR: stateDir,
      OPENMATES_TEST_ACCOUNT_EMAIL: TEST_EMAIL,
      OPENMATES_TEST_ACCOUNT_PASSWORD: TEST_PASSWORD,
      OPENMATES_TEST_ACCOUNT_OTP_KEY: TEST_OTP_KEY,
      OPENMATES_TEST_ACCOUNT_SOURCE_SLOT: '',
      OPENMATES_CLI_DEVICE_IDENTITY: deviceIdentity,
    });
    const bridge = spawn('node', [
      '--experimental-strip-types', '--loader', './frontend/packages/openmates-cli/tests/loader.mjs',
      'scripts/project_remote_access_live.mjs', 'serve', API_BASE_URL,
    ], {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        OPENMATES_STATE_DIR: stateDir,
        OPENMATES_CLI_DEVICE_IDENTITY: deviceIdentity,
        OPENMATES_PROJECT_FIXTURE_NAME: 'OpenMates',
        OPENMATES_REMOTE_HOST_SESSION: join(stateDir, 'session.json'),
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    }) as ChildProcessWithoutNullStreams;
    bridge.stderr.resume();
    const sent: SocketEvent[] = [];
    const received: SocketEvent[] = [];
    const retrievalEvents: RetrievalEvent[] = [];
    let acceptedTurnStartedAt: number | null = null;
    let focusActivatedAt: number | null = null;
    let turnCompletedAt: number | null = null;
    let acceptedChatId: string | null = null;
    let projectReferenceEmbedId: string | null = null;
    const recordEvent = (direction: RetrievalEvent['direction'], event: SocketEvent) => {
      if (acceptedTurnStartedAt === null || !event.type || ![
        'chat_turn_preflight', 'project_file_operation_request', 'project_file_operation_result',
        'send_embed_data', 'ai_message_update', 'ai_background_response_completed',
        'ai_typing_ended', 'post_processing_completed',
      ].includes(event.type)) return;
      const at = Date.now();
      retrievalEvents.push({
        at_utc: new Date(at).toISOString(), at_epoch_ms: at, direction, type: event.type,
        ...(event.payload?.operation ? { operation: event.payload.operation } : {}),
        ...(event.payload?.arguments?.target ? { target: event.payload.arguments.target } : {}),
        ...(event.payload?.status ? { status: event.payload.status } : {}),
        ...(event.payload?.is_final_chunk ? { final_chunk: true } : {}),
        ...(event.payload?.awaiting_async_skill_continuation ? { awaiting_async_skill_continuation: true } : {}),
        ...(event.payload?.task_id ? { task_id: event.payload.task_id } : {}),
        ...(event.payload?.embed_id ? { embed_id: event.payload.embed_id } : {}),
      });
    };
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Network.enable');
    cdp.on('Network.webSocketFrameSent', ({ response }: { response: { payloadData: string } }) => {
      try { const event = JSON.parse(response.payloadData) as SocketEvent; sent.push(event); recordEvent('sent', event); }
      catch { /* Ignore control frames. */ }
    });
    cdp.on('Network.webSocketFrameReceived', ({ response }: { response: { payloadData: string } }) => {
      try { const event = JSON.parse(response.payloadData) as SocketEvent; received.push(event); recordEvent('received', event); }
      catch { /* Ignore control frames. */ }
    });
    let chatUrl: string | null = null;
    let fixtureAudit: { project_id?: string; source_id?: string } | null = null;
    let scenarioFailure: unknown = null;
    let chatCleanupFailure: string | null = null;
    let fixtureCleanupFailure: string | null = null;
    try {
      const fixture = await waitForFixtureEvent(bridge, 'fixture_ready');
      fixtureAudit = { project_id: fixture.project_id, source_id: fixture.source_id };
      expect(fixture).toMatchObject({ project_name: 'OpenMates', path_privacy_verified: true });
      expect(fixture.project_id).toBeTruthy();
      console.log('[README] Disposable connected Project ready.');
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await startNewChat(page);
      await waitForChatReady(page);
      await page.bringToFront();
      await expect.poll(() => page.evaluate(() => document.hasFocus()), { timeout: 5_000 }).toBe(true);
      await page.evaluate(() => window.dispatchEvent(new Event('focus')));

      // Reject one ordinary request during the standard countdown. Its chat
      // must never gain authority or issue Project file jobs afterwards.
      try {
        await sendMessage(page, PROMPT);
      } finally {
        chatUrl = page.url();
      }
      const rejectedChatId = await currentChatId(page);
      const preflight = sent.filter(event => event.type === 'chat_turn_preflight').at(-1);
      expect(preflight?.payload?.inference_request?.project_focus_candidates?.some(candidate => candidate.project_id === fixture.project_id)).toBe(true);
      await expect(page.getByTestId('focus-progress-bar')).toBeVisible({ timeout: 240_000 });
      await expect(page.getByTestId('focus-reject-hint')).toBeVisible();
      expect(await currentAuthority(page)).toBeNull();
      expect(received.filter(event => event.type === 'project_file_operation_request')).toHaveLength(0);
      await page.getByTestId('focus-mode-bar').last().click();
      await expect(page.getByTestId('focus-progress-bar')).toHaveCount(0);
      await waitForTurnCompletion(page);
      expect(await currentAuthority(page)).toBeNull();
      expect(received.filter(event => event.type === 'project_file_operation_request')).toHaveLength(0);
      console.log('[README] Rejection kept Project authority and file access blocked.');
      console.log('[README] Deleting rejected chat and awaiting server tombstone.');
      await deleteObservedChatAndWaitForAck(page, rejectedChatId, received);
      console.log('[README] Rejected-chat deletion acknowledged.');
      chatUrl = null;

      // The cleanup helper opens Chats to delete the row. On phone the open
      // sidebar covers the composer-side New Chat button until explicitly closed.
      const openSidebar = page.locator('.sidebar:not(.closed)');
      if (await openSidebar.count()) {
        console.log('[README] Closing Chats sidebar after cleanup.');
        const sidebarClose = openSidebar.getByTestId('activity-history-wrapper')
          .locator('button.icon_close.top-button.right');
        await expect(sidebarClose).toBeVisible({ timeout: 5_000 });
        await sidebarClose.click({ timeout: 5_000 });
      }
      await expect(page.locator('.sidebar')).toHaveClass(/closed/, { timeout: 5_000 });
      console.log('[README] Rejection case complete; loading a fresh page for the independent accepted case.');
      // Keep this Page and its CDP Network listeners, but reset the client chat
      // lifecycle after the rejected chat is deleted before sending again.
      await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
      await waitForChatReady(page);
      const refreshedSidebar = page.locator('.sidebar:not(.closed)');
      if (await refreshedSidebar.count()) {
        const sidebarClose = refreshedSidebar.getByTestId('activity-history-wrapper')
          .locator('button.icon_close.top-button.right');
        await expect(sidebarClose).toBeVisible({ timeout: 5_000 });
        await sidebarClose.click({ timeout: 5_000 });
      }
      await expect(page.locator('.sidebar')).toHaveClass(/closed/, { timeout: 5_000 });
      console.log('[README] Fresh page and chat transport ready; starting accepted chat.');
      page.setDefaultTimeout(10_000);
      try {
        await startNewChat(page);
      } finally {
        page.setDefaultTimeout(0);
      }
      await waitForChatReady(page);
      console.log('[README] Accepted chat editor ready.');
      await page.bringToFront();
      await page.evaluate(() => window.dispatchEvent(new Event('focus')));
      await page.evaluate(() => {
        const progressWindow = window as Window & { projectProgressLabels?: string[] };
        progressWindow.projectProgressLabels = [];
        let previous = '';
        new MutationObserver(() => {
          const indicator = document.querySelector('[data-testid="chat-processing-indicator"]');
          const text = indicator?.getClientRects().length ? indicator.textContent?.trim() ?? '' : '';
          if (text && text !== previous) progressWindow.projectProgressLabels?.push(text);
          previous = text;
        }).observe(document.body, { childList: true, characterData: true, subtree: true });
      });
      acceptedTurnStartedAt = Date.now();
      console.log('[README] Sending accepted README request.');
      try {
        await sendMessage(page, PROMPT);
      } finally {
        chatUrl = page.url();
      }
      console.log('[README] Accepted README request sent.');
      acceptedChatId = await currentChatId(page);
      const secondPreflight = sent.filter(event => event.type === 'chat_turn_preflight').at(-1);
      expect(secondPreflight?.payload?.inference_request?.project_focus_candidates?.some(candidate => candidate.project_id === fixture.project_id)).toBe(true);
      await expect(page.getByTestId('focus-progress-bar')).toBeVisible({ timeout: 240_000 });
      await expect(page.getByTestId('focus-pill')).toHaveCount(0);
      expect(await currentAuthority(page)).toBeNull();
      expect(received.filter(event => event.type === 'project_file_operation_request')).toHaveLength(0);
      await expect(page.getByTestId('focus-pill').getByTestId('focus-pill-label')).toHaveText('Work on OpenMates', { timeout: 60_000 });
      await expect.poll(() => currentAuthority(page), { timeout: 30_000 }).toMatchObject({ project_id: fixture.project_id });
      focusActivatedAt = Date.now();
      console.log('[README] Countdown activated the selected Project.');
      await expect.poll(() => received.some(event => event.type === 'project_file_operation_request'
        && event.payload?.operation === 'read_text' && event.payload.arguments?.path === 'README.md'), {
        message: 'the assistant must read the matched README from the selected Project', timeout: 180_000,
      }).toBe(true);
      const filenameSearches = received.filter(event => event.type === 'project_file_operation_request'
        && event.payload?.operation === 'search');
      expect(filenameSearches.every(event => event.payload?.arguments?.target === 'files')).toBe(true);
      expect(filenameSearches.every(event => /readme/i.test(event.payload?.arguments?.query ?? ''))).toBe(true);
      await expect.poll(() => {
        const read = received.find(event => event.type === 'project_file_operation_request'
          && event.payload?.operation === 'read_text' && event.payload.arguments?.path === 'README.md');
        return sent.find(event => event.type === 'project_file_operation_result'
          && event.payload?.operation_id === read?.payload?.operation_id && event.payload?.status === 'completed')
          ?.payload?.result?.content;
      }, { message: 'the remote README must be read successfully', timeout: 180_000 }).toBe(README_CONTENT);
      expect(await page.evaluate(() => (window as Window & { projectProgressLabels?: string[] }).projectProgressLabels ?? []))
        .toEqual(expect.arrayContaining([expect.stringMatching(/(?:Listing|Searching|Reading) Project (?:files?|text)/)]));
      const toonModule = createRequire(resolve(REPO_ROOT, 'frontend/packages/ui/package.json')).resolve('@toon-format/toon');
      const { decode: decodeToon } = await import(pathToFileURL(toonModule).href);
      const finishedProjectEmbeds = () => received.flatMap(event => {
        if (event.type !== 'send_embed_data' || event.payload?.status !== 'finished'
          || typeof event.payload.content !== 'string') return [];
        const decoded = decodeToon(event.payload.content, { strict: false }) as Record<string, unknown>;
        if (decoded.app_id !== 'projects' || !['search', 'read'].includes(String(decoded.skill_id))) return [];
        const rows = Array.isArray(decoded.results) ? decoded.results as Array<Record<string, unknown>> : [];
        const allowedTopLevel = new Set(['app_id', 'skill_id', 'results', 'result_count', 'status', 'embed_ref', 'query', 'search_target']);
        const allowedReference = new Set(['project_id', 'project_name', 'source_id', 'path', 'embed_id', 'line', 'team_id']);
        return [{
          skill: String(decoded.skill_id),
          embedId: event.payload.embed_id,
          topLevelFields: Object.keys(decoded).sort(),
          referenceFields: [...new Set(rows.flatMap(row => Object.keys(row)))].sort(),
          referenceCount: rows.length,
          compositeParent: Array.isArray(decoded.embed_ids),
          allowedFields: Object.keys(decoded).every(key => allowedTopLevel.has(key))
            && rows.length > 0
            && rows.every(row => Object.keys(row).every(key => allowedReference.has(key))
              && typeof row.path === 'string' && Boolean(row.source_id || row.embed_id)),
          readmeReference: rows.some(row => row.project_id === fixture.project_id
            && row.source_id === fixture.source_id && row.path === 'README.md'),
          properQuery: /readme/i.test(String(decoded.query ?? '')),
          properSearchTarget: decoded.skill_id !== 'search' || decoded.search_target === 'files',
          containsFileBytes: JSON.stringify(decoded).includes('# Connected project')
            || JSON.stringify(decoded).includes('Connected diagram'),
        }];
      });
      await expect.poll(() => finishedProjectEmbeds().some(summary => summary.skill === 'read'), {
        message: 'the completed README read must publish a reference card', timeout: 180_000,
      }).toBe(true);
      const readRequestIndex = received.findIndex(event => event.type === 'project_file_operation_request'
        && event.payload?.operation === 'read_text' && event.payload.arguments?.path === 'README.md');
      expect(readRequestIndex).toBeGreaterThanOrEqual(0);
      await expect.poll(() => received.slice(readRequestIndex + 1).some(event =>
        (event.type === 'ai_message_update' || event.type === 'ai_background_response_completed')
        && event.payload?.chat_id === acceptedChatId
        && event.payload?.is_final_chunk === true
        && !event.payload.awaiting_async_skill_continuation
        && !event.payload.awaiting_focus_mode_continuation), {
        message: 'the assistant must finish after the README read, not pause for another async continuation',
        timeout: 300_000,
      }).toBe(true);
      await waitForTurnCompletion(page);
      turnCompletedAt = Date.now();
      for (const event of received) {
        if (event.type !== 'send_embed_data' || typeof event.payload?.content !== 'string') continue;
        const decoded = decodeToon(event.payload.content, { strict: false });
        // A model's quotation must not become a new code/document embed,
        // regardless of whether the Project reference card is also present.
        expect(JSON.stringify(decoded)).not.toContain('# Connected project');
        expect(JSON.stringify(decoded)).not.toContain('Connected diagram');
      }
      const projectEmbedSummaries = finishedProjectEmbeds();
      expect(projectEmbedSummaries.map(summary => summary.skill)).toContain('read');
      const invalidReferenceSummaries = projectEmbedSummaries.flatMap((summary, index) =>
        summary.allowedFields && summary.readmeReference && summary.properQuery
          && summary.properSearchTarget && !summary.containsFileBytes ? [] : [{
            index, skill: summary.skill, compositeParent: summary.compositeParent,
            referenceCount: summary.referenceCount, topLevelFields: summary.topLevelFields,
            referenceFields: summary.referenceFields, allowedFields: summary.allowedFields,
            readmeReference: summary.readmeReference, properQuery: summary.properQuery,
            properSearchTarget: summary.properSearchTarget, containsFileBytes: summary.containsFileBytes,
          }]);
      expect(invalidReferenceSummaries, 'Project reference shape and privacy checks (field names only)').toEqual([]);
      const referenceEmbedId = projectEmbedSummaries.find(summary => summary.skill === 'read')?.embedId;
      expect(referenceEmbedId).toBeTruthy();
      projectReferenceEmbedId = referenceEmbedId ?? null;
      const referencePreview = page.locator(`[data-embed-id="${referenceEmbedId}"]`).getByTestId('project-reference-preview');
      await expect(referencePreview).toBeVisible({ timeout: 30_000 });
      await expect(referencePreview).toContainText('OpenMates');
      await expect(referencePreview).toContainText(/readme/i);
      console.log('[README] Original README read and reference card visible.');
      const storedReference = await page.evaluate(async (embedId: string) => {
        const open = indexedDB.open('chats_db');
        const db = await new Promise<IDBDatabase>((resolvePromise, reject) => {
          open.onsuccess = () => resolvePromise(open.result);
          open.onerror = () => reject(open.error);
        });
        try {
          const row = await new Promise<Record<string, unknown> | undefined>((resolvePromise, reject) => {
            const request = db.transaction('embeds', 'readonly').objectStore('embeds').get(`embed:${embedId}`);
            request.onsuccess = () => resolvePromise(request.result);
            request.onerror = () => reject(request.error);
          });
          return {
            encrypted: typeof row?.encrypted_content === 'string' && row.encrypted_content.length > 0,
            hasPlainContent: Boolean(row?.content || row?.data),
            containsReadmeBytes: JSON.stringify(row ?? {}).includes('# Connected project'),
          };
        } finally { db.close(); }
      }, referenceEmbedId as string);
      expect(storedReference).toEqual({ encrypted: true, hasPlainContent: false, containsReadmeBytes: false });
      console.log('[README] Saved embed contains encrypted references without file bytes.');
      await expect(page.getByTestId('message-assistant').last()).toContainText(/readme|connected project/i);

      // The saved card is a location reference. Opening it reads the original
      // connected source on demand, without importing another Project item.
      const projectId = fixture.project_id as string;
      const sourceId = fixture.source_id as string;
      const beforeOpen = await projectFileState(page, projectId, sourceId);
      expect(beforeOpen.sourceStatus).toBe('connected');
      const savedEmbedEvents = received.filter(event => event.type === 'send_embed_data').length;
      const referenceCard = referencePreview.locator('xpath=ancestor::*[@data-testid="embed-preview"][1]');
      await referenceCard.click();
      const fullscreen = page.getByTestId('project-reference-fullscreen');
      await expect(fullscreen).toBeVisible({ timeout: 30_000 });
      const readmeRow = fullscreen.getByTestId('project-reference-row').filter({ hasText: 'README.md' }).first();
      await expect(readmeRow).toBeVisible();
      await readmeRow.click();
      const originalReadme = page.getByTestId('code-fullscreen-code').last();
      await expect(originalReadme).toContainText('# Connected project', { timeout: 30_000 });
      await expect(originalReadme).toContainText('docs/readme-image.png');
      await closeFullscreen(page, originalReadme.locator('xpath=ancestor::*[contains(@class,"unified-embed-fullscreen-overlay")][1]'));
      await expect(readmeRow).toBeVisible();
      expect((await projectFileState(page, projectId, sourceId)).itemCount).toBe(beforeOpen.itemCount);
      expect(received.filter(event => event.type === 'send_embed_data')).toHaveLength(savedEmbedEvents);
      await closeFullscreen(page, fullscreen);
      console.log('[README] Reopening the original created no file or embed copy.');

      const stopped = waitForFixtureEvent(bridge, 'bridge_stopped');
      bridge.kill('SIGUSR1');
      await stopped;
      await expect.poll(() => projectFileState(page, projectId, sourceId), { timeout: 30_000 })
        .toMatchObject({ itemCount: beforeOpen.itemCount, sourceStatus: 'offline' });
      await referenceCard.click();
      await expect(fullscreen).toBeVisible({ timeout: 30_000 });
      await fullscreen.getByTestId('project-reference-row').filter({ hasText: 'README.md' }).first().click();
      await expect(page.locator('.child-state[role="alert"]')).toContainText(/source is unavailable/i, { timeout: 30_000 });
      await expect(page.getByTestId('code-fullscreen-code')).toHaveCount(0);
      expect((await projectFileState(page, projectId, sourceId)).itemCount).toBe(beforeOpen.itemCount);
      expect(received.filter(event => event.type === 'send_embed_data')).toHaveLength(savedEmbedEvents);
      console.log('[README] Disconnected source reports unavailable without a cached file copy.');
    } catch (error) {
      scenarioFailure = error;
    } finally {
      if (acceptedTurnStartedAt !== null || fixtureAudit !== null) {
        const first = (type: string, direction: RetrievalEvent['direction'], operation?: string) =>
          retrievalEvents.find(event => event.type === type && event.direction === direction
            && (!operation || event.operation === operation))?.at_epoch_ms ?? null;
        const referenceAt = retrievalEvents.find(event => event.type === 'send_embed_data'
          && event.direction === 'received' && event.embed_id === projectReferenceEmbedId)?.at_epoch_ms ?? null;
        await test.info().attach('readme-retrieval-metrics', {
          body: JSON.stringify({
            schema: 'openmates.readme_retrieval_metrics.v1',
            measurement_basis: 'Baseline milestones came from dev backend logs; after milestones use browser receipt and observed WebSocket frames.',
            baseline: RETRIEVAL_BASELINE,
            after: {
              accepted_turn_started_at_utc: acceptedTurnStartedAt === null ? null : new Date(acceptedTurnStartedAt).toISOString(),
              focus_activated_at_utc: focusActivatedAt === null ? null : new Date(focusActivatedAt).toISOString(),
              filename_search_requested_at_utc: first('project_file_operation_request', 'received', 'search') === null
                ? null : new Date(first('project_file_operation_request', 'received', 'search') as number).toISOString(),
              read_requested_at_utc: first('project_file_operation_request', 'received', 'read_text') === null
                ? null : new Date(first('project_file_operation_request', 'received', 'read_text') as number).toISOString(),
              first_reference_at_utc: referenceAt === null ? null : new Date(referenceAt).toISOString(),
              turn_completed_at_utc: turnCompletedAt === null ? null : new Date(turnCompletedAt).toISOString(),
              focus_to_reference_ms: focusActivatedAt !== null && referenceAt !== null ? referenceAt - focusActivatedAt : null,
              focus_to_completion_ms: focusActivatedAt !== null && turnCompletedAt !== null ? turnCompletedAt - focusActivatedAt : null,
              model_token_totals: null,
              combined_reported_input_tokens: null,
            },
            backend_token_lookup: {
              chat_id: acceptedChatId,
              task_ids: [...new Set(retrievalEvents.map(event => event.task_id).filter(Boolean))],
              note: 'Collect actual model and preprocessing token totals from this dev run’s correlated backend usage logs; they are not sent to the browser.',
            },
            fixture_audit: {
              project_id: fixtureAudit?.project_id ?? null,
              source_id: fixtureAudit?.source_id ?? null,
            },
            visible_progress_labels: await page.evaluate(() =>
              (window as Window & { projectProgressLabels?: string[] }).projectProgressLabels ?? []).catch(() => []),
            wire_timeline: retrievalEvents,
          }, null, 2),
          contentType: 'application/json',
        });
      }
      if (chatUrl) {
        const cleanupChatId = chatUrl.match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? acceptedChatId;
        if (cleanupChatId) {
          try {
            await page.goto(chatUrl, { waitUntil: 'domcontentloaded' });
            await deleteObservedChatAndWaitForAck(page, cleanupChatId, received);
            console.log('[README] Final disposable chat deletion acknowledged.');
          } catch (error) {
            chatCleanupFailure = `disposable chat cleanup did not confirm server tombstone and local row removal: ${String(error)}`;
            console.error(`[README] ${chatCleanupFailure}`);
          }
        }
      }
      await cdp.detach().catch(() => undefined);
      if (chatCleanupFailure) {
        await test.info().attach('readme-chat-cleanup', {
          body: JSON.stringify({ chat_id: acceptedChatId ?? chatUrl?.match(/chat-id=([a-zA-Z0-9-]+)/)?.[1], failure: chatCleanupFailure }),
          contentType: 'application/json',
        });
      }
      if (bridge.exitCode === null && bridge.signalCode === null) {
        const waitForBridgeClose = (timeoutMs: number) => new Promise<{ code: number | null; signal: NodeJS.Signals | null } | null>(resolvePromise => {
          const onClose = (code: number | null, signal: NodeJS.Signals | null) => {
            clearTimeout(timeout);
            resolvePromise({ code, signal });
          };
          const timeout = setTimeout(() => {
            bridge.off('close', onClose);
            resolvePromise(null);
          }, timeoutMs);
          bridge.once('close', onClose);
        });
        const gracefulExit = waitForBridgeClose(45_000);
        bridge.kill('SIGTERM');
        const outcome = await gracefulExit;
        if (outcome === null) {
          bridge.kill('SIGKILL');
          await waitForBridgeClose(5_000);
          fixtureCleanupFailure = 'fixture bridge did not finish cleanup within 45 seconds';
        } else if (outcome.code !== 0) {
          fixtureCleanupFailure = `fixture bridge exited unsuccessfully (${outcome.code ?? outcome.signal ?? 'unknown'})`;
        }
      } else if (bridge.exitCode !== 0) {
        fixtureCleanupFailure = `fixture bridge had already exited unsuccessfully (${bridge.exitCode ?? bridge.signalCode ?? 'unknown'})`;
      }
      if (fixtureCleanupFailure) console.error(`[README] ${fixtureCleanupFailure}`);
      if (fixtureAudit) {
        await test.info().attach('readme-fixture-cleanup', {
          body: JSON.stringify({
            project_id: fixtureAudit.project_id,
            source_id: fixtureAudit.source_id,
            clean_exit: fixtureCleanupFailure === null,
            failure: fixtureCleanupFailure,
          }),
          contentType: 'application/json',
        });
      }
      rmSync(stateDir, { recursive: true, force: true });
    }
    if (scenarioFailure) throw scenarioFailure;
    if (chatCleanupFailure) throw new Error(chatCleanupFailure);
    if (fixtureCleanupFailure) throw new Error(fixtureCleanupFailure);
  });
});
