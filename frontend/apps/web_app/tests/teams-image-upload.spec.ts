/* eslint-disable @typescript-eslint/no-require-imports -- E2E helpers expose CommonJS exports. */
export {};
import { resolve } from 'node:path';
import type { Browser, Page, Response, Route, TestInfo } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { fillMessageEditor, loginToTestAccount, startNewChat, waitForChatReady } = require('./helpers/chat-test-helpers');
const { waitForHydratedChat } = require('./helpers/chat-hydration');
const { scrollChatHistoryToStart } = require('./helpers/chat-scroll');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

type Frame = { direction: 'sent' | 'received'; type: string; payload: Record<string, any> };
function captureProtocol(page: Page, frames: Frame[]): void {
  page.on('websocket', socket => {
    for (const [event, direction] of [['framesent', 'sent'], ['framereceived', 'received']] as const) {
      socket.on(event, frame => {
        try {
          const value = JSON.parse(String(frame.payload));
          if (value.type && value.payload) frames.push({ direction, type: value.type, payload: value.payload });
        } catch { /* Control frames. */ }
      });
    }
  });
}
function requestIs(response: Response, method: string, path: RegExp): boolean {
  return response.request().method() === method && path.test(new URL(response.url()).pathname);
}
function missingEmbeds(frames: Frame[]): Frame[] {
  return frames.filter(frame => frame.direction === 'received' && frame.type === 'error' &&
    /embed not found/i.test(String(frame.payload.message)));
}

// SystemMessageNotice.svelte is exercised through the TeamChatReminder surface,
// including its role, ordering, toolbar clearance and readable message text.
async function expectReadableReminder(page: Page, testInfo: TestInfo): Promise<void> {
  const reminder = page.getByTestId('team-chat-ai-reminder');
  await expect(reminder).toHaveAttribute('role', 'note');
  await expect(reminder).toContainText('Mention @openmates');
  const paragraph = reminder.locator('p');
  const container = page.getByTestId('chat-history-container');
  await scrollChatHistoryToStart(page, testInfo);
  // The initial system notice must clear the top fade and floating action bar.
  await expect.poll(async () => {
    const [textBox, containerBox] = await Promise.all([paragraph.boundingBox(), container.boundingBox()]);
    return textBox && containerBox ? textBox.y - containerBox.y : -1;
  }).toBeGreaterThanOrEqual(30);
  await expect.poll(async () => {
    const [textBox, toolbarBox] = await Promise.all([paragraph.boundingBox(), page.getByTestId('chat-top-actions').boundingBox()]);
    return textBox && toolbarBox ? textBox.y - (toolbarBox.y + toolbarBox.height) : -1;
  }).toBeGreaterThanOrEqual(0);
  await expect.poll(() => paragraph.evaluate(element => {
    const box = element.getBoundingClientRect();
    const hit = document.elementFromPoint(box.x + 1, box.y + Math.min(box.height / 2, 10));
    return box.y >= 0 && box.bottom <= innerHeight && !!hit && element.contains(hit);
  })).toBe(true);
  const [reminderBox, firstMessageBox] = await Promise.all([
    reminder.boundingBox(), page.getByTestId('message-user').first().boundingBox(),
  ]);
  expect(reminderBox!.y + reminderBox!.height).toBeLessThanOrEqual(firstMessageBox!.y);
}

