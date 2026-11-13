/* eslint-disable @typescript-eslint/no-require-imports */
import type { Browser, BrowserContext, Locator, Page, TestInfo } from '@playwright/test';
import { authoredDocument } from './helpers/authored-result-fixtures';
import { authoredEncryptedSnapshot, blockAuthoredFixtureImageEgress, clearAuthoredChatCache } from './helpers/authored-results-flow-helpers';

const { test, expect } = require('./helpers/cookie-audit');
const { createIsolatedBrowserContext, declareTestState, waitForChatReady } = require('./helpers/chat-test-helpers');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, loginWorkflowCliViaPair, parseCliJson,
  removeWorkflowCliHome, runWorkflowCli } = require('./helpers/workflow-cli-e2e-helpers');

type Item = { embed_id: string; kind: string; title: string; embed_ref: string };
type Carrier = { type: string; title: string; status: string; embed_ids: string[];
  items: Item[]; view: { mode: string; embeds: string[] } };
const recipientState = declareTestState({ auth: 'unauthenticated recipient of an explicitly shared embed',
  browserStorage: 'fresh', account: 'none', chat: 'read-only shared records from this test',
  notifications: 'unchanged', securityReminders: 'unchanged' });
const privateFieldNames = /"(?:aes_key|aes_nonce|authored_media|encrypted_embed_key|source_json)"\s*:/;

