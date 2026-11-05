/**
 * Real authenticated attachment/chat, embed encryption and output sync persistence.
 * Only Code Run prepare/start/status/stream use synthetic sandbox transport.
 * This is a GUI integration regression, not proof of actual E2B execution.
 */
import { test, expect } from './helpers/cookie-audit';
import type { Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';
/* eslint-disable @typescript-eslint/no-require-imports */
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const SOURCE_PATH = path.join(__dirname, 'fixtures', 'code_run_math.py');
const SOURCE = readFileSync(SOURCE_PATH, 'utf8');
const SUCCESS = 'math-dependencies-ok x**2 + 2*x + 1 [0, 1, 2]';
const INSTALL_FAILURE = 'Dependency installation failed: numpy==2.5.4 requires Python >=3.12; sandbox Python is 3.11. Source execution did not start.';
const dependencies = [
  { package: 'sympy', import_name: 'sympy', latest_version: '1.14.0' },
  { package: 'numpy', import_name: 'numpy', latest_version: '2.5.4', requires_python: '>=3.12' },
  { package: 'matplotlib', import_name: 'matplotlib.pyplot', latest_version: '3.10.8' },
  { package: 'ipython', import_name: 'IPython.display', latest_version: '9.7.0' },
];

async function installSyntheticSandboxTransport(page: Page, incompatiblePin: boolean) {
  const executionId = incompatiblePin ? '00000000-0000-4000-8000-000000000012' : '00000000-0000-4000-8000-000000000011';
  const requests: Record<string, any>[] = [];
  let statusRequests = 0;
  let streamConnections = 0;
  const now = Date.now() / 1000;
  const terminalStatus = {
    execution_id: executionId, status: incompatiblePin ? 'failed' : 'finished',
    target_filename: 'code_run_math.py', files: ['code_run_math.py'],
    exit_code: incompatiblePin ? 1 : 0, duration_seconds: 1,
    artifacts: [], skipped_artifacts: [],
    events: incompatiblePin
      ? [{ kind: 'status', text: 'Installing dependencies...\n', timestamp: now },
        { kind: 'stderr', text: `${INSTALL_FAILURE}\n`, timestamp: now + 1 },
        { kind: 'status', text: 'Exited with code 1\n', timestamp: now + 2 }]
      : [{ kind: 'status', text: 'Installing compatible Python dependencies...\n', timestamp: now },
        { kind: 'stdout', text: `${SUCCESS}\n`, timestamp: now + 1 },
        { kind: 'status', text: 'Exited with code 0\n', timestamp: now + 2 }],
    ...(incompatiblePin ? { error: INSTALL_FAILURE } : {}),
  };
  await page.route(/\/v1\/code\/run\/prepare(?:\?|$)/, route => route.fulfill({ json: {
    dependency_suggestions: dependencies.map(pkg => ({ ...pkg, ecosystem: 'python', source: 'pypi',
      versions: [{ version: pkg.latest_version, released_at: '2026-10-20T00:00:00Z' }],
    })),
  } }));
  await page.route(/\/v1\/code\/run(?:\?|$)/, route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: { execution_id: executionId, status: 'queued', target_filename: 'code_run_math.py', files: ['code_run_math.py'], credits_per_minute: 5 } });
  });
  await page.route(new RegExp(`/v1/code/run/${executionId}(?:\\?|$)`), route => {
    statusRequests += 1;
    return route.fulfill({ json: terminalStatus });
  });
  // Deliberately does not intercept /v1/ws: authentication, chat sync and sidecars are real.
  await page.routeWebSocket(/\/v1\/code\/run\/[^/]+\/stream(?:\?|$)/, socket => {
    streamConnections += 1;
    socket.send(JSON.stringify({ type: 'code_run_snapshot', payload: { ...terminalStatus, status: 'installing_dependencies', events: [] } }));
    socket.send(JSON.stringify({ type: 'code_run_update', payload: { status: terminalStatus.status } }));
  });
  return { requests, counts: () => ({ statusRequests, streamConnections }) };
}