// contract-test: direct surface=gui.web assertions=teams.collaboration.realtime-team-sync,teams.chat.encrypted-until-invoked,teams.context.full-switch-local
test('keeps a pending Team image local, then shares the encrypted image with a member after reload', async (
  { page, browser }: { page: Page; browser: Browser }, testInfo: TestInfo,
) => {
  test.setTimeout(300_000);
  const owner = getTestAccount(1);
  const member = getTestAccount(2);
  test.skip(!owner.email || !member.email || owner.email === member.email, 'Two isolated accounts required.');
  await skipIfFeaturesDisabled(test, page, ['platform:teams']);
  const ownerFrames: Frame[] = [];
  const memberFrames: Frame[] = [];
  captureProtocol(page, ownerFrames);
  await loginToTestAccount(page, undefined, undefined, { credentials: owner });
  let teamId: string | undefined;
  let apiOrigin: string | undefined;
  let memberContext: Awaited<ReturnType<Browser['newContext']>> | undefined;
  let memberVideo: ReturnType<Page['video']> | undefined;
  let releaseUpload: (() => void) | undefined;
  const uploadGate = new Promise<void>(resolveGate => { releaseUpload = resolveGate; });
  let flowError: unknown;
  const cleanupErrors: unknown[] = [];
  try {
    await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', {
      configurable: true, value: { writeText: async (text: string) => { document.body.dataset.secureInvite = text; } },
    }));
    await page.getByTestId('profile-container').click();
    await page.getByTestId('settings-teams-item').click();
    await page.getByTestId('team-create-open').click();
    await page.getByTestId('team-name-input').fill(`Image collaboration ${Date.now()}`);
    await page.getByTestId('team-create-continue').click();
    const created = page.waitForResponse(response => requestIs(response, 'POST', /^\/v1\/teams$/) && response.ok());
    await page.getByTestId('team-create-submit').click();
    const createResponse = await created;
    apiOrigin = new URL(createResponse.url()).origin;
    teamId = String((await createResponse.json()).team.team_id);
    await page.getByTestId('team-members-open').click();
    await page.getByTestId('team-invite-email-input').fill(member.email);
    const invited = page.waitForResponse(response => requestIs(response, 'POST', /\/invites$/) && response.ok());
    await page.getByTestId('team-invite-submit').click();
    const invite = (await (await invited).json()).invite;
    await page.getByTestId('team-invite-copy-secure-link').click();
    const secureLink = await page.locator('body').getAttribute('data-secure-invite');
    expect(secureLink).toMatch(/\/teams\/invites\/[^#]+#key=[A-Za-z0-9_-]{43}$/);
    const viewport = page.viewportSize();
    if (!viewport) throw new Error('Recorded owner viewport required');
    memberContext = await browser.newContext({ baseURL: new URL(secureLink!).origin, viewport,
      recordVideo: { dir: testInfo.outputPath('member-video'), size: viewport } });
    const memberPage = await memberContext.newPage();
    memberVideo = memberPage.video();
    captureProtocol(memberPage, memberFrames);
    await memberPage.goto(secureLink!);
    await expect.poll(() => memberPage.url()).not.toContain('#key=');
    await loginToTestAccount(memberPage, undefined, undefined, { credentials: member });
    await memberPage.goto(getE2EDebugUrl(`/#settings/teams/invites/${encodeURIComponent(invite.invite_id)}`));
    await memberPage.getByTestId('team-invite-recipient-email').fill(member.email);
    const accepted = memberPage.waitForResponse(response => requestIs(response, 'POST', /\/invites\/[^/]+\/accept$/) && response.ok());
    await memberPage.getByTestId('team-invite-accept').click();
    expect((await (await accepted).json()).status).toBe('accepted');
    await expect(memberPage.getByTestId('team-invite-result')).toContainText(/joined/i);
    await page.getByTestId('banner-back-button').click();
    await page.getByTestId('banner-back-button').click();
    await expect.poll(() => new URL(page.url()).hash).toBe('#settings/teams');
    await page.getByTestId('banner-back-button').click();
    await page.getByTestId('team-context-dropdown').click();
    await page.getByTestId(`team-context-option-${teamId}`).click();
    await page.getByTestId('icon-button-close').click();
    await waitForChatReady(page);
    await startNewChat(page);
    const field = page.getByTestId('message-field').last();
    const editor = field.getByTestId('message-editor');
    const firstLine = 'Here is our shared Team photo.';
    const firstStart = ownerFrames.length;
    await fillMessageEditor(page, editor, firstLine);
    await field.locator('[data-action="send-message"]').click();
    await expect(page.getByTestId('message-user').filter({ hasText: firstLine })).toBeVisible();
    const chatId = await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id');
    expect(chatId).toBeTruthy();
    await expect(page.getByTestId('team-chat-ai-reminder')).toContainText('@openmates');
    await expectReadableReminder(page, testInfo);
    await expect.poll(() => ownerFrames.slice(firstStart).some(frame => frame.direction === 'sent' &&
      frame.type === 'chat_message_added' && frame.payload.chat_id === chatId && frame.payload.team_id === teamId)).toBe(true);
    await expect.poll(() => ownerFrames.some(frame => frame.type === 'chat_message_confirmed' && frame.payload.chat_id === chatId)).toBe(true);
    await memberPage.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId!)}&team-id=${encodeURIComponent(teamId!)}`));
    await waitForChatReady(memberPage);
    if (await memberPage.getByTestId('settings-menu').isVisible()) await memberPage.getByTestId('icon-button-close').click();
    await waitForHydratedChat(memberPage, chatId!, testInfo,
      memberPage.getByTestId('remote-human-message').filter({ hasText: firstLine }));
    await expectReadableReminder(memberPage, testInfo);

    // Hold the real upload request. No mocked response, scanner or image bytes.
    let uploadStarted = false;
    await page.route('**/v1/upload/file', async (route: Route) => {
      if (route.request().method() !== 'POST') return route.continue();
      uploadStarted = true;
      await uploadGate;
      await route.continue();
    });
    const ownerStart = ownerFrames.length;
    const memberStart = memberFrames.length;
    const uploaded = page.waitForResponse(response => requestIs(response, 'POST', /^\/v1\/upload\/file$/) && response.ok());
    await page.getByTestId('message-file-input').setInputFiles(resolve(__dirname, 'fixtures/humans_group.jpg'));
    await expect.poll(() => uploadStarted).toBe(true);
    const pending = editor.locator('[data-testid="embed-preview"][data-status="processing"]');
    await expect(pending).toBeVisible();
    // playwright-determinism: allow - exercise both 5s and 15s stale recovery timers while the real upload is blocked.
    await page.waitForTimeout(16_000);
    await expect(pending).toBeVisible();
    expect(ownerFrames.slice(ownerStart).filter(frame => frame.direction === 'sent' && frame.type === 'request_embed')).toEqual([]);
    expect(missingEmbeds(ownerFrames.slice(ownerStart))).toEqual([]);
    await expect(page.getByText(/server error: embed not found/i)).not.toBeVisible();
    releaseUpload!();
    const uploadBody = await (await uploaded).json();
    expect(uploadBody.embed_id).toBeTruthy();
    await expect(field.getByTestId('embed-preview')).toHaveAttribute('data-status', 'finished', { timeout: 90_000 });
    const caption = 'The image is uploaded and shared with our Team.';
    await editor.press('Control+End');
    await page.keyboard.insertText(caption);
    await field.locator('[data-action="send-message"]').click();
    await expect.poll(() => ownerFrames.slice(ownerStart).some(frame => frame.type === 'chat_message_confirmed' && frame.payload.chat_id === chatId)).toBe(true);
    await expect(editor).toHaveText('');
    await expect(editor.getByTestId('embed-preview')).toHaveCount(0);
    const sent = ownerFrames.slice(ownerStart).find(frame => frame.direction === 'sent' && frame.type === 'chat_message_added' && frame.payload.chat_id === chatId)!;
    expect(sent.payload.team_id).toBe(teamId);
    expect(sent.payload.team_ai_invocation).toBeUndefined();
    expect(sent.payload.message.encrypted_content).toBeTruthy();
    expect(sent.payload.message.content).toBeUndefined();
    const saved = await memberPage.request.get(`${apiOrigin}/v1/embeds/chats/${chatId}/embeds/${uploadBody.embed_id}?team_id=${encodeURIComponent(teamId!)}`);
    expect(saved.ok()).toBe(true);
    expect((await saved.json()).embed.encrypted_content).toBeTruthy();
    const unscoped = await memberPage.request.get(`${apiOrigin}/v1/embeds/chats/${chatId}/embeds/${uploadBody.embed_id}`);
    expect(unscoped.status()).toBe(404);
    const ownerMessage = page.getByTestId('message-user').filter({ hasText: caption });
    const memberMessage = memberPage.getByTestId('remote-human-message').filter({ hasText: caption });
    const ownerImage = ownerMessage.getByTestId('embed-preview').getByRole('img', { name: 'humans_group.jpg', exact: true });
    const memberImage = memberMessage.getByTestId('embed-preview').getByRole('img', { name: 'humans_group.jpg', exact: true });
    for (const image of [ownerImage, memberImage]) {
      await expect(image).toBeVisible({ timeout: 60_000 });
      await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
    }
    await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId!)}&team-id=${encodeURIComponent(teamId!)}`));
    await waitForChatReady(page);
    await waitForHydratedChat(page, chatId!, testInfo, ownerMessage);
    await expect(editor).toHaveText('');
    await expect(editor.getByTestId('embed-preview')).toHaveCount(0);
    await expect(ownerImage).toBeVisible({ timeout: 60_000 });
    await expect.poll(() => ownerImage.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
    await expectReadableReminder(page, testInfo);
    await memberPage.reload({ waitUntil: 'domcontentloaded' });
    await waitForChatReady(memberPage);
    await waitForHydratedChat(memberPage, chatId!, testInfo, memberMessage);
    await expect(memberImage).toBeVisible({ timeout: 60_000 });
    await expect.poll(() => memberImage.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
    await expectReadableReminder(memberPage, testInfo);
    for (const [frames, start] of [[ownerFrames, ownerStart], [memberFrames, memberStart]] as const) {
      expect(missingEmbeds(frames.slice(start))).toEqual([]);
      expect(frames.slice(start).filter(frame => /team_ai_(processing|response_completed)/.test(frame.type))).toEqual([]);
    }
    await expect(page.getByText(/server error: embed not found/i)).not.toBeVisible();
  } catch (error) { flowError = error; }
  finally {
    releaseUpload?.();
    await testInfo.attach('upload-protocol-summary', { body: JSON.stringify([...ownerFrames, ...memberFrames]
      .filter(frame => frame.type === 'request_embed' || frame.type === 'error')
      .map(frame => ({ direction: frame.direction, type: frame.type, missing: /embed not found/i.test(String(frame.payload.message)) }))), contentType: 'application/json' });
    if (teamId && apiOrigin) {
      try { expect((await page.request.delete(`${apiOrigin}/v1/teams/${teamId}`)).ok()).toBe(true); }
      catch (error) { cleanupErrors.push(error); }
    }
    if (memberContext) {
      try { await memberContext.close(); }
      catch (error) { cleanupErrors.push(error); }
    }
    if (memberVideo) await testInfo.attach('member-image-upload', { path: await memberVideo.path(), contentType: 'video/webm' });
  }
  if (flowError && !cleanupErrors.length) throw flowError;
  if (cleanupErrors.length) {
    const errors = [...(flowError ? [flowError] : []), ...cleanupErrors];
    throw new AggregateError(errors, errors.map(error => error instanceof Error ? error.message : String(error)).join('\n\n'));
  }
});