function activeEmbedId(page: Page) {
  return new URLSearchParams(new URL(page.url()).hash.slice(1)).get('embed-id');
}
async function expectPrivateFieldsHidden(surface: Locator) {
  expect(await surface.innerText()).not.toMatch(privateFieldNames);
  await expect(surface).not.toContainText('```openmates_embeds');
}
async function expectOrderedGroup(surface: Locator, carrier: Carrier) {
  const cards = surface.getByTestId('embeds-map-view-card');
  await expect(cards).toHaveCount(carrier.items.length, { timeout: 60_000 });
  expect(await cards.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-entry-ref')))).toEqual(carrier.embed_ids);
  for (const item of carrier.items) {
    const card = surface.locator(`[data-testid="embed-preview"][data-embed-id="${item.embed_id}"]`);
    await expect(card).toHaveCount(1);
    const expected = authoredDocument.items.find(record => record.kind === item.kind)!;
    // A user-provided card carries no origin label in its preview; its details view lists the origin.
    const context = card.getByTestId('authored-result-context');
    if (expected.origin === 'user_provided') await expect(context).toHaveCount(0);
    else await expect(context).toHaveAttribute('data-origin', expected.origin);
  }
  await expectPrivateFieldsHidden(surface);
}
async function openSavedChat(page: Page, url: string, chatId: string, carrier: Carrier, navigate = true) {
  if (navigate) await page.goto(url);
  await waitForChatReady(page, undefined, 60_000);
  const active = page.getByTestId('active-chat-container');
  await expect(active).toHaveAttribute('data-current-chat-id', chatId, { timeout: 60_000 });
  const collection = active.getByTestId('authored-results-preview');
  await expect(collection).toHaveAttribute('data-status', 'finished', { timeout: 60_000 });
  await expectOrderedGroup(collection, carrier);
  return collection;
}
async function openChild(page: Page, collection: Locator, item: Item) {
  const card = collection.locator(`[data-testid="embed-preview"][data-embed-id="${item.embed_id}"]`);
  await card.scrollIntoViewIfNeeded();
  await expect(card).toHaveAttribute('role', 'button');
  await card.focus();
  await card.press('Enter');
  const fullscreen = page.getByTestId('embed-fullscreen-overlay').last();
  await expect(fullscreen).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => activeEmbedId(page)).toBe(item.embed_id);
  await expect(fullscreen.getByTestId('embed-header-title')).toHaveText(item.title);
  const origin = authoredDocument.items.find(record => record.kind === item.kind)!.origin;
  await expect(fullscreen.getByTestId('authored-result-context')).toHaveAttribute('data-origin', origin);
  await expectPrivateFieldsHidden(fullscreen);
  return fullscreen;
}
async function closeFullscreen(page: Page, fullscreen: Locator) {
  await fullscreen.getByTestId('embed-minimize').click();
  await expect(fullscreen).not.toBeVisible();
  await expect.poll(() => activeEmbedId(page)).toBeNull();
}
async function createBrowserEmbedShare(page: Page, fullscreen: Locator, embedId: string) {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new URL(page.url()).origin });
  await fullscreen.getByTestId('embed-share-button').click();
  await expect(page.getByTestId('share-embed-preview')).toBeVisible();
  const metadata = page.waitForResponse(response => response.url().includes('/v1/share/embed/metadata')
    && response.request().method() === 'POST' && response.request().postDataJSON()?.embed_id === embedId,
  { timeout: 60_000 });
  await page.getByTestId('share-generate-link').click();
  await expect(page.getByTestId('share-copy-link')).toBeVisible({ timeout: 60_000 });
  expect((await metadata).ok(), 'explicit embed sharing must be persisted').toBe(true);
  await page.getByTestId('share-copy-link').click();
  await expect(page.getByTestId('share-copy-link')).toHaveClass(/copied/);
  const url = await page.evaluate(() => navigator.clipboard.readText());
  const parsed = new URL(url);
  expect(parsed.origin === new URL(page.url()).origin, 'share URL must use the runner web origin').toBe(true);
  expect(parsed.pathname === `/share/embed/${embedId}` || /^\/s\/[A-Za-z0-9]+$/.test(parsed.pathname), 'normal share URL required').toBe(true);
  expect(parsed.hash.length > 1, 'share key remains in the browser URL fragment').toBe(true);
  return url;
}
async function recipient(browser: Browser, info: TestInfo, name: string, baseUrl: string, apiUrl: string,
  verify: (page: Page) => Promise<void>) {
  const context: BrowserContext = await createIsolatedBrowserContext(browser, recipientState, {
    viewport: { width: 390, height: 844 }, recordVideo: { dir: info.outputPath(`${name}-recipient-video`), size: { width: 390, height: 844 } },
  });
  const page = await context.newPage();
  const video = page.video();
  try {
    await blockAuthoredFixtureImageEgress(page, baseUrl, apiUrl);
    await verify(page);
    await expect(page.locator('[data-authenticated="true"]')).toHaveCount(0);
    await info.attach(`${name}-recipient`, { body: await page.screenshot(), contentType: 'image/png' });
  } catch (error) {
    // Keep the failing recipient view: the main test screenshot belongs to
    // the owner and cannot distinguish share decryption from modal failures.
    await info.attach(`${name}-recipient-failure`, { body: await page.screenshot(), contentType: 'image/png' });
    throw error;
  } finally {
    await context.close();
    if (video) await info.attach(`${name}-recipient-video`, { path: await video.path(), contentType: 'video/webm' });
  }
}

