/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Real encrypted chat and diagram revisions; only provider responses use offline fixtures. */
const { test, expect } = require('./helpers/cookie-audit');
const {
  createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl,
  installE2EServerContentOverrideGate,
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat, waitForChatReady } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { reloadChatWorkspace } = require('./helpers/workspace-navigation');
const { closeFullscreen } = require('./helpers/embed-test-helpers');

const { email, password, otpKey } = getTestAccount();

// contract-test: supporting surface=gui.web assertions=app-memories.selection.source-scoped,app-memories.transparency.loaded-set,chats.rendering.assistant-document-convergence,chats.persistence.client-encrypted,storage.versions.bounded-reconstruction,chats.layout.responsive-history
test('missed diagram preselection recovers through on-demand memories and keeps editable encrypted history', async ({ page }: { page: any }, testInfo: any) => {
  test.setTimeout(300_000);
  skipWithoutCredentials(test, email, password, otpKey);
  const log = createSignupLogger('DIAGRAM_HTML_EDITING');
  const screenshot = createStepScreenshotter(log, { filenamePrefix: 'diagram-design-web' });
  const revisions: Record<string, unknown>[] = [];
  const historyErrors: string[] = [];
  const observeHistoryErrors = (observedPage: any) => observedPage.on('websocket', (socket: any) => {
    socket.on('framereceived', ({ payload }: { payload: string | Buffer }) => {
      try {
        const frame = JSON.parse(String(payload));
        if (frame.type === 'error' && !frame.payload?.request_id
          && /Immutable embed version mismatch/.test(String(frame.payload?.message))) {
          historyErrors.push(String(frame.payload.message));
        }
      } catch { /* Only structured server errors matter. */ }
    });
  });
  observeHistoryErrors(page);
  page.on('websocket', (socket: any) => {
    socket.on('framereceived', ({ payload }: { payload: string | Buffer }) => {
      try {
        const message = JSON.parse(String(payload));
        if (message.type === 'commit_chat_diagram_revision_result') {
          const receipt = message.payload ?? message.data ?? {};
          revisions.push({ status: receipt.status, version: receipt.current_revision, code: receipt.code });
        }
      } catch { /* Non-JSON frames do not contain revision receipts. */ }
    });
  });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(getE2EDebugUrl('/'));
  await loginToTestAccount(page, log, screenshot);
  await installE2EServerContentOverrideGate(page, 'diagram-html-editing');
  await startNewChat(page, log);
  const otherTab = await page.context().newPage();
  observeHistoryErrors(otherTab);
  await otherTab.goto(page.url());
  await waitForChatReady(otherTab, log);
  try {
    await expect.poll(() => page.evaluate(() => {
      const raw = sessionStorage.getItem('openmates_e2e_log_forwarding');
      if (!raw) return false;
      const state = JSON.parse(raw);
      return Boolean(state.runId && state.token);
    }), { message: 'signed diagram fixture transport gate is installed' }).toBe(true);
    await sendMessage(page,
      'Create a dark editable architecture diagram of the ingestion, query and storage layers. DIAGRAM_HTML_E2E:on_demand <<<TEST_LIVE_MOCK:diagram_html_web>>>', log);
    await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
    const chatUrl = page.url();
    const assistant = page.getByTestId('message-assistant').last();
    const preview = assistant.locator('[data-testid="embed-preview"][data-app-id="diagrams"][data-status="finished"]').first();
    await expect(preview).toBeVisible({ timeout: 90_000 });
    await expect(preview.getByTestId('diagram-html-preview')).toBeVisible();
    expect(historyErrors).toEqual([]);
    await expect(page.getByTestId('notification').filter({ hasText: 'Immutable embed version mismatch' })).toHaveCount(0);
    await expect(otherTab.getByTestId('notification').filter({ hasText: 'Immutable embed version mismatch' })).toHaveCount(0);
    await expect(page.locator('[data-testid="assistant-memory-app-icon"][data-app-id="diagrams"]').first()).toBeVisible();
    await expect(assistant.locator('[data-testid="embed-preview"][data-app-id="system"]')).toHaveCount(0);
    await expect(assistant).not.toContainText('<!DOCTYPE');
    await expect(assistant).not.toContainText('flowchart TD');
    await preview.getByTestId('result-preview-expand').click({ trial: true });
    await screenshot(page, 'chat-scaled-diagram-preview');
    await preview.getByTestId('result-preview-expand').click();
    let overlay = page.getByTestId('embed-fullscreen-overlay');
    await expect(overlay).toBeVisible();
    let frame = overlay.frameLocator('[data-testid="diagram-html-frame"]');
    let label = frame.locator('text[data-om-text="nifi-text-2"]');
    let node = frame.locator('g[data-om-component="nifi"]');
    let edge = frame.locator('g[data-om-edge="nifi-trino"] path[data-om-path]');
    await expect(label).toHaveText('Apache NiFi');
    const pageBackground = await frame.locator('body').evaluate((body: HTMLElement) => getComputedStyle(body).backgroundColor);
    await expect(overlay.getByTestId('diagram-html-canvas')).toHaveCSS('background-color', pageBackground);
    await expect(overlay.getByTestId('diagram-html-fullscreen')).toHaveCSS('background-color', pageBackground);
    const originalTransform = await node.getAttribute('transform');
    const originalEdge = await edge.getAttribute('d');
    await expect(overlay.getByTestId('embed-edit-button')).toBeVisible({ timeout: 20_000 });
    await expect(overlay.getByTestId('embed-edit-icon')).not.toHaveCSS('mask-image', 'none');
    await screenshot(page, 'fullscreen-original');

    await overlay.getByTestId('embed-edit-button').click();
    await expect(overlay.getByTestId('diagram-html-canvas')).toHaveAttribute('data-editor-ready', 'true');
    await label.click();
    const input = frame.getByTestId('diagram-html-text-editor');
    await expect(input).toBeVisible();
    await input.fill('OpenMates Ingestion');
    await input.press('Enter');
    await expect(label).toHaveText('OpenMates Ingestion');
    const nodeBox = await node.boundingBox();
    expect(nodeBox).not.toBeNull();
    await page.mouse.move(nodeBox.x + 15, nodeBox.y + nodeBox.height - 8);
    await page.mouse.down();
    await page.mouse.move(nodeBox.x + 60, nodeBox.y + nodeBox.height + 17, { steps: 8 });
    await page.mouse.up();
    await expect(node).not.toHaveAttribute('transform', originalTransform ?? '');
    await expect(edge).not.toHaveAttribute('d', originalEdge ?? '');
    const editedTransform = await node.getAttribute('transform');
    const editedEdge = await edge.getAttribute('d');
    await screenshot(page, 'fullscreen-editing-text-and-layout');
    await expect(overlay.getByTestId('diagram-html-save')).toBeEnabled();
    await overlay.getByTestId('diagram-html-save').click();
    await expect(overlay.getByTestId('diagram-html-canvas')).toHaveAttribute('data-editing', 'false', { timeout: 45_000 });
    await expect(overlay.getByTestId('diagram-html-save-error')).toHaveCount(0);
    await expect(overlay.getByTestId('version-dot-2')).toBeVisible({ timeout: 20_000 });
    await screenshot(page, 'fullscreen-saved-version-2');

    await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });
    await test.step('Reload saved diagram chat and wait for workspace readiness', async () => {
      await reloadChatWorkspace(page, chatUrl, log);
    });
    const reloadedPreview = page.getByTestId('message-assistant').last().locator('[data-testid="embed-preview"][data-app-id="diagrams"][data-status="finished"]').first();
    await expect(reloadedPreview).toBeVisible({ timeout: 45_000 });
    await reloadedPreview.getByTestId('result-preview-expand').click();
    overlay = page.getByTestId('embed-fullscreen-overlay');
    frame = overlay.frameLocator('[data-testid="diagram-html-frame"]');
    label = frame.locator('text[data-om-text="nifi-text-2"]');
    node = frame.locator('g[data-om-component="nifi"]');
    edge = frame.locator('g[data-om-edge="nifi-trino"] path[data-om-path]');
    await expect(label).toHaveText('OpenMates Ingestion');
    await expect(node).toHaveAttribute('transform', editedTransform);
    await expect(edge).toHaveAttribute('d', editedEdge);

    await overlay.getByTestId('version-dot-1').click();
    await expect(label).toHaveText('Apache NiFi');
    expect(await node.getAttribute('transform')).toBe(originalTransform);
    await expect(edge).toHaveAttribute('d', originalEdge ?? '');
    await expect(overlay.getByTestId('embed-edit-button')).toHaveCount(0);
    await screenshot(page, 'fullscreen-original-version-history');
    await overlay.getByTestId('version-dot-2').click();
    await expect(label).toHaveText('OpenMates Ingestion');
    await expect(overlay.getByTestId('embed-edit-button')).toBeVisible();
    await overlay.getByTestId('embed-edit-button').click();
    await expect(overlay.getByTestId('diagram-html-canvas')).toHaveAttribute('data-editor-ready', 'true');
    await label.click();
    await frame.getByTestId('diagram-html-text-editor').fill('Do not persist');
    await frame.getByTestId('diagram-html-text-editor').press('Enter');
    await overlay.getByTestId('diagram-html-cancel').click();
    await expect(label).toHaveText('OpenMates Ingestion');
    await expect(overlay.getByTestId('version-dot-3')).toHaveCount(0);

    await overlay.getByTestId('version-dot-1').click();
    await expect(label).toHaveText('Apache NiFi');
    await overlay.getByTestId('restore-version-btn').click();
    await expect(overlay.getByTestId('restore-version-btn')).toContainText('Confirm');
    await overlay.getByTestId('restore-version-btn').click();
    await expect(overlay.getByTestId('version-dot-3')).toBeVisible({ timeout: 45_000 });
    await expect(label).toHaveText('Apache NiFi');
    expect(await node.getAttribute('transform')).toBe(originalTransform);
    await expect(edge).toHaveAttribute('d', originalEdge ?? '');
    await expect(overlay.getByTestId('embed-edit-button')).toBeVisible();
    await screenshot(page, 'fullscreen-restored-version-3');

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(overlay.getByTestId('diagram-html-canvas')).toBeVisible();
    await screenshot(page, 'fullscreen-phone');
    await closeFullscreen(page, overlay);
    await screenshot(page, 'chat-phone-preview');
    await testInfo.attach('diagram-revision-receipts', { body: JSON.stringify(revisions), contentType: 'application/json' });
    expect([...new Set(revisions.filter(receipt => receipt.status === 'committed').map(receipt => receipt.version))]).toEqual([2, 3]);
  } catch (error) {
    // Preserve the failure state before best-effort chat cleanup changes it.
    await screenshot(page, 'failure-before-cleanup').catch(() => {});
    await testInfo.attach('diagram-failure-state', {
      body: JSON.stringify({
        pageClosed: page.isClosed(),
        assistantMessages: await page.getByTestId('message-assistant').count().catch(() => null),
        diagramPreviews: await page.locator('[data-testid="embed-preview"][data-app-id="diagrams"]').evaluateAll((nodes: Element[]) =>
          nodes.map(node => ({ status: node.getAttribute('data-status'), hasHtml: Boolean(node.querySelector('[data-testid="diagram-html-preview"]')) }))).catch(() => []),
        revisionReceipts: revisions,
      }),
      contentType: 'application/json',
    }).catch(() => {});
    throw error;
  } finally {
    await otherTab.close();
    const overlay = page.getByTestId('embed-fullscreen-overlay');
    if (await overlay.isVisible().catch(() => false)) await closeFullscreen(page, overlay);
    if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log, screenshot, 'diagram-cleanup');
  }
});