async function openSavedMathAttachment(page: Page, log: (message: string) => void, screenshot: any) {
  const { email, password, otpKey } = getTestAccount();
  skipWithoutCredentials(test, email, password, otpKey);
  await page.goto(getE2EDebugUrl('/'));
  await loginToTestAccount(page, log, screenshot);
  await startNewChat(page, log);
  const editor = page.getByTestId('message-editor');
  await expect(editor.locator('[contenteditable="true"]').first()).toBeVisible({ timeout: 20_000 });
  await editor.locator('[contenteditable="true"]').first().fill(withMockMarker('Please acknowledge this attached Python file.', 'test_hello', 'instant'));
  await page.locator('input[type="file"][multiple]').setInputFiles(SOURCE_PATH);
  await expect(editor.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]')).toBeVisible({ timeout: 30_000 });
  const send = page.locator('[data-action="send-message"]');
  await expect(send).toBeEnabled({ timeout: 15_000 });
  await send.click();
  await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
  await expect(page.getByTestId('message-assistant').last()).toContainText('Hello', { timeout: 30_000 });
  const chatUrl = page.url();
  const embed = page.getByTestId('message-user').last().locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]');
  await expect(embed).toBeVisible({ timeout: 30_000 });
  const overlay = await openFullscreen(page, embed.getByTestId('result-preview-expand'));
  const source = overlay.getByTestId('code-fullscreen-code');
  await expect(source).toContainText('from IPython.display import display');
  const sourceText = await source.innerText();
  await overlay.getByTestId('embed-run-button').click();
  await expect(overlay.getByTestId('code-run-file-selection')).toBeVisible({ timeout: 30_000 });
  return { overlay, embed, chatUrl, sourceText };
}

// contract-test: supporting surface=gui.web assertions=code-run.request.validated,code-run.execution.stream-status-visible,code-run.output.chat-bound-encrypted,message-input.embeds.gated-send
test('automatic Python dependencies use bare packages and synthetic output survives real encrypted sync and reload', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const log = createSignupLogger('CODE_RUN_COMPATIBLE_DEPENDENCIES');
  const screenshot = createStepScreenshotter(log, { filenamePrefix: 'code-run-compatible-dependencies' });
  const synced: any[] = [];
  page.on('websocket', socket => {
    if (!/\/v1\/ws(?:\?|$)/.test(socket.url())) return;
    socket.on('framereceived', frame => {
      try {
        const message = JSON.parse(String(frame.payload));
        if (message.type === 'code_run_output_synced') synced.push(message.payload);
      } catch { /* Non-JSON frames carry no sidecar receipt. */ }
    });
  });
  const transport = await installSyntheticSandboxTransport(page, false);
  const { overlay, embed, chatUrl, sourceText } = await openSavedMathAttachment(page, log, screenshot);
  const selection = overlay.getByTestId('code-run-file-selection');
  for (const dependency of dependencies) {
    await expect(selection.getByRole('combobox', { name: `${dependency.package} · Version`, exact: true })).toHaveValue('automatic');
  }
  await testInfo.attach('automatic-dependency-selection', { body: await selection.screenshot(), contentType: 'image/png' });
  await selection.getByTestId('code-run-continue').click();
  await expect(overlay.getByTestId('code-run-terminal')).toContainText(SUCCESS, { timeout: 30_000 });
  await expect(overlay.getByTestId('code-run-terminal')).toContainText(/Exited.*code 0/);
  expect(transport.requests).toHaveLength(1);
  const request = transport.requests[0];
  expect(request.dependency_installs).toEqual(dependencies.map(pkg => ({ ecosystem: 'python', packages: [pkg.package] })));
  expect(request.client_files.find((file: any) => file.is_target).code).toBe(SOURCE);
  expect(transport.counts()).toEqual({ statusRequests: 1, streamConnections: 1 });
  await expect.poll(() => synced.find(row => row.embed_id === request.target_embed_id), { timeout: 30_000, message: 'real server acknowledges encrypted Code Run output' }).toBeTruthy();
  const receipt = synced.find(row => row.embed_id === request.target_embed_id);
  expect(receipt.chat_id).toBe(request.chat_id);
  expect(typeof receipt.encrypted_payload).toBe('string');
  expect(receipt.encrypted_payload.length).toBeGreaterThan(32);
  expect(receipt.encrypted_payload).not.toContain(SUCCESS);
  expect(receipt.output).toBeUndefined();
  await overlay.getByTestId('code-run-view-code').click();
  expect(await overlay.getByTestId('code-fullscreen-code').innerText()).toBe(sourceText);
  await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });
  await expect(embed).toContainText(SUCCESS, { timeout: 20_000 });
  await page.reload({ waitUntil: 'domcontentloaded' });
  const reloadedEmbed = page.getByTestId('message-user').last().locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]');
  await expect(reloadedEmbed).toContainText(SUCCESS, { timeout: 30_000 });
  const restored = await openFullscreen(page, reloadedEmbed.getByTestId('result-preview-expand'));
  await expect(restored.getByTestId('code-fullscreen-code')).toBeVisible();
  expect(await restored.getByTestId('code-fullscreen-code').innerText()).toBe(sourceText);
  await restored.getByTestId('embed-run-button').click();
  await expect(restored.getByTestId('code-run-terminal')).toContainText(SUCCESS);
  expect(transport.requests).toHaveLength(1);
  await testInfo.attach('synthetic-output-restored-after-reload', { body: await restored.screenshot(), contentType: 'image/png' });
  await closeFullscreen(page, restored, { returnToChatUrl: chatUrl });
  await deleteActiveChat(page, log, screenshot, 'dependency-flow-cleanup');
});

