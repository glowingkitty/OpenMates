/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Real encrypted chat and diagram revisions; only provider responses use offline fixtures. */
const { test, expect } = require('./helpers/cookie-audit');
const {
  createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl,
  installE2EServerContentOverrideGate,
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.persistence.client-encrypted,storage.versions.bounded-reconstruction,chats.layout.responsive-history
test('generated HTML diagram keeps its composition and saves text/layout changes with restorable encrypted history', async ({ page }: { page: any }, testInfo: any) => {
  test.setTimeout(300_000);
  skipWithoutCredentials(test, email, password, otpKey);
  const log = createSignupLogger('DIAGRAM_HTML_EDITING');
  const screenshot = createStepScreenshotter(log, { filenamePrefix: 'diagram-design-web' });
  const revisions: Record<string, unknown>[] = [];
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
  try {
    await expect.poll(() => page.evaluate(() => {
      const raw = sessionStorage.getItem('openmates_e2e_log_forwarding');
      if (!raw) return false;
      const state = JSON.parse(raw);
      return Boolean(state.runId && state.token);
    }), { message: 'signed diagram fixture transport gate is installed' }).toBe(true);
    await sendMessage(page,
      'Create a dark high-level architecture diagram of the OpenMates stack. DIAGRAM_HTML_E2E:architecture_dark <<<TEST_LIVE_MOCK:diagram_html_web>>>', log);
    await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
    const chatUrl = page.url();
    const assistant = page.getByTestId('message-assistant').last();
    const preview = assistant.locator('[data-testid="embed-preview"][data-app-id="diagrams"][data-status="finished"]').first();
    await expect(preview).toBeVisible({ timeout: 90_000 });
    await expect(preview.getByTestId('diagram-html-preview')).toBeVisible();
    await expect(assistant).not.toContainText('<!DOCTYPE');
    await preview.scrollIntoViewIfNeeded();
    await screenshot(page, 'chat-scaled-diagram-preview');
    await preview.click();
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

    await overlay.getByTestId('embed-minimize').click();
    await page.reload();
    await expect(page).toHaveURL(chatUrl);
    const reloadedPreview = page.getByTestId('message-assistant').last().locator('[data-testid="embed-preview"][data-app-id="diagrams"][data-status="finished"]').first();
    await expect(reloadedPreview).toBeVisible({ timeout: 45_000 });
    await reloadedPreview.scrollIntoViewIfNeeded();
    await reloadedPreview.click();
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
    await overlay.getByTestId('embed-minimize').click();
    await screenshot(page, 'chat-phone-preview');
    await testInfo.attach('diagram-revision-receipts', { body: JSON.stringify(revisions), contentType: 'application/json' });
    expect([...new Set(revisions.filter(receipt => receipt.status === 'committed').map(receipt => receipt.version))]).toEqual([2, 3]);
  } catch (error) {
    // Preserve the failure state before best-effort chat cleanup changes it.
    await screenshot(page, 'failure-before-cleanup').catch(() => {});
    await testInfo.attach('diagram-failure-state', {
      body: JSON.stringify({
        assistantMessages: await page.getByTestId('message-assistant').count(),
        diagramPreviews: await page.locator('[data-testid="embed-preview"][data-app-id="diagrams"]').evaluateAll((nodes: Element[]) =>
          nodes.map(node => ({ status: node.getAttribute('data-status'), hasHtml: Boolean(node.querySelector('[data-testid="diagram-html-preview"]')) }))),
        revisionReceipts: revisions,
      }),
      contentType: 'application/json',
    }).catch(() => {});
    throw error;
  } finally {
    const overlay = page.getByTestId('embed-fullscreen-overlay');
    if (await overlay.isVisible().catch(() => false)) await overlay.getByTestId('embed-minimize').click();
    if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log, screenshot, 'diagram-cleanup');
  }
});
