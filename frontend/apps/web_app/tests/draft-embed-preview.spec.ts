/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { fillMessageEditor, loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

// contract-test: direct surface=gui.web assertions=drafts.draft-only.presentation,drafts.persistence.local-first-encrypted
test('saved embed references show type labels in navigation without a draft-only header', async ({ page }: { page: any }) => {
  test.setTimeout(90_000);
  skipWithoutCredentials(test, email, password, otpKey);
  await page.setViewportSize({ width: 1280, height: 900 });
  await loginToTestAccount(page, () => undefined, async () => undefined, { waitForEditor: true });
  await startNewChat(page);
  await fillMessageEditor(page, page.getByTestId('message-editor'), 'Draft with an image reference');
  await expect.poll(() => page.url()).toContain('chat-id=');
  const draftChatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
  expect(draftChatId).toBeTruthy();
  await page.getByTestId('input-dismiss-button').click();
  await expect(page.getByTestId('draft-chat-badge')).toHaveCount(0);
  await expect(page.getByTestId('message-editor').locator('.ProseMirror')).toBeEmpty();
  await startNewChat(page);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => typeof (window as typeof window & {
    __openmatesE2ESetDraftPreview?: unknown;
  }).__openmatesE2ESetDraftPreview)).toBe('function');

  await page.evaluate(async (chatId: string) => {
    const setDraftPreview = (window as typeof window & {
      __openmatesE2ESetDraftPreview?: (chatId: string, preview: string, markdown?: string) => Promise<void>;
    }).__openmatesE2ESetDraftPreview;
    if (!setDraftPreview) throw new Error('E2E draft preview fixture hook is unavailable');
    const reference = '{"type":"image","embed_id":"legacy-image-ref-12345"}';
    await setDraftPreview(chatId, '```json {"type": "image", "embed_id": "legacy-image-ref-12345"...', `Look at this\n\`\`\`json\n${reference}\n\`\`\``);
  }, draftChatId!);

  const resumeCard = page.locator(`[data-testid="resume-chat-draft-card"][data-chat-id="${draftChatId}"]`);
  await expect(resumeCard).toContainText('[Image]', { timeout: 20_000 });
  await expect(resumeCard).not.toContainText('embed_id');

  const sidebar = page.getByTestId('activity-history-wrapper');
  if (!(await sidebar.isVisible().catch(() => false))) await page.getByTestId('sidebar-toggle').click();
  await expect(sidebar).toBeVisible({ timeout: 10_000 });
  const sidebarRow = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${draftChatId}"]`);
  await expect(sidebarRow).toContainText('[Image]', { timeout: 20_000 });
  await expect(sidebarRow).not.toContainText('embed_id');
  await sidebarRow.click();
  await expect(page.getByTestId('message-editor')).toContainText('Look at this', { timeout: 20_000 });
  await expect(page.getByTestId('chat-header-title')).toHaveCount(0);
  await expect(page.getByTestId('draft-chat-badge')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=drafts.draft-only.lifecycle,drafts.persistence.local-first-encrypted,message-input.drafts.preview-persistence,message-input.send.ownership
test('photo draft keeps its preview after dismissal and reload, then sends once', async ({ page }: { page: any }, testInfo: any) => {
  test.setTimeout(180_000);
  skipWithoutCredentials(test, email, password, otpKey);
  test.skip(!process.env.E2E_USE_MOCKS, 'Uses deterministic inference fixtures.');
  const { resolve } = require('node:path');
  const { withMockMarker } = require('./signup-flow-helpers');
  const { installWebSocketFrameTracker } = require('./helpers/cross-client-draft-sync');
  const { sendMessage, setChatSidebarOpen, waitForChatReady } = require('./helpers/chat-test-helpers');
  const frames = installWebSocketFrameTracker(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await loginToTestAccount(page, undefined, undefined, { waitForEditor: true });
  await startNewChat(page);
  await setChatSidebarOpen(page, false);
  const editor = page.getByTestId('message-editor');
  const uploaded = page.waitForResponse((response: any) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/v1/upload/file');
  await page.getByTestId('message-file-input').setInputFiles(resolve(__dirname, 'fixtures/humans_group.jpg'));
  const uploadResponse = await uploaded;
  expect(uploadResponse.ok(), `Upload returned ${uploadResponse.status()}: ${await uploadResponse.text()}`).toBe(true);
  const upload = await uploadResponse.json();
  expect(upload.embed_id).toBeTruthy();
  const image = editor.getByTestId('embed-preview').getByRole('img', { name: 'humans_group.jpg', exact: true });
  await expect(editor.getByTestId('embed-preview')).toHaveAttribute('data-status', 'finished', { timeout: 60_000 });
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
  const caption = 'Describe this saved photo';
  await editor.locator('.ProseMirror').press('Control+End');
  await page.keyboard.insertText(caption);
  await expect(editor).toContainText(caption);
  await expect.poll(() => frames.find((frame: any) => frame.direction === 'received'
    && frame.type === 'draft_update_receipt')?.chatId, { timeout: 30_000 }).toBeTruthy();
  const chatId = frames.find((frame: any) => frame.direction === 'received'
    && frame.type === 'draft_update_receipt')!.chatId;
  await page.getByTestId('input-dismiss-button').click();
  const resume = page.locator(`[data-testid="resume-chat-draft-card"][data-chat-id="${chatId}"]`);
  await expect(resume).toBeVisible();
  await resume.click();
  await expect(editor).toContainText(caption);
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await waitForChatReady(page);
  await expect(editor).toContainText(caption, { timeout: 30_000 });
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
  const marker = withMockMarker('', 'chat_flow_capital').trim();
  const sendStart = frames.length;
  // An empty insertion preserves the exact restored photo/caption document.
  // The shared helper supplies the fixture marker through the supported send event.
  try {
    await sendMessage(page, '', console.log, undefined, 'restored-photo', {
      preserveExistingContent: true, testMockMarker: marker, waitUntil: 'visible',
    });
    const sent = page.getByTestId('message-user').filter({ hasText: caption });
    await expect(sent).toHaveCount(1);
    const sentImage = sent.getByTestId('embed-preview').getByRole('img', { name: 'humans_group.jpg', exact: true });
    await expect(sentImage).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => sentImage.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
    await expect(page.getByTestId('message-assistant').first()).toBeVisible({ timeout: 60_000 });
    await expect(editor.getByTestId('embed-preview')).toHaveCount(0);
    expect(frames.slice(sendStart).filter((frame: any) => frame.direction === 'received'
      && frame.type === 'error' && frame.chatId === chatId)).toEqual([]);
    expect(frames.slice(sendStart).filter((frame: any) => frame.direction === 'sent'
      && frame.type === 'delete_chat' && frame.chatId === chatId)).toEqual([]);
  } finally {
    await testInfo.attach('photo-draft-send-diagnostics', {
      contentType: 'application/json',
      body: JSON.stringify({ url: page.url(), frames: frames.slice(sendStart),
        lastSend: await page.evaluate(() => (window as typeof window & {
          __openmatesLastSendDebug?: unknown;
        }).__openmatesLastSendDebug ?? null),
      }),
    });
  }
});