// contract-test: supporting surface=gui.web assertions=app-memories.selection.source-scoped,app-memories.precedence.obligations,app-memories.transparency.loaded-set,chats.rendering.assistant-document-convergence
test('loaded architecture guidance supports prose, native mind maps and explicitly requested Mermaid source', async ({ page }: { page: any }) => {
  test.setTimeout(240_000);
  skipWithoutCredentials(test, email, password, otpKey);
  const log = createSignupLogger('OPTIONAL_DIAGRAM_GUIDANCE');
  const screenshot = createStepScreenshotter(log, { filenamePrefix: 'optional-diagram-guidance' });
  await page.goto(getE2EDebugUrl('/'));
  await loginToTestAccount(page, log, screenshot);
  await installE2EServerContentOverrideGate(page, 'diagram-html-editing');
  for (const kind of ['prose', 'mindmap', 'source']) {
    await startNewChat(page, log);
    try {
      const prompt = kind === 'source'
        ? 'Give me Mermaid source code for a planner-to-worker architecture flow. DIAGRAM_HTML_E2E:explicit_mermaid_source'
        : kind === 'mindmap'
          ? 'Create a native mind map of the planner and implementation worker architecture. DIAGRAM_HTML_E2E:native_mindmap'
          : 'Discuss the architecture of a planner, researcher and implementation worker. Answer in prose only, without a visual. DIAGRAM_HTML_E2E:architecture_prose';
      await sendMessage(page, `${prompt} <<<TEST_LIVE_MOCK:diagram_html_web>>>`, log);
      await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
      const assistant = page.getByTestId('message-assistant').last();
      await expect(page.locator('[data-testid="assistant-memory-app-icon"][data-app-id="diagrams"]').first()).toBeVisible({ timeout: 90_000 });
      if (kind === 'source') {
        const code = assistant.locator('[data-testid="embed-preview"][data-app-id="code"][data-status="finished"]').first();
        await expect(code).toBeVisible({ timeout: 90_000 });
        await code.getByTestId('result-preview-expand').click();
        await expect(page.getByTestId('code-fullscreen-code')).toContainText('flowchart TD');
        await expect(page.getByTestId('code-fullscreen-code')).toContainText('Planner --> Worker');
        await screenshot(page, 'explicit-mermaid-source');
        await closeFullscreen(page, page.getByTestId('embed-fullscreen-overlay'));
      } else if (kind === 'mindmap') {
        const chatUrl = page.url();
        const map = assistant.locator('[data-testid="embed-preview"][data-app-id="mindmaps"][data-status="finished"]').first();
        await expect(map.getByTestId('mindmap-rendered-preview')).toBeVisible({ timeout: 90_000 });
        await map.getByTestId('result-preview-expand').click();
        const overlay = page.getByTestId('embed-fullscreen-overlay');
        await expect(overlay.getByTestId('mindmap-fullscreen-canvas')).toBeVisible();
        await expect(overlay.getByTestId('mindmap-node')).toHaveCount(2);
        await screenshot(page, 'generated-native-mindmap-fullscreen');
        await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });
        await reloadChatWorkspace(page, chatUrl, log);
        await expect(page.getByTestId('message-assistant').last().getByTestId('mindmap-rendered-preview')).toBeVisible();
        await screenshot(page, 'generated-native-mindmap-reloaded');
      } else {
        await expect(assistant).toContainText('The planner defines scope, the researcher reports findings, and the implementation worker owns a bounded task.');
        await expect(assistant.locator('[data-testid="embed-preview"]')).toHaveCount(0);
        await screenshot(page, 'guidance-loaded-prose-only');
      }
      await expect(assistant.locator('[data-testid="embed-preview"][data-app-id="diagrams"]')).toHaveCount(0);
      if (kind !== 'mindmap') await expect(assistant.locator('[data-testid="embed-preview"][data-app-id="mindmaps"]')).toHaveCount(0);
    } finally {
      const overlay = page.getByTestId('embed-fullscreen-overlay');
      if (await overlay.isVisible().catch(() => false)) await closeFullscreen(page, overlay);
      if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log, screenshot, 'optional-guidance-cleanup');
    }
  }
});
