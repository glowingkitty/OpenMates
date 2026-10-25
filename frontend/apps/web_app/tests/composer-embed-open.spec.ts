/* eslint-disable @typescript-eslint/no-require-imports */
import { expect, test } from './helpers/cookie-audit';
import { createSignupLogger, getTestAccount } from './signup-flow-helpers';
import { loginToTestAccount } from './helpers/chat-test-helpers';
import { skipWithoutCredentials } from './helpers/env-guard';
import { getE2EDebugUrl } from './signup-flow-helpers';
import { focusComposer } from './helpers/composer-focus';
import { seedViaPairedCli, type Seed } from './helpers/owned-encrypted-embed-fixture';
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair,
  runWorkflowCli, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');

const credentials = getTestAccount();
const CHAT_ID = 'e2e-composer-embed-destination';
const selectionDiagnostics = new WeakMap<object, string[]>();

test.beforeEach(async ({ page }) => {
  const lines: string[] = [];
  selectionDiagnostics.set(page, lines);
  page.on('console', message => {
    if (message.text().startsWith('[ActiveChat] Composer embed') || message.text().startsWith('[composer-test]')) lines.push(message.text());
  });
  await page.addInitScript(() => document.addEventListener('click', event => {
    const card = event.target instanceof Element ? event.target.closest('[data-testid="recent-embed-search-result"], [data-testid="saved-embed-search-result"]') : null;
    if (card) console.debug('[composer-test] clicked', card.getAttribute('data-testid'));
  }, true));
});

test.afterEach(async ({ page }, testInfo) => {
  await testInfo.attach('composer-selection-diagnostics', { body: JSON.stringify(selectionDiagnostics.get(page) ?? [], null, 2), contentType: 'application/json' });
});

// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
test('opens a public web result from the new-chat composer while keeping the draft', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
  const skipInterests = page.getByTestId('guest-interest-skip');
  if (await skipInterests.isVisible({ timeout: 5000 }).catch(() => false)) await skipInterests.click();

  const query = 'Rocket-powered aircraft - Wikipedia';
  const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
  await expect(editor).toBeVisible({ timeout: 20_000 });
  await focusComposer(page);
  await editor.fill(query);
  const eventCard = page.getByTestId('recent-embed-search-result').filter({ hasText: query }).first();
  await expect(eventCard).toBeVisible({ timeout: 30_000 });
  await expect(eventCard.locator('..').locator('.card-date')).toHaveCount(0);
  await eventCard.click();

  const fullscreen = page.getByTestId('embed-fullscreen-container');
  await expect(fullscreen).toBeVisible({ timeout: 20_000 });
  await expect(fullscreen).toContainText(query);
  await expect(editor).toHaveText(query);
  await expect(page).toHaveURL(/embed-id=/);
  await fullscreen.getByTestId('embed-minimize').click();
  await expect(fullscreen).toHaveCount(0);
  await expect(editor).toHaveText(query);
});

// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual,chats.persistence.client-encrypted,chats.sync.key-gated-recovery
test('recovers the original encrypted saved event without a source chat while composing in a public example', async ({ page }, testInfo) => {
  test.slow();
  test.setTimeout(300_000);
  test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.CI_TEST_MODE !== 'e2e',
    'Requires disposable isolated paired browser and CLI backend');
  skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
  const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('composer-saved-original-event');
  const composerChatId = 'example-gigantic-airplanes';
  const summaryTitle = 'Freelance Barcamp Berlin saved summary';
  const summaryNotes = 'Saved summary notes must never replace original event details';
  let source: Seed | undefined;
  let observeRecovery = false;
  const reads: { path: string; status: number; encrypted: boolean }[] = [];
  page.on('response', async response => {
    const path = new URL(response.url()).pathname;
    if (!observeRecovery || !/^\/v1\/embeds\/chats\/[^/]+\/(?:embeds\/|window)/.test(path)) return;
    const body = await response.json().catch(() => null);
    reads.push({ path, status: response.status(), encrypted: typeof body?.embed?.encrypted_content === 'string'
      || body?.embeds?.some((row: { encrypted_content?: string }) => typeof row.encrypted_content === 'string') === true });
  });
  try {
    await page.setViewportSize({ width: 1366, height: 900 });
    await loginWorkflowCliViaPair(page, apiUrl, home, 'COMPOSER_SAVED_ORIGINAL_EVENT');
    await page.getByTestId('icon-button-close').click();
    source = seedViaPairedCli(apiUrl, home, 'event', 0, true);
    await page.goto(`${process.env.PLAYWRIGHT_TEST_BASE_URL}/#chat-id=${source.chatId}`, { waitUntil: 'domcontentloaded' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('link', { name: 'Freelance Barcamp Berlin', exact: true })).toBeVisible({ timeout: 60_000 });
    await page.evaluate(async ({ chatId, embedIds, childId, title, notes }) => {
      const hooks = window as Window & {
        __openmatesE2EPrepareEmbedCache?: (input: { chatId: string; embedIds: string[] }) => Promise<unknown>;
        __openmatesE2ESeedSavedEmbedMemory?: (input: { embedId: string; title: string; notes: string;
          location: string; url: string; date_start: string }) => Promise<unknown>;
      };
      if (!hooks.__openmatesE2EPrepareEmbedCache || !hooks.__openmatesE2ESeedSavedEmbedMemory) throw new Error('Owned saved-event fixture hooks unavailable');
      await hooks.__openmatesE2EPrepareEmbedCache({ chatId, embedIds });
      // A real legacy saved entry contains the child UUID but deliberately no source chat ID.
      // Its summary fields differ from the original encrypted event to detect substitution.
      await hooks.__openmatesE2ESeedSavedEmbedMemory({ embedId: childId, title, notes,
        location: 'Saved summary venue must not appear', url: 'https://example.com/saved-summary-only',
        date_start: '2030-01-01T12:00:00Z' });
    }, { chatId: source.chatId, embedIds: [source.embedId, source.childId], childId: source.childId,
      title: summaryTitle, notes: summaryNotes });
    await page.goto(getE2EDebugUrl(`/#chat-id=${composerChatId}`), { waitUntil: 'domcontentloaded' });
    const activeChat = page.getByTestId('active-chat-container');
    await expect(activeChat).toHaveAttribute('data-current-chat-id', composerChatId, { timeout: 30_000 });
    const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
    await focusComposer(page);
    await editor.fill(summaryTitle);
    const saved = page.locator(`[data-testid="saved-embed-search-result"][data-embed-id="${source.childId}"]`);
    await expect(saved).toBeVisible({ timeout: 30_000 });
    await page.evaluate(async ids => {
      const evict = (window as Window & { __openmatesE2EEvictEmbedCache?: (ids: string[]) => Promise<void> }).__openmatesE2EEvictEmbedCache;
      if (!evict) throw new Error('E2E local embed eviction hook unavailable');
      await evict(ids);
    }, [source.embedId, source.childId]);
    expect(await page.evaluate(async ids => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open('chats_db');
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      try {
        return await Promise.all(ids.map(id => new Promise<boolean>((resolve, reject) => {
          const request = db.transaction('embeds').objectStore('embeds').get(`embed:${id}`);
          request.onsuccess = () => resolve(!request.result); request.onerror = () => reject(request.error);
        })));
      } finally { db.close(); }
    }, [source.embedId, source.childId])).toEqual([true, true]);
    observeRecovery = true;
    await saved.click();
    const fullscreen = page.getByTestId('embed-fullscreen-container');
    await expect(fullscreen).toBeVisible({ timeout: 60_000 });
    await expect(fullscreen.getByTestId('event-description')).toHaveText('Recovered encrypted event details', { timeout: 60_000 });
    await expect(fullscreen).toContainText('Freelance Barcamp Berlin');
    await expect(fullscreen.getByTestId('event-venue-card')).toContainText('Original encrypted event venue');
    await expect(fullscreen).not.toContainText(summaryTitle);
    await expect(fullscreen).not.toContainText(summaryNotes);
    await expect(fullscreen).not.toContainText('Saved summary venue must not appear');
    await expect.poll(() => reads.some(row => row.path.startsWith(`/v1/embeds/chats/${source!.chatId}/`)
      && row.status === 200 && row.encrypted), { timeout: 30_000 }).toBe(true);
    expect(reads.filter(row => row.path.startsWith(`/v1/embeds/chats/${composerChatId}/`))).toEqual([]);
    await expect(page.locator('[data-testid="settings-menu"].visible')).toHaveCount(0);
    await expect(activeChat).toHaveAttribute('data-current-chat-id', composerChatId);
    await expect(editor).toHaveText(summaryTitle);
    await page.evaluate(() => {
      window.open = url => {
        (window as Window & { __savedEventOpenedUrl?: string }).__savedEventOpenedUrl = String(url);
        return null;
      };
    });
    await fullscreen.getByTestId('external-provider-cta').click();
    expect(await page.evaluate(() => (window as Window & { __savedEventOpenedUrl?: string }).__savedEventOpenedUrl))
      .toBe('https://example.com/events/barcamp');
    await fullscreen.getByTestId('embed-minimize').click();
    await expect(fullscreen).toHaveCount(0);
    await expect(editor).toHaveText(summaryTitle);
    await expect(activeChat).toHaveAttribute('data-current-chat-id', composerChatId);
    await expect(page.locator('[data-testid="settings-menu"].visible')).toHaveCount(0);
  } finally {
    await testInfo.attach('saved-original-encrypted-event-recovery', { body: JSON.stringify(reads, null, 2), contentType: 'application/json' });
    try {
      if (source) {
        const deletion = await runWorkflowCli(apiUrl, home, ['chats', 'delete', source.chatId, '--yes'], 15_000);
        expect(deletion.code, deletion.stderr).toBe(0);
      }
    } finally { removeWorkflowCliHome(home); }
  }
});

// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
test('reports an unavailable saved original without presenting saved notes as event details', async ({ page }) => {
  test.setTimeout(180_000);
  test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.CI_TEST_MODE !== 'e2e',
    'Requires disposable isolated backend for an absent original embed UUID');
  skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
  await loginToTestAccount(page, createSignupLogger('COMPOSER_UNAVAILABLE_SAVED_ORIGINAL'));
  await expect.poll(() => page.evaluate(async () => {
    const state = await (window as Window & {
      __openmatesE2EChatConnectionState?: () => Promise<{ cachePrimed: boolean }>;
    }).__openmatesE2EChatConnectionState?.();
    return state?.cachePrimed === true;
  }), { timeout: 30_000 }).toBe(true);
  const query = 'Unavailable original saved event';
  const notes = 'Saved notes are not original encrypted event content';
  await page.evaluate(async ({ title, notes }) => {
    const seed = (window as Window & {
      __openmatesE2ESeedSavedEmbedMemory?: (input: { embedId: string; title: string; notes: string }) => Promise<unknown>;
    }).__openmatesE2ESeedSavedEmbedMemory;
    if (!seed) throw new Error('E2E saved memory seed helper unavailable');
    await seed({ embedId: '99999999-9999-4999-8999-999999999999', title, notes });
  }, { title: query, notes });
  const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
  await focusComposer(page);
  await editor.fill(query);
  const saved = page.getByTestId('saved-embed-search-result').filter({ hasText: query }).first();
  await expect(saved).toBeVisible({ timeout: 30_000 });
  await saved.click();
  const fullscreen = page.getByTestId('embed-fullscreen-container');
  await expect(fullscreen).toBeVisible({ timeout: 30_000 });
  const errorShell = fullscreen.getByTestId('embed-fullscreen-loading');
  await expect(errorShell).toHaveAttribute('aria-busy', 'false', { timeout: 60_000 });
  await expect(errorShell.getByRole('status')).toContainText('could not be loaded');
  await expect(fullscreen).not.toContainText(notes);
  await expect(page.getByTestId('event-description')).toHaveCount(0);
  await expect(page.locator('[data-testid="settings-menu"].visible')).toHaveCount(0);
  await expect(editor).toHaveText(query);
  await fullscreen.getByTestId('embed-minimize').click();
  await expect(fullscreen).toHaveCount(0);
  await expect(editor).toHaveText(query);
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

  const query = 'Rocket-powered aircraft - Wikipedia';
  const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
  await expect(editor).toBeVisible({ timeout: 20_000 });
  await focusComposer(page);
  await editor.fill(query);
  const eventCard = page.getByTestId('recent-embed-search-result').filter({ hasText: query }).first();
  await expect(eventCard).toBeVisible({ timeout: 30_000 });
  await eventCard.click();

  const fullscreen = page.getByTestId('embed-fullscreen-container');
  await expect(fullscreen).toBeVisible({ timeout: 20_000 });
  await expect(fullscreen).toContainText(query);
  await expect(editor).toHaveText(query);
  await expect(page).toHaveURL(/embed-id=/);
  await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', CHAT_ID);
  await fullscreen.getByTestId('embed-minimize').click();
  await expect(fullscreen).toHaveCount(0);
  await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', CHAT_ID);
  await expect(editor).toHaveText(query);
});

// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual,chats.persistence.client-encrypted,chats.sync.key-gated-recovery
test('recovers an owned event from its source chat while composing in another chat', async ({ page }, testInfo) => {
  test.slow();
  test.setTimeout(300_000);
  test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.CI_TEST_MODE !== 'e2e',
    'Requires disposable isolated paired browser and CLI backend');
  skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
  const apiUrl = workflowApiUrl();
  const home = createWorkflowCliHome('composer-owned-event');
  const destinationId = '11111111-1111-4111-8111-11111111e2e1';
  const query = 'Freelance Barcamp Berlin';
  let source: Seed | undefined;
  let observeRecovery = false;
  const reads: { path: string; status: number; encrypted: boolean }[] = [];
  let delayedRecoveryReads = 0;
  await page.route('**/v1/embeds/chats/*/embeds/*', async route => {
    const path = new URL(route.request().url()).pathname;
    if (!observeRecovery || !source || !path.startsWith(`/v1/embeds/chats/${source.chatId}/embeds/`)) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    const body = await response.body();
    // Preserve real server ciphertext/status; only delivery latency is controlled.
    await new Promise(resolve => setTimeout(resolve, 2_000));
    delayedRecoveryReads++;
    await route.fulfill({ response, body });
  });
  page.on('response', async response => {
    const path = new URL(response.url()).pathname;
    if (!observeRecovery || !/^\/v1\/embeds\/chats\/[^/]+\/(?:embeds\/|window)/.test(path)) return;
    const body = await response.json().catch(() => null);
    reads.push({ path, status: response.status(), encrypted: typeof body?.embed?.encrypted_content === 'string'
      || body?.embeds?.some((row: { encrypted_content?: string }) => typeof row.encrypted_content === 'string') === true });
  });
  try {
    await page.setViewportSize({ width: 1366, height: 900 });
    await loginWorkflowCliViaPair(page, apiUrl, home, 'COMPOSER_OWNED_EVENT');
    await page.getByTestId('icon-button-close').click();
    source = seedViaPairedCli(apiUrl, home, 'event', 0, true);
    await page.goto(`${process.env.PLAYWRIGHT_TEST_BASE_URL}/#chat-id=${source.chatId}`, { waitUntil: 'domcontentloaded' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('link', { name: query, exact: true })).toBeVisible({ timeout: 60_000 });
    // Transcript readiness alone does not populate the cache-only composer search index.
    // Resolve both genuine ciphertext rows first, then discard any earlier empty RAM index.
    await focusComposer(page);
    expect(await page.evaluate(async ({ chatId, embedIds }) => {
      const prepare = (window as Window & {
        __openmatesE2EPrepareEmbedCache?: (input: { chatId: string; embedIds: string[] }) => Promise<{
          decryptedCount: number; encryptedCount: number;
        }>;
      }).__openmatesE2EPrepareEmbedCache;
      if (!prepare) throw new Error('E2E owned embed cache preparation hook is unavailable');
      return prepare({ chatId, embedIds });
    }, { chatId: source.chatId, embedIds: [source.embedId, source.childId] })).toEqual({ decryptedCount: 2, encryptedCount: 2 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('link', { name: query, exact: true })).toBeVisible({ timeout: 60_000 });
    await page.evaluate(async chatId => {
      const seed = (window as Window & {
        __openmatesE2ESeedChat?: (input: { chat: Record<string, unknown>; messages: Record<string, unknown>[] }) => Promise<unknown>;
      }).__openmatesE2ESeedChat;
      if (!seed) throw new Error('E2E chat seed helper is unavailable');
      const now = Math.floor(Date.now() / 1000);
      await seed({ chat: { chat_id: chatId, title: 'Owned event composer destination', messages_v: 1, title_v: 1,
        last_edited_overall_timestamp: now, created_at: now, updated_at: now },
      messages: [{ message_id: '11111111-1111-4111-8111-11111111e2e2', chat_id: chatId,
        role: 'user', created_at: now, status: 'synced', content: 'Keep this destination active.' }] });
    }, destinationId);
    const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
    const card = page.locator(`[data-testid="recent-embed-search-result"][data-embed-id="${source.childId}"]`);
    // Build the real owned search entry before switching chats; the index must outlive local cache eviction.
    await focusComposer(page);
    await editor.fill(query);
    await expect(card).toBeVisible({ timeout: 60_000 });
    await editor.fill('');
    const sidebarToggle = page.getByTestId('sidebar-toggle');
    if (await sidebarToggle.isVisible().catch(() => false)) await sidebarToggle.click();
    await page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${destinationId}"]`).click();
    const activeChat = page.getByTestId('active-chat-container');
    await expect(activeChat).toHaveAttribute('data-current-chat-id', destinationId);
    // Exercise the normal closed-sidebar composer view.
    const closeSidebar = page.getByTestId('activity-history-wrapper').locator('button.icon_close.top-button');
    if (await closeSidebar.isVisible().catch(() => false)) await closeSidebar.click();
    await focusComposer(page);
    await editor.fill(query);
    await expect(card).toBeVisible({ timeout: 30_000 });
    await page.evaluate(async ids => {
      const evict = (window as Window & {
        __openmatesE2EEvictEmbedCache?: (embedIds: string[]) => Promise<void>;
      }).__openmatesE2EEvictEmbedCache;
      if (!evict) throw new Error('E2E local embed eviction hook is unavailable');
      await evict(ids);
    }, [source.embedId, source.childId]);
    // Confirm ciphertext really is absent locally, while the independently built result card remains.
    expect(await page.evaluate(async ids => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open('chats_db');
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      try {
        return await Promise.all(ids.map(id => new Promise<boolean>((resolve, reject) => {
          const request = db.transaction('embeds').objectStore('embeds').get(`embed:${id}`);
          request.onsuccess = () => resolve(!request.result); request.onerror = () => reject(request.error);
        })));
      } finally { db.close(); }
    }, [source.embedId, source.childId])).toEqual([true, true]);
    await expect(card).toBeVisible();
    observeRecovery = true;
    await card.click();
    const fullscreen = page.getByTestId('embed-fullscreen-container');
    await expect(fullscreen).toBeVisible({ timeout: 30_000 });
    await expect(fullscreen.getByTestId('event-description')).toHaveText('Recovered encrypted event details', { timeout: 60_000 });
    await expect.poll(() => reads.some(row => row.path.startsWith(`/v1/embeds/chats/${source!.chatId}/`)
      && row.status === 200 && row.encrypted), { timeout: 30_000 }).toBe(true);
    expect(delayedRecoveryReads).toBeGreaterThan(0);
    expect(reads.filter(row => row.path.startsWith(`/v1/embeds/chats/${destinationId}/`))).toEqual([]);
    await expect(activeChat).toHaveAttribute('data-current-chat-id', destinationId);
    await expect(editor).toHaveText(query);
    await fullscreen.getByTestId('embed-minimize').click();
    await expect(fullscreen).toHaveCount(0);
    await expect(activeChat).toHaveAttribute('data-current-chat-id', destinationId);
    await expect(editor).toHaveText(query);
  } finally {
    await testInfo.attach('composer-owned-event-recovery', { body: JSON.stringify(reads, null, 2), contentType: 'application/json' });
    try {
      if (source) {
        const deletion = await runWorkflowCli(apiUrl, home, ['chats', 'delete', source.chatId, '--yes'], 15_000);
        expect(deletion.code, deletion.stderr).toBe(0);
      }
    } finally { removeWorkflowCliHome(home); }
  }
});