// contract-test: direct surface=gui.web assertions=authored-results.creation.relevant-and-independent,authored-results.eligibility.all-suitable-results,authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts,authored-results.groups.same-response-and-reuse,authored-results.lifecycle.encrypted-and-stable,authored-results.actions.truthful-and-explicit,authored-results.surfaces.shared-semantics,tv-titles.lifecycle.groups-and-actions
// CI dependency: ai_committed_fixtures/default, paired CLI build + ordinary core/AI worker.
// No live inference, external provider/image egress, selected encrypted-media or cancellation proof is claimed.
test('saved authored web records survive cold cache recovery and individual/group sharing', async ({ page, browser }: {
  page: Page; browser: Browser;
}, info: TestInfo) => {
  test.setTimeout(900_000);
  const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL;
  expect(baseUrl, 'isolated runner base URL required').toBeTruthy();
  expect(['localhost', '127.0.0.1'], 'this disposable fixture runs only in isolated CI').toContain(new URL(baseUrl!).hostname);
  const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(baseUrl!);
  const home = createWorkflowCliHome('authored-web-flow');
  let chatId: string | undefined;
  try {
    await blockAuthoredFixtureImageEgress(page, baseUrl!, apiUrl);
    await loginWorkflowCliViaPair(page, apiUrl, home, 'AUTHORED_WEB');
    const creation = await runWorkflowCli(apiUrl, home, ['chats', 'new',
      'Create cards from my supplied records, preserving requested drafts. <<<TEST_MOCK:authored_results>>>', '--json'],
    120_000, { OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'authored-results-web-setup' });
    expect(creation.recording, 'paired CLI setup retains a real terminal recording').toBeTruthy();
    if (creation.recording) {
      await info.attach('authored-web-cli-setup', { path: creation.recording.videoPath, contentType: 'video/mp4' });
      await info.attach('authored-web-cli-setup-manifest', { path: creation.recording.manifestPath, contentType: 'application/json' });
    }
    const created = parseCliJson(creation, 'create actual saved authored chat');
    expect(created.error).toBeUndefined();
    expect(created.status).toBe('completed');
    chatId = created.chatId;
    expect(chatId).toMatch(/^[a-f0-9-]{36}$/);
    const refs = [...String(created.assistant).matchAll(/"embed_id"\s*:\s*"([a-f0-9-]+)"/g)];
    expect(refs).toHaveLength(1);
    const carrierId = refs[0][1];
    const stored = parseCliJson(await runWorkflowCli(apiUrl, home,
      ['embeds', 'show', carrierId, '--chat', chatId, '--json'], 60_000), 'read saved authored carrier');
    const carrier = stored.content as Carrier;
    expect(carrier.type).toBe('authored_results');
    expect(carrier.status).toBe('finished');
    expect(carrier.items.map(item => item.kind)).toEqual(authoredDocument.items.map(item => item.kind));
    expect(carrier.items.map(item => item.embed_id)).toEqual(carrier.embed_ids);
    expect(carrier.view).toEqual({ mode: 'cards', embeds: carrier.embed_ids });
    expect(new Set(carrier.embed_ids).size).toBe(25);
    const ownChat = new URL(`/#chat-id=${chatId}`, baseUrl).href;
    let collection = await openSavedChat(page, ownChat, chatId!, carrier);
    const expected = [{ id: carrierId, title: carrier.title }, ...carrier.items.map(item => ({ id: item.embed_id, title: item.title }))];
    const encrypted = async () => (await authoredEncryptedSnapshot(page, expected)).every(row => row.found
      && row.ciphertext && row.encryptedType && !row.plainContent && !row.titleInStoredRow && !row.rawCryptoFields);
    await expect.poll(encrypted, { timeout: 60_000 }).toBe(true);
    for (const kind of ['events.event', 'nutrition.recipe', 'tv.movie', 'images.image_result', 'models3d.model_result']) {
      const item = carrier.items.find(item => item.kind === kind)!;
      const fullscreen = await openChild(page, collection, item);
      if (kind === 'nutrition.recipe') await expect(fullscreen).toContainText('Red lentils');
      if (kind === 'tv.movie') await expect(fullscreen.getByTestId('tv-synopsis')).toHaveText('A supplied film synopsis.');
      if (kind === 'models3d.model_result') await expect(fullscreen.getByTestId('models3d-result-fullscreen')).toBeVisible();
      await closeFullscreen(page, fullscreen);
    }
    await page.reload();
    collection = await openSavedChat(page, ownChat, chatId!, carrier, false);
    await expectOrderedGroup(collection, carrier);
    expect(await clearAuthoredChatCache(page, baseUrl!)).toEqual({ chats: 0, messages: 0, embeds: 0, embed_keys: 0 });
    collection = await openSavedChat(page, ownChat, chatId!, carrier);
    await expect.poll(encrypted, { timeout: 60_000 }).toBe(true);
    await info.attach('authored-owner-cold-recovery', { body: await page.screenshot(), contentType: 'image/png' });

    const movie = carrier.items.find(item => item.kind === 'tv.movie')!;
    const individual = await openChild(page, collection, movie);
    const individualUrl = await createBrowserEmbedShare(page, individual, movie.embed_id);
    await recipient(browser, info, 'authored-individual', baseUrl!, apiUrl, async guest => {
      // An embed id without its encrypted fragment cannot disclose the record.
      await guest.goto(new URL(`/share/embed/${movie.embed_id}`, baseUrl!).href);
      await expect(guest.getByRole('heading', { name: 'Unable to Load Embed' })).toBeVisible();
      await expect(guest.locator('body')).not.toContainText(movie.title);
      await guest.goto(individualUrl);
      // The link must carry the independently encrypted movie's key after
      // owner cold-cache recovery, rather than inheriting its carrier key.
      const overlay = guest.getByTestId('embed-fullscreen-overlay').last();
      await expect(overlay.getByTestId('tv-title-fullscreen')).toBeVisible({ timeout: 60_000 });
      await expect.poll(() => activeEmbedId(guest)).toBe(movie.embed_id);
      await expect(overlay.getByTestId('embed-header-title')).toHaveText(movie.title);
      await expect(overlay.getByTestId('authored-result-context').getByRole('link', { name: 'Supplied test reference' })).toHaveAttribute('href', 'https://example.org/reference');
      await expect(overlay).not.toContainText('Supplied: tv.series');
      await expectPrivateFieldsHidden(overlay);
      const unshared = await guest.request.get(new URL(`/v1/share/embed/${carrierId}`, apiUrl).href);
      expect(unshared.ok()).toBe(true); // Public denial uses non-enumerating dummy data.
      const hidden = await unshared.json() as { child_embeds?: unknown[]; embed_keys?: unknown[] };
      expect(Array.isArray(hidden.child_embeds) && hidden.child_embeds.length === 0,
        'an individual share must not grant the unshared carrier membership').toBe(true);
      expect(Array.isArray(hidden.embed_keys) && hidden.embed_keys.length === 0,
        'an individual share must not expose unshared carrier key wrappers').toBe(true);
    });

    collection = await openSavedChat(page, ownChat, chatId!, carrier);
    // The group is the normal results view: no custom title row, expand button or own fullscreen layer.
    await expect(collection.getByTestId('authored-results-expand')).toHaveCount(0);
    await expect(collection.getByTestId('embeds-map-view')).toBeVisible();
    await expectOrderedGroup(collection, carrier);
    await page.reload();
    collection = await openSavedChat(page, ownChat, chatId!, carrier, false);
    await expect(collection.getByTestId('authored-results-expand')).toHaveCount(0);
    // Each member opens its own fullscreen; a draft member keeps its provenance.
    const draft = carrier.items.find(item => item.kind === 'nutrition.recipe')!;
    const leaf = await openChild(page, collection, draft);
    await expect(leaf).toContainText('Red lentils');
    await expect(leaf.getByTestId('authored-result-context')).toHaveAttribute('data-origin', 'draft');
    await closeFullscreen(page, leaf);
  } finally {
    try {
      if (chatId) {
        const deleted = await runWorkflowCli(apiUrl, home, ['chats', 'delete', chatId, '--yes', '--json'], 30_000);
        expect(deleted.code, 'disposable source chat cleanup must be acknowledged').toBe(0);
      }
    }
    finally { removeWorkflowCliHome(home); }
  }
});