// contract-test: supporting surface=gui.web assertions=code-run.request.validated,code-run.execution.stream-status-visible,message-input.embeds.gated-send
test('explicit incompatible Python pin remains exact and synthetic failure is shown as dependency installation', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const log = createSignupLogger('CODE_RUN_EXPLICIT_DEPENDENCY_PIN');
  const screenshot = createStepScreenshotter(log, { filenamePrefix: 'code-run-explicit-dependency-pin' });
  const transport = await installSyntheticSandboxTransport(page, true);
  const { overlay, chatUrl, sourceText } = await openSavedMathAttachment(page, log, screenshot);
  const selection = overlay.getByTestId('code-run-file-selection');
  await selection.getByRole('combobox', { name: 'numpy · Version', exact: true }).selectOption('2.5.4');
  await testInfo.attach('explicit-incompatible-version-selected', { body: await selection.screenshot(), contentType: 'image/png' });
  await selection.getByTestId('code-run-continue').click();
  const terminal = overlay.getByTestId('code-run-terminal');
  await expect(terminal).toContainText(INSTALL_FAILURE, { timeout: 30_000 });
  await expect(terminal).not.toContainText('Traceback (most recent call last)');
  await expect(terminal).not.toContainText('ModuleNotFoundError');
  await expect(terminal).not.toContainText(SUCCESS);
  expect(transport.requests).toHaveLength(1);
  expect(transport.requests[0].dependency_installs).toEqual(dependencies.map(pkg => ({ ecosystem: 'python', packages: [pkg.package === 'numpy' ? 'numpy==2.5.4' : pkg.package] })));
  expect(transport.requests[0].client_files.find((file: any) => file.is_target).code).toBe(SOURCE);
  expect(transport.counts()).toEqual({ statusRequests: 1, streamConnections: 1 });
  await overlay.getByTestId('code-run-view-code').click();
  expect(await overlay.getByTestId('code-fullscreen-code').innerText()).toBe(sourceText);
  await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });
  await deleteActiveChat(page, log, screenshot, 'explicit-pin-cleanup');
});
