/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { fillMessageEditor, loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

// contract-test: direct surface=gui.web assertions=drafts.draft-only.presentation,drafts.persistence.local-first-encrypted
test('saved embed references show type labels in resume, sidebar, and header previews', async ({ page }: { page: any }) => {
  test.setTimeout(90_000);
  skipWithoutCredentials(test, email, password, otpKey);
  await page.setViewportSize({ width: 1280, height: 900 });
  await loginToTestAccount(page, () => undefined, async () => undefined, { waitForEditor: true });
  await startNewChat(page);
  await fillMessageEditor(page, page.getByTestId('message-editor'), 'Draft with an image reference');
  await expect(page.getByTestId('draft-chat-badge')).toBeVisible({ timeout: 15_000 });

  const draftChatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
  expect(draftChatId).toBeTruthy();
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
  await expect(page.getByTestId('chat-header-title')).toContainText('[Image]', { timeout: 20_000 });
  await expect(page.getByTestId('chat-header-title')).not.toContainText('embed_id');
});
