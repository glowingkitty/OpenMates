import { expect, test } from './helpers/cookie-audit';
import { createSignupLogger, getTestAccount } from './signup-flow-helpers';
import { loginToTestAccount } from './helpers/chat-test-helpers';
import { skipWithoutCredentials } from './helpers/env-guard';
import { getE2EDebugUrl } from './signup-flow-helpers';

const credentials = getTestAccount();
const CHAT_ID = 'e2e-composer-embed-destination';

// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
test('opens a public event from the new-chat composer while keeping the draft', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
  const skipInterests = page.getByTestId('guest-interest-skip');
  if (await skipInterests.isVisible({ timeout: 5000 }).catch(() => false)) await skipInterests.click();

  const query = 'Spec-Driven Development in Practice';
  const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
  await expect(editor).toBeVisible({ timeout: 20_000 });
  await editor.click();
  await editor.fill(query);
  const eventCard = page.getByTestId('recent-embed-search-result').filter({ hasText: query }).first();
  await expect(eventCard).toBeVisible({ timeout: 30_000 });
  await eventCard.click();

  const fullscreen = page.getByTestId('embed-fullscreen-container');
  await expect(fullscreen).toBeVisible({ timeout: 20_000 });
  await expect(fullscreen).toContainText(query);
  await expect(editor).toHaveText(query);
  await expect(page).toHaveURL(/embed-id=/);
});

// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
test('opens saved memory details when its embed is unavailable', async ({ page }) => {
  test.setTimeout(180_000);
  skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
  await loginToTestAccount(page, createSignupLogger('COMPOSER_SAVED_EMBED_FALLBACK'));
  await expect.poll(() => page.evaluate(async () => {
    const state = await (window as Window & {
      __openmatesE2EChatConnectionState?: () => Promise<{ cachePrimed: boolean }>;
    }).__openmatesE2EChatConnectionState?.();
    return state?.cachePrimed === true;
  }), { timeout: 30_000 }).toBe(true);
  const { entryId } = await page.evaluate(async () => {
    const seed = (window as Window & {
      __openmatesE2ESeedSavedEmbedMemory?: (input: { embedId: string; title: string }) => Promise<{ entryId: string }>;
    }).__openmatesE2ESeedSavedEmbedMemory;
    if (!seed) throw new Error('E2E saved memory seed helper is unavailable');
    return seed({ embedId: 'e2e-missing-composer-saved-embed', title: 'E2E saved memory fallback' });
  });

  const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
  await expect(editor).toBeVisible({ timeout: 20_000 });
  await editor.fill('E2E saved memory fallback');
  const saved = page.getByTestId('saved-embed-search-result').filter({ hasText: 'E2E saved memory fallback' }).first();
  await expect(saved).toBeVisible({ timeout: 30_000 });
  await saved.click();
  await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible({ timeout: 20_000 });
  await expect(page).toHaveURL(new RegExp(`settings=apps/events/settings_memories/saved_events/entry/${entryId}`));
  await expect(editor).toHaveText('E2E saved memory fallback');
});

// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
test('opens an event from another example chat while keeping the message draft', async ({ page }) => {
  test.setTimeout(180_000);
  skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
  await loginToTestAccount(page, createSignupLogger('COMPOSER_EMBED_OPEN'));
  await expect.poll(() => page.evaluate(async () => {
    const state = await (window as Window & {
      __openmatesE2EChatConnectionState?: () => Promise<{ cachePrimed: boolean }>;
    }).__openmatesE2EChatConnectionState?.();
    return state?.cachePrimed === true;
  }), { timeout: 30_000 }).toBe(true);
  await page.evaluate(async (chatId) => {
    const seed = (window as Window & {
      __openmatesE2ESeedChat?: (input: { chat: Record<string, unknown>; messages: Record<string, unknown>[] }) => Promise<unknown>;
    }).__openmatesE2ESeedChat;
    if (!seed) throw new Error('E2E chat seed helper is unavailable');
    const now = Math.floor(Date.now() / 1000);
    await seed({
      chat: {
        chat_id: chatId, title: 'Composer embed destination', messages_v: 1, title_v: 1,
        last_edited_overall_timestamp: now, created_at: now, updated_at: now,
      },
      messages: [{
        message_id: 'e2e-composer-embed-destination-message', chat_id: chatId,
        role: 'user', created_at: now, status: 'synced', content: 'A destination chat.',
      }],
    });
  }, CHAT_ID);
  const sidebarToggle = page.getByTestId('sidebar-toggle');
  if (await sidebarToggle.isVisible().catch(() => false)) await sidebarToggle.click();
  const destination = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${CHAT_ID}"]`);
  await expect(destination).toBeVisible({ timeout: 20_000 });
  await destination.click();
  await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', CHAT_ID);

  const query = 'Spec-Driven Development in Practice';
  const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
  await expect(editor).toBeVisible({ timeout: 20_000 });
  await editor.fill(query);
  const eventCard = page.getByTestId('recent-embed-search-result').filter({ hasText: query }).first();
  await expect(eventCard).toBeVisible({ timeout: 30_000 });
  await eventCard.click();

  const fullscreen = page.getByTestId('embed-fullscreen-container');
  await expect(fullscreen).toBeVisible({ timeout: 20_000 });
  await expect(fullscreen).toContainText(query);
  await expect(editor).toHaveText(query);
  await expect(page).toHaveURL(/embed-id=/);
});
