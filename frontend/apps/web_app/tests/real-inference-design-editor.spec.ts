import { test, expect } from './helpers/cookie-audit';
import { focusMessageEditor, startNewChat } from './helpers/chat-test-helpers';
import { requireRealInference } from './helpers/real-inference-guard';
import {
  createWorkflowCliHome, loginWorkflowCliViaPair, removeWorkflowCliHome,
  runWorkflowCli, runWorkflowCliJson, workflowApiUrl,
} from './helpers/workflow-cli-e2e-helpers';

const base = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const firstTitle = 'Open Studio Weekend';
const revisedTitle = 'Open Studio Saturday';
test.describe.configure({ retries: 0 });

const cards = '[data-testid="embed-preview"][data-app-id="design"][data-skill-id="document"]';

// contract-test: direct surface=gui.web assertions=design-editor.assistant.route,design-editor.assistant.review,design-editor.assistant.apply
test('creates a reviewed Design, applies a proposal and reads the saved chat from CLI', async ({ page, context }, info) => {
  requireRealInference('Editable Design creation and follow-up', base);
  test.setTimeout(540_000);
  const api = workflowApiUrl();
  const home = createWorkflowCliHome('design-author');
  let chatId: string | undefined;
  try {
    await loginWorkflowCliViaPair(page, api, home, 'DESIGN_AUTHOR');
    await page.getByTestId('icon-button-close').click();
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.setViewportSize({ width: 1280, height: 860 });
    await startNewChat(page);
    const composer = page.getByTestId('message-editor');
    await focusMessageEditor(composer);
    await page.keyboard.insertText('@Gemini-3.8-Flash');
    const models = page.getByTestId('mention-dropdown');
    await expect(models.getByTestId('mention-result-name').filter({ hasText: /Gemini 3\.8 Flash/i }).first()).toBeVisible();
    await page.keyboard.press('Tab');
    await expect(models).toBeHidden();
    await page.keyboard.insertText(' Create an editable Design document, a letter-size flyer in warm cream and navy for a studio and gallery. Include one simple graphic shape, the exact headline "Open Studio Weekend", and the exact line "Saturday at 11:00". Use the Design app.');
    await page.keyboard.press('Escape');
    await page.locator('[data-action="send-message"]').click();
    await expect(page).toHaveURL(/chat-id=[a-f0-9-]{36}/, { timeout: 30_000 });
    chatId = page.url().match(/chat-id=([a-f0-9-]{36})/)?.[1];
    expect(chatId).toBeTruthy();
    await expect(page.getByTestId('message-assistant').first().getByTestId('generated-by')).toContainText(/Gemini 3\.8 Flash/i, { timeout: 190_000 });
    const first = page.getByTestId('message-assistant').locator(cards).first();
    await expect(first.getByTestId('design-embed-thumbnail')).toBeVisible({ timeout: 180_000 });
    await expect(page.getByTestId('message-assistant').first()).toHaveAttribute('data-streaming', 'false', { timeout: 90_000 });
    await first.getByTestId('result-preview-expand').click();
    await expect(page.getByTestId('design-canvas')).toBeVisible();
    await info.attach('generated-design-desktop', { body: await page.screenshot(), contentType: 'image/png' });
    await page.getByTestId('design-mode').click();
    await expect(page.locator('[data-testid^="design-layer-"]').first()).toBeVisible();
    await page.getByTestId('design-mode').click();
    await page.getByTestId('design-copy-for-chat').click();
    await expect(page.getByTestId('design-copy-for-chat')).toContainText('Paste into chat');
    await page.keyboard.press('Escape');

    const editor = page.getByTestId('message-editor').last();
    await focusMessageEditor(editor);
    await page.keyboard.insertText(`Change only the attached Design headline from "${firstTitle}" to "${revisedTitle}". Use the Design app to propose the revision.`);
    await page.keyboard.press('Enter');
    await page.keyboard.press('ControlOrMeta+v');
    await expect(editor.locator(cards)).toBeVisible();
    await page.locator('[data-action="send-message"]').click();

    const proposal = page.getByTestId('message-assistant').locator(cards).nth(1);
    await expect(proposal.getByTestId('design-embed-thumbnail')).toBeVisible({ timeout: 190_000 });
    await page.setViewportSize({ width: 390, height: 844 });
    await proposal.getByTestId('result-preview-expand').click();
    await expect(page.getByTestId('design-proposal-apply')).toBeVisible();
    await info.attach('design-proposal-phone', { body: await page.screenshot(), contentType: 'image/png' });
    await page.getByTestId('design-proposal-apply').click();
    await expect(page.getByTestId('design-proposal-controls')).toContainText('Changes applied.');
    await page.keyboard.press('Escape');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await first.getByTestId('result-preview-expand').click();
    await page.getByTestId('design-mode').click();
    await page.getByTestId('design-show-layers').click();
    const headline = page.locator('[data-testid^="design-layer-"]').filter({ hasText: /headline|title/i }).first();
    await headline.click();
    await page.getByTestId('design-show-properties').click();
    await expect(page.getByTestId('design-property-text')).toHaveValue(revisedTitle);
    await info.attach('applied-design-phone', { body: await page.screenshot(), contentType: 'image/png' });
    const read = await runWorkflowCliJson(api, home, ['chats', 'show', chatId!, '--all', '--raw'], 'read saved Design chat', 60_000);
    expect(JSON.stringify(read)).toContain('design-document');
  } catch (error) {
    await info.attach('before-cleanup', { body: await page.screenshot(), contentType: 'image/png' });
    throw error;
  } finally {
    if (chatId) await runWorkflowCli(api, home, ['chats', 'delete', chatId, '--yes'], 30_000);
    removeWorkflowCliHome(home);
  }
});
