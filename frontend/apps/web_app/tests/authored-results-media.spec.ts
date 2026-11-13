/* eslint-disable @typescript-eslint/no-require-imports */
import type { Browser, Page, TestInfo } from '@playwright/test';
import { copyFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { authoredEncryptedSnapshot, clearAuthoredChatCache } from './helpers/authored-results-flow-helpers';
import { closeSettingsPanel } from './helpers/settings-readiness';
import { allowIsolatedAuthoredMedia, deleteSelectedUploadMessage, explicitlyShareSelectedChild,
  expectSelectedRecipeImage, openSelectedRecipe } from './helpers/authored-results-media-helpers';

const { test, expect } = require('./helpers/cookie-audit');
const { createIsolatedBrowserContext, declareTestState, waitForChatReady } = require('./helpers/chat-test-helpers');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');
const { clearWorkflowCliSyncCache, createWorkflowCliHome, loginWorkflowCliViaPair,
  parseCliJson, removeWorkflowCliHome, runWorkflowCli } = require('./helpers/workflow-cli-e2e-helpers');

const recipientState = declareTestState({ auth: 'unauthenticated recipient of an explicitly shared child',
  browserStorage: 'fresh', account: 'none', chat: 'read-only selected-media child',
  notifications: 'unchanged', securityReminders: 'unchanged' });

async function mediaStep<T>(title: string, action: () => T): Promise<Awaited<T>> {
  // Keep the last reached stage in CI stdout even if the runner cannot finish its JSON report.
  console.info(`[authored-selected-media] ${title}`);
  return test.step(title, action);
}

function references(message: { content: string; embedIds?: string[] }): string[] {
  return [...new Set([...(message.embedIds || []),
    ...[...String(message.content).matchAll(/"embed_id"\s*:\s*"([a-f0-9-]{36})"/g)].map(match => match[1])])];
}

// contract-test: direct surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable,authored-results.groups.same-response-and-reuse,authored-results.surfaces.shared-semantics
// CI dependencies: uploads + ai_committed_fixtures, paired CLI preparation and
// exact isolated full-storage epoch-one activation. No external inference/provider.
test('selected uploaded media survives source-message deletion and explicit child sharing', async (
  { page, browser }: { page: Page; browser: Browser }, info: TestInfo,
) => {
  test.setTimeout(900_000);
  const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL;
  expect(baseUrl, 'isolated runner URL required').toBeTruthy();
  expect(['localhost', '127.0.0.1']).toContain(new URL(baseUrl!).hostname);
  const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(baseUrl!);
  const home = createWorkflowCliHome('authored-selected-media');
  const selectedFile = join(home, 'authored-selected-image.jpg');
  const unrelatedFile = join(home, 'authored-unrelated-image.jpg');
  copyFileSync(join(__dirname, 'fixtures/golden_gate_bridge.jpg'), selectedFile);
  copyFileSync(join(__dirname, 'fixtures/finance.jpeg'), unrelatedFile);
  let chatId: string | undefined;
  try {
    await allowIsolatedAuthoredMedia(page, baseUrl!, apiUrl);
    await mediaStep('Pair the isolated CLI with the browser account', () =>
      loginWorkflowCliViaPair(page, apiUrl, home, 'AUTHORED_MEDIA'));
    // A real unrelated upload is in authorized history, but is never selected by
    // the authored document. The seed fixture also replaces postprocessing AI.
    const initial = parseCliJson(await mediaStep('Save the unrelated upload', () => runWorkflowCli(apiUrl, home, ['chats', 'new',
      `Keep this unrelated upload separate. @${unrelatedFile} <<<TEST_MOCK:chat_recommendations:instant>>>`, '--json'],
    180_000)), 'seed saved chat with unrelated upload');
    expect(initial.status).toBe('completed');
    chatId = initial.chatId;
    expect(chatId).toMatch(/^[a-f0-9-]{36}$/);
    // Upload and authoring belong to separate user turns. The existing output
    // ledger binds each authored cohort to its initiating user message; deleting
    // that message would legitimately delete the card as well as the upload.
    const upload = await mediaStep('Save the selected upload in its own message', () => runWorkflowCli(apiUrl, home, ['chats', 'send', '--chat', chatId,
      `Keep this selected illustration for my next request. @${selectedFile} <<<TEST_MOCK:chat_recommendations:instant>>>`, '--json'],
    180_000, { OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'authored-selected-media-upload' }));
    expect(upload.recording, 'real terminal capture of selected CLI upload').toBeTruthy();
    if (upload.recording) {
      await info.attach('authored-selected-media-upload-cli', { path: upload.recording.videoPath, contentType: 'video/mp4' });
      await info.attach('authored-selected-media-upload-cli-manifest', { path: upload.recording.manifestPath, contentType: 'application/json' });
    }
    expect(parseCliJson(upload, 'save selected upload in its own message').status).toBe('completed');
    const result = await mediaStep('Author the recipe from selected historical media', () => runWorkflowCli(apiUrl, home, ['chats', 'send', '--chat', chatId,
      'Create the supplied recipe from history using only authored-selected-image.jpg as its illustration. <<<TEST_MOCK:authored_selected_media>>>', '--json'],
    180_000, { OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'authored-selected-media-authoring' }));
    expect(result.recording, 'real terminal capture of historical-media authoring').toBeTruthy();
    if (result.recording) {
      await info.attach('authored-selected-media-cli', { path: result.recording.videoPath, contentType: 'video/mp4' });
      await info.attach('authored-selected-media-cli-manifest', { path: result.recording.manifestPath, contentType: 'application/json' });
    }
    const created = parseCliJson(result, 'create selected-media authored children');
    expect(created.status).toBe('completed');
    expect(created.messageId, 'actual authoring assistant message identity').toMatch(/^[a-f0-9-]{36}$/);
    expect(created.assistant).toContain('The unrelated upload is not an image for this card.');
    const carrierIds = references({ content: created.assistant });
    expect(carrierIds).toHaveLength(1);
    const carrierId = carrierIds[0];
    const read = async (id: string) => parseCliJson(await runWorkflowCli(apiUrl, home,
      ['embeds', 'show', id, '--chat', chatId!, '--json'], 60_000), 'read saved media embed').content;
    const saved = parseCliJson(await runWorkflowCli(apiUrl, home,
      ['chats', 'show', chatId!, '--json'], 90_000), 'read actual upload-message identities');
    const selectedMessage = saved.messages.find((message: any) => message.role === 'user'
      && message.content.includes('Keep this selected illustration'));
    const unrelatedMessage = saved.messages.find((message: any) => message.role === 'user'
      && message.content.includes('Keep this unrelated upload'));
    const authoringMessage = saved.messages.find((message: any) => message.role === 'user'
      && message.content.includes('Create the supplied recipe from history'));
    expect(!!selectedMessage && !!unrelatedMessage && !!authoringMessage).toBe(true);
    const selectedMessageId = selectedMessage.clientMessageId || selectedMessage.id;
    const authoringMessageId = authoringMessage.clientMessageId || authoringMessage.id;
    expect(authoringMessageId).not.toBe(selectedMessageId);
    const selectedIds = references(selectedMessage);
    const unrelatedIds = references(unrelatedMessage);
    expect(selectedIds).toHaveLength(1);
    expect(unrelatedIds).toHaveLength(1);
    const uploadId = selectedIds[0];
    const unrelatedId = unrelatedIds[0];
    expect(uploadId).not.toBe(unrelatedId);
    const original = await read(uploadId);
    const unrelated = await read(unrelatedId);
    const carrier = await read(carrierId);
    expect(carrier.status).toBe('finished');
    expect(carrier.validation.status).toBe('valid');
    expect(carrier.embed_ids).toHaveLength(2);
    expect(carrier.embed_ids).not.toContain(uploadId);
    expect(carrier.embed_ids).not.toContain(unrelatedId);
    const recipeId = carrier.items.find((item: any) => item.kind === 'nutrition.recipe').embed_id;
    const siblingId = carrier.items.find((item: any) => item.kind === 'events.event').embed_id;
    const recipe = await read(recipeId);
    const sibling = await read(siblingId);
    const authoringMessageHash = createHash('sha256').update(authoringMessageId).digest('hex');
    for (const id of [carrierId, recipeId]) {
      const canonical = await page.request.get(`${apiUrl}/v1/embeds/chats/${chatId}/embeds/${id}`);
      expect(canonical.status(), 'authored cohort is durably readable before source deletion').toBe(200);
      expect((await canonical.json()).embed.hashed_message_id,
        'actual canonical cohort binds the authoring turn, independently of the source upload').toBe(authoringMessageHash);
    }
    expect(recipe.title).toBe('Supplied lentil recipe');
    expect(recipe).not.toHaveProperty('embed_ids');
    expect(sibling).not.toHaveProperty('authored_media');
    expect(Array.isArray(recipe.authored_media) && recipe.authored_media.length === 1,
      'exactly one selected encrypted descriptor, never the upload graph').toBe(true);
    const media = recipe.authored_media[0];
    expect(media.source_embed_id).toBe(uploadId);
    expect(media.caption).toBe('Selected uploaded illustration');
    expect(media.attribution).toBe('Disposable CI image fixture');
    expect(recipe.authoring.images).toEqual([{ embed_ref: 'authored-selected-image.jpg',
      caption: 'Selected uploaded illustration', attribution: 'Disposable CI image fixture' }]);
    // Only booleans cross assertion diagnostics: never print raw rendition keys
    // or AES metadata when a comparison fails.
    const selectedKeys = Object.values(media.files).map((file: any) => file.s3_key);
    const unrelatedKeys = new Set(Object.values(unrelated.files).map((file: any) => file.s3_key));
    expect(selectedKeys.length > 0 && selectedKeys.every(key => !unrelatedKeys.has(key))).toBe(true);
    expect(Object.entries(media.files).every(([name, file]) => isDeepStrictEqual(file, original.files[name]))).toBe(true);
    expect(media.aes_key === original.aes_key && media.aes_nonce === original.aes_nonce).toBe(true);
    expect(JSON.stringify(recipe).includes(unrelatedId)).toBe(false);

    const ownChat = new URL(`/#chat-id=${chatId}`, baseUrl).href;
    // Pairing leaves the settings drawer open on the new-chat screen; close it so
    // it cannot cover or reset the chat before the message context menu is used.
    if (await page.getByTestId('profile-container').getAttribute('data-action') === 'close-settings') {
      await closeSettingsPanel(page, info);
    }
    await page.goto(ownChat);
    await waitForChatReady(page, undefined, 60_000);
    await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId);
    let overlay = await mediaStep('Open the saved selected-media recipe before source deletion', () =>
      openSelectedRecipe(page, recipeId, created.messageId));
    await overlay.getByTestId('embed-minimize').click();
    await expect(overlay).not.toBeVisible();
    // The chat must still be the open one (not the new-chat screen) and the
    // source upload message must be rendered before its context menu is opened.
    await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId, { timeout: 30_000 });
    await page.locator(`[data-testid="message-user"][data-message-id="${selectedMessageId}"]`).scrollIntoViewIfNeeded({ timeout: 30_000 });
    await mediaStep('Delete only the source upload message and await canonical deletion', () =>
      deleteSelectedUploadMessage(page, apiUrl, chatId!, selectedMessageId, uploadId));
    // Cold CLI reads prove the child's selected keys did not live only in its
    // source upload or local cache; the independent sibling stays readable.
    clearWorkflowCliSyncCache(home);
    const recovered = await mediaStep('Cold-read the retained recipe after source deletion', () => read(recipeId));
    expect(isDeepStrictEqual(recovered, recipe), 'cold child content remains identical').toBe(true);
    expect((await read(siblingId)).title).toBe('Independent supplied event');
    expect((await read(unrelatedId)).filename).toBe('authored-unrelated-image.jpg');
    expect(await clearAuthoredChatCache(page, baseUrl!)).toEqual({ chats: 0, messages: 0, embeds: 0, embed_keys: 0 });
    await page.goto(ownChat);
    await waitForChatReady(page, undefined, 60_000);
    overlay = await mediaStep('Reopen retained media after clearing the browser chat cache', () =>
      openSelectedRecipe(page, recipeId, created.messageId));
    const encrypted = await authoredEncryptedSnapshot(page, [{ id: recipeId, title: recipe.title }]);
    expect(encrypted.every(row => row.found && row.ciphertext && row.encryptedType
      && !row.plainContent && !row.titleInStoredRow && !row.rawCryptoFields)).toBe(true);
    const url = await mediaStep('Explicitly share only the selected recipe child', () =>
      explicitlyShareSelectedChild(page, overlay, recipeId));
    const context = await createIsolatedBrowserContext(browser, recipientState, {
      recordVideo: { dir: info.outputPath('selected-media-recipient'), size: { width: 1280, height: 800 } },
    });
    const guest: Page = await context.newPage();
    const video = guest.video();
    try {
      await allowIsolatedAuthoredMedia(guest, baseUrl!, apiUrl);
      await guest.goto(url);
      const shared = guest.getByTestId('embed-fullscreen-overlay').last();
      await mediaStep('Verify the unauthenticated recipient decrypts the retained illustration', () =>
        expectSelectedRecipeImage(shared));
      await expect(shared.getByTestId('embed-header-title')).toHaveText(recipe.title);
      await expect(guest.locator('[data-authenticated="true"]')).toHaveCount(0);
      await expect(shared).not.toContainText('Independent supplied event');
      const denied = await guest.request.get(`${apiUrl}/v1/embeds/chats/${chatId}/embeds/${unrelatedId}`);
      expect([401, 403, 404]).toContain(denied.status());
      await info.attach('selected-media-shared-child', { body: await guest.screenshot(), contentType: 'image/png' });
      await mediaStep('Reject access to the unshared sibling', () =>
        guest.goto(new URL(`/share/embed/${siblingId}`, baseUrl).href));
      await expect(guest.getByRole('heading', { name: 'Unable to Load Embed' })).toBeVisible();
      await expect(guest.locator('body')).not.toContainText('Independent supplied event');
    } finally {
      await context.close();
      if (video) await info.attach('selected-media-recipient', { path: await video.path(), contentType: 'video/webm' });
    }
  } finally {
    try {
      if (chatId) expect((await runWorkflowCli(apiUrl, home,
        ['chats', 'delete', chatId, '--yes', '--json'], 60_000)).code).toBe(0);
    } finally { removeWorkflowCliHome(home); }
  }
});