// contract-test: direct surface=gui.web assertions=authored-results.groups.same-response-and-reuse,authored-results.presentation.standard-results-view,authored-results.surfaces.shared-semantics
// CI dependency: ai_committed_fixtures/default, paired CLI build + ordinary core/AI worker.
// The saved group holds two dated, geolocated events without images, so both tabs are offered.
test('saved authored group shows Calendar and Map tabs, opens each card own fullscreen and keeps members after reload', async ({ page }: {
  page: Page;
}) => {
  test.setTimeout(600_000);
  const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL;
  expect(baseUrl, 'isolated runner base URL required').toBeTruthy();
  expect(['localhost', '127.0.0.1'], 'this disposable fixture runs only in isolated CI').toContain(new URL(baseUrl!).hostname);
  const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(baseUrl!);
  const home = createWorkflowCliHome('authored-group-view');
  let chatId: string | undefined;
  try {
    await blockAuthoredFixtureImageEgress(page, baseUrl!, apiUrl);
    await loginWorkflowCliViaPair(page, apiUrl, home, 'AUTHORED_GROUP');
    const created = parseCliJson(await runWorkflowCli(apiUrl, home, ['chats', 'new',
      'Show my two supplied conference days as cards. <<<TEST_MOCK:authored_event_group>>>', '--json'], 120_000),
    'create saved authored group chat');
    expect(created.status).toBe('completed');
    chatId = created.chatId;
    expect(chatId).toMatch(/^[a-f0-9-]{36}$/);
    const refs = [...String(created.assistant).matchAll(/"embed_id"\s*:\s*"([a-f0-9-]+)"/g)];
    expect(refs).toHaveLength(1);
    const carrier = parseCliJson(await runWorkflowCli(apiUrl, home,
      ['embeds', 'show', refs[0][1], '--chat', chatId!, '--json'], 60_000), 'read saved authored carrier').content as Carrier;
    const ownChat = new URL(`/#chat-id=${chatId}`, baseUrl).href;
    expect(carrier.items.map(item => item.kind)).toEqual(['events.event', 'events.event']);
    let collection = await openSavedChat(page, ownChat, chatId!, carrier);
    // Without an image each card shows its venue map, and no card carries an origin label.
    await expect(collection.getByTestId('event-preview-map')).toHaveCount(2);
    await expect(collection.getByText('User-provided')).toHaveCount(0);

    // Both tabs exist; Map is the default and switching works in both directions.
    const mapTab = collection.getByTestId('embeds-results-view-tab-map');
    const calendarTab = collection.getByTestId('embeds-results-view-tab-calendar');
    await expect(mapTab).toBeVisible();
    await expect(calendarTab).toBeVisible();
    await expect(mapTab).toHaveAttribute('aria-selected', 'true');
    await calendarTab.click();
    await expect(calendarTab).toHaveAttribute('aria-selected', 'true');
    await expect(mapTab).toHaveAttribute('aria-selected', 'false');
    await expect(collection.getByRole('tabpanel', { name: 'Calendar results' })).toBeVisible();
    await expect(collection.getByTestId('embeds-map-view-map')).toHaveCount(0);
    await mapTab.click();
    await expect(mapTab).toHaveAttribute('aria-selected', 'true');
    await expect(collection.getByTestId('embeds-map-view-map')).toBeVisible();

    // A card opens its own fullscreen; closing returns to the chat with the group intact.
    const event = carrier.items.find(item => item.kind === 'events.event')!;
    const fullscreen = await openChild(page, collection, event);
    await closeFullscreen(page, fullscreen);
    await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId!);
    await expect(collection).toBeVisible();

    // Reload keeps the same members, order and embed ids.
    const snapshot = async (surface: Locator) => surface.getByTestId('embeds-map-view-card').evaluateAll(nodes => nodes.map(node => ({
      ref: node.getAttribute('data-entry-ref'),
      id: node.getAttribute('data-embed-id')
        ?? node.querySelector('[data-testid="embed-preview"]')?.getAttribute('data-embed-id') ?? null,
    })));
    const before = await snapshot(collection);
    expect(before.map(row => row.ref)).toEqual(carrier.embed_ids);
    await page.reload();
    collection = await openSavedChat(page, ownChat, chatId!, carrier, false);
    expect(await snapshot(collection)).toEqual(before);
  } finally {
    try {
      if (chatId) {
        const deleted = await runWorkflowCli(apiUrl, home, ['chats', 'delete', chatId, '--yes', '--json'], 30_000);
        expect(deleted.code, 'disposable source chat cleanup must be acknowledged').toBe(0);
      }
    }
    finally { removeWorkflowCliHome(home); }
  }
});
