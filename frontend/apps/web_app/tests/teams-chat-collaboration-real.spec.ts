/* eslint-disable @typescript-eslint/no-require-imports -- E2E helpers expose CommonJS exports. */
/** Dev-only proof: two real Team members collaborate before and after real AI turns. */
export {};
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { writeFile } from 'node:fs/promises';
import type { APIResponse, Browser, Page, Response, TestInfo } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { fillMessageEditor, loginToTestAccount, startNewChat, waitForChatReady } = require('./helpers/chat-test-helpers');
const { selectMentionResult } = require('./helpers/mention-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

type Frame = { direction: 'sent' | 'received'; type: string; payload: Record<string, any> };
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const API_URL = (process.env.PLAYWRIGHT_TEST_API_URL || BASE_URL.replace('://app.dev.', '://api.dev.')).replace(/\/$/, '');

function requireDirectDevRealInference(): void {
  if (process.env.CI || process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1') {
    throw new Error('Team chat real-inference proof must run on coordinated dev, never CI.');
  }
  if (process.env.OPENMATES_TEAMS_CHAT_REAL_AI !== '1' || process.env.E2E_USE_MOCKS || process.env.E2E_USE_LIVE_MOCKS) {
    throw new Error('Set OPENMATES_TEAMS_CHAT_REAL_AI=1 with all mock modes disabled.');
  }
  if (!new URL(BASE_URL).hostname.includes('.dev.') || !new URL(API_URL).hostname.includes('.dev.')) {
    throw new Error('Team chat real-inference proof is restricted to dev hosts.');
  }
  const owner = getTestAccount(1);
  const member = getTestAccount(2);
  if (!owner.email || !owner.password || !owner.otpKey || !member.email || !member.password || !member.otpKey || owner.email === member.email) {
    throw new Error('Two distinct provisioned dev test accounts with TOTP are required.');
  }
  const hook = process.env.OPENMATES_TEAM_CHAT_CREDIT_HOOK;
  if (!hook || !existsSync(hook)) {
    throw new Error('A coordinator-owned OPENMATES_TEAM_CHAT_CREDIT_HOOK executable is required to fund only the fresh test Team.');
  }
}

function captureProtocol(page: Page, frames: Frame[]): void {
  const apiHost = new URL(API_URL).host;
  page.on('websocket', (socket) => {
    if (new URL(socket.url()).host !== apiHost) return;
    const capture = (direction: Frame['direction']) => (frame: { payload?: string | Buffer }) => {
        try {
          const value = JSON.parse(String(frame.payload)) as { type?: string; payload?: Record<string, any> };
          if (value.type && value.payload && typeof value.payload === 'object') {
            frames.push({ direction, type: value.type, payload: value.payload });
          }
        } catch { /* WebSocket control frame. */ }
    };
    socket.on('framesent', capture('sent'));
    socket.on('framereceived', capture('received'));
  });
}

function proofId(value: unknown): string | null {
  return typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value) ? value : null;
}

async function waitForFrame(frames: Frame[], from: number, direction: Frame['direction'], type: string,
  predicate: (payload: Record<string, any>) => boolean = () => true, timeout = 45_000): Promise<Frame> {
  let found: Frame | undefined;
  await expect.poll(() => {
    found = frames.slice(from).find((frame) => frame.direction === direction && frame.type === type && predicate(frame.payload));
    return Boolean(found);
  }, { timeout, message: `Expected ${direction} ${type} protocol event` }).toBe(true);
  return found!;
}

async function sendText(page: Page, content: string): Promise<void> {
  const field = page.getByTestId('message-field').last();
  const editor = field.getByTestId('message-editor');
  await expect(editor).toBeVisible();
  await fillMessageEditor(page, editor, content);
  await field.locator('[data-action="send-message"]').click();
  await expect(page.getByTestId('message-user').filter({ hasText: content })).toBeVisible({ timeout: 60_000 });
}

async function sendSelectedMate(page: Page, content: string): Promise<void> {
  await selectMentionResult(page, 'Sophia', 'Sophia');
  const field = page.getByTestId('message-field').last();
  await expect(field.locator('.mate-mention-node, .mate-mention')).toContainText('@Sophia');
  await page.keyboard.press('End');
  await page.keyboard.insertText(` ${content}`);
  await field.locator('[data-action="send-message"]').click();
}

async function readTeamCredits(page: Page, teamId: string): Promise<number> {
  const response = await page.request.get(`${API_URL}/v1/teams/${teamId}/billing`);
  expect(response.ok()).toBe(true);
  const body = await response.json() as { billing?: { balance_credits?: number } };
  expect(Number.isInteger(body.billing?.balance_credits)).toBe(true);
  return body.billing!.balance_credits!;
}

async function readTeamUsage(page: Page, teamId: string): Promise<Array<Record<string, any>>> {
  const response = await page.request.get(`${API_URL}/v1/teams/${teamId}/billing/usage`);
  expect(response.ok()).toBe(true);
  const body = await response.json() as { usage?: Array<Record<string, any>> };
  expect(Array.isArray(body.usage)).toBe(true);
  const teamHash = createHash('sha256').update(teamId).digest('hex');
  for (const row of body.usage!) {
    expect(row.hashed_team_id).toBe(teamHash);
    expect(row.credit_amount).toBeGreaterThan(0);
  }
  return body.usage!;
}

async function readPersonalCredits(page: Page): Promise<number> {
  const response = await page.request.get(`${API_URL}/v1/settings/delete-account-preview`);
  expect(response.ok()).toBe(true);
  const body = await response.json() as { total_credits?: number };
  expect(Number.isInteger(body.total_credits)).toBe(true);
  return body.total_credits!;
}

async function assertOwnRightOfRemote(page: Page, ownLine: string, remoteLine: string): Promise<void> {
  const own = page.getByTestId('message-user').filter({ hasText: ownLine }).locator('[class*="message-align-"]');
  const remote = page.getByTestId('remote-human-message').filter({ hasText: remoteLine }).locator('[class*="message-align-"]');
  await expect(own).toHaveClass(/message-align-right/);
  await expect(remote).toHaveClass(/message-align-left/);
  const [ownBox, remoteBox] = await Promise.all([own.boundingBox(), remote.boundingBox()]);
  expect(ownBox).not.toBeNull();
  expect(remoteBox).not.toBeNull();
  expect(ownBox!.x, 'own Team message should sit to the right of another human').toBeGreaterThan(remoteBox!.x);
}

async function assertTeamWindow(page: Page, teamId: string, chatId: string, privateLines: string[]): Promise<Array<Record<string, any>>> {
  const personal = await page.request.get(`${API_URL}/v1/chats/${chatId}/messages/window?limit=100`);
  expect(personal.status()).toBe(404);
  let response: APIResponse | undefined;
  await expect.poll(async () => {
    response = await page.request.get(`${API_URL}/v1/chats/${chatId}/messages/window?team_id=${teamId}&limit=100`);
    if (!response.ok()) return 0;
    const body = await response.json() as { messages?: unknown[] };
    return body.messages?.length ?? 0;
  }, { timeout: 45_000 }).toBeGreaterThanOrEqual(privateLines.length);
  expect(response?.ok()).toBe(true);
  const body = await response!.json() as { messages: Array<Record<string, any>> };
  expect(body.messages.length).toBeGreaterThanOrEqual(privateLines.length);
  for (const line of privateLines) expect(JSON.stringify(body)).not.toContain(line);
  for (const message of body.messages.filter((row) => row.role === 'user')) {
    expect(message.encrypted_content).toBeTruthy();
    expect(message.hashed_user_id).toMatch(/^[0-9a-f]{64}$/);
    expect(message.content).toBeUndefined();
    expect(message.sender_name).toBeUndefined();
  }
  return body.messages;
}

test.beforeAll(() => requireDirectDevRealInference());

// contract-test: direct surface=gui.web assertions=teams.collaboration.realtime-team-sync,teams.chat.encrypted-until-invoked,teams.chat.sender-identity-layout,teams.chat-billing.team-credit-boundary,teams.context.full-switch-local
test('two Team members collaborate privately and invoke OpenMates with their full attributed history', async (
  { page, browser }: { page: Page; browser: Browser }, testInfo: TestInfo,
) => {
  test.setTimeout(600_000);
  page.setDefaultTimeout(60_000);
  page.setDefaultNavigationTimeout(60_000);
  const owner = getTestAccount(1);
  const member = getTestAccount(2);
  const ownerFrames: Frame[] = [];
  const memberFrames: Frame[] = [];
  captureProtocol(page, ownerFrames);
  await skipIfFeaturesDisabled(test, page, ['platform:teams']);
  await loginToTestAccount(page, undefined, undefined, { credentials: owner });
  let teamId: string | null = null;
  let chatId: string | null = null;
  let ownerOrdinaryEnd: number | null = null;
  let memberOrdinaryEnd: number | null = null;
  const laterOrdinaryMessageIds: string[] = [];
  let memberContext: Awaited<ReturnType<Browser['newContext']>> | undefined;
  let memberPage: Page | undefined;
  const ownerVideo = page.video();
  let memberVideo: ReturnType<Page['video']> | undefined;
  let runError: unknown;
  const cleanupErrors: Error[] = [];
  try {
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
        writeText: async (text: string) => { document.body.dataset.secureInvite = text; }
      } });
    });
    await page.getByTestId('profile-container').click();
    await page.getByTestId('settings-teams-item').click();
    await expect(page.getByTestId('team-create-open')).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('team-create-open').click();
    const teamName = `Berlin planning ${Date.now()}`;
    await page.getByTestId('team-name-input').fill(teamName);
    await page.getByTestId('team-create-continue').click();
    const created = page.waitForResponse((response: Response) => response.request().method() === 'POST' &&
      new URL(response.url()).pathname === '/v1/teams' && response.ok());
    await page.getByTestId('team-create-submit').click();
    teamId = String((await (await created).json()).team.team_id);
    expect(teamId).toBeTruthy();
    // The operator hook may fund only this freshly created disposable Team.
    execFileSync(process.env.OPENMATES_TEAM_CHAT_CREDIT_HOOK!, [teamId], { timeout: 60_000, stdio: 'ignore' });
    await page.getByTestId('team-members-open').click();
    await page.getByTestId('team-invite-email-input').fill(member.email);
    const invited = page.waitForResponse((response: Response) => response.request().method() === 'POST' &&
      /\/invites$/.test(new URL(response.url()).pathname) && response.ok());
    await page.getByTestId('team-invite-submit').click();
    const invite = (await (await invited).json()).invite as { invite_id: string; delivery_status: string; role: string };
    expect(invite.delivery_status).toBe('client_share_required');
    expect(invite.role).toBe('member');
    await page.getByTestId('team-invite-copy-secure-link').click();
    const secureLink = await page.locator('body').getAttribute('data-secure-invite');
    expect(secureLink).toMatch(/\/teams\/invites\/[^#]+#key=[A-Za-z0-9_-]{43}$/);

    const viewport = page.viewportSize();
    if (!viewport) throw new Error('Owner viewport is required for two-actor video');
    memberContext = await browser.newContext({ baseURL: new URL(secureLink!).origin, viewport,
      recordVideo: { dir: testInfo.outputPath('member-video'), size: viewport } });
    memberPage = await memberContext.newPage();
    memberPage.setDefaultTimeout(60_000);
    memberPage.setDefaultNavigationTimeout(60_000);
    memberVideo = memberPage.video();
    captureProtocol(memberPage, memberFrames);
    await memberPage.goto(secureLink!);
    await expect.poll(() => memberPage!.url()).not.toContain('#key=');
    await loginToTestAccount(memberPage, undefined, undefined, { credentials: member });
    // Login returns to the home page; the secure link already stored its key in this tab.
    await memberPage.goto(getE2EDebugUrl(`/#settings/teams/invites/${encodeURIComponent(invite.invite_id)}`));
    await expect(memberPage.getByTestId('team-invite-recipient-email')).toBeVisible();
    await memberPage.getByTestId('team-invite-recipient-email').fill(member.email);
    const accepted = memberPage.waitForResponse((response: Response) => response.request().method() === 'POST' &&
      /\/invites\/[^/]+\/accept$/.test(new URL(response.url()).pathname) && response.ok());
    await memberPage.getByTestId('team-invite-accept').click();
    expect((await (await accepted).json()).status).toBe('accepted');
    await expect(memberPage.getByTestId('team-invite-result')).toContainText(/joined/i);
    await page.getByTestId('banner-back-button').click();
    await page.getByTestId('banner-back-button').click();
    await expect.poll(() => new URL(page.url()).hash).toBe('#settings/teams');
    await page.getByTestId('banner-back-button').click();
    await expect(page.getByTestId('team-context-dropdown')).toBeVisible();
    await page.getByTestId('team-context-dropdown').click();
    await page.getByTestId(`team-context-option-${teamId}`).click();
    await page.getByTestId('icon-button-close').click();
    await waitForChatReady(page);
    await startNewChat(page);
    const personalCreditsBefore = await readPersonalCredits(page);
    const memberPersonalCreditsBefore = await readPersonalCredits(memberPage);
    const teamCreditsBefore = await readTeamCredits(page, teamId);
    expect(await readTeamUsage(page, teamId)).toHaveLength(0);

    const lines = [
      'Could we plan our Berlin team event for Saturday afternoon?',
      'I can invite the local volunteers and check who is free.',
      'Great. I will check a venue near Alexanderplatz and share the address.',
      'I will prepare a short welcome note for the volunteers.'
    ];
    const ordinaryStart = ownerFrames.length;
    await sendText(page, lines[0]);
    await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', /.+/, { timeout: 30_000 });
    chatId = await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id');
    expect(chatId).toBeTruthy();
    await waitForFrame(ownerFrames, ordinaryStart, 'sent', 'chat_message_added',
      (payload) => payload.team_id === teamId);
    await memberPage.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId!)}&team-id=${encodeURIComponent(teamId)}`));
    await waitForChatReady(memberPage);
    // Finish invitation setup before recording the actual collaboration view.
    if (await memberPage.getByTestId('settings-menu').isVisible()) {
      await memberPage.getByTestId('icon-button-close').click();
    }
    await expect(memberPage.getByTestId('settings-menu')).not.toBeVisible();
    await expect(memberPage.getByTestId('message-user').filter({ hasText: lines[0] })).toBeVisible({ timeout: 45_000 });
    await expect(memberPage.getByTestId('remote-human-message').filter({ hasText: lines[0] })
      .getByTestId('remote-human-name')).not.toBeEmpty();
    // A member's draft is private to that account and uses the Team chat scope.
    const memberDraftStart = memberFrames.length;
    const ownerPrivateDraftStart = ownerFrames.length;
    const memberEditor = memberPage.getByTestId('message-field').last().getByTestId('message-editor');
    await fillMessageEditor(memberPage, memberEditor, lines[1]);
    const memberDraft = await waitForFrame(memberFrames, memberDraftStart, 'sent', 'update_draft',
      (payload) => payload.chat_id === chatId);
    expect(memberDraft.payload.team_id).toBe(teamId);
    expect(memberDraft.payload.encrypted_draft_md).toBeTruthy();
    expect(JSON.stringify(memberDraft.payload)).not.toContain(lines[1]);
    await waitForFrame(memberFrames, memberDraftStart, 'received', 'draft_update_receipt',
      (payload) => payload.chat_id === chatId && payload.team_id === teamId && payload.success === true);
    await sendText(memberPage, lines[1]);
    await expect(page.getByTestId('remote-human-message').filter({ hasText: lines[1] }))
      .toBeVisible({ timeout: 45_000 });
    const memberDraftDelete = await waitForFrame(memberFrames, memberDraftStart, 'sent', 'delete_draft',
      (payload) => payload.chatId === chatId);
    expect(memberDraftDelete.payload.team_id).toBe(teamId);
    await waitForFrame(memberFrames, memberDraftStart, 'received', 'draft_delete_receipt',
      (payload) => payload.chat_id === chatId && payload.team_id === teamId && payload.success === true);
    expect(ownerFrames.slice(ownerPrivateDraftStart).filter((frame) => frame.direction === 'received' &&
      ['chat_draft_updated', 'draft_deleted'].includes(frame.type) && frame.payload.chat_id === chatId))
      .toHaveLength(0);
    await sendText(page, lines[2]);
    await expect(memberPage.getByTestId('remote-human-message').filter({ hasText: lines[2] }))
      .toBeVisible({ timeout: 45_000 });
    await sendText(memberPage, lines[3]);
    await expect(page.getByTestId('remote-human-message').filter({ hasText: lines[3] }))
      .toBeVisible({ timeout: 45_000 });
    await assertOwnRightOfRemote(page, lines[2], lines[1]);
    await assertOwnRightOfRemote(memberPage, lines[1], lines[2]);
    expect(await readTeamCredits(page, teamId)).toBe(teamCreditsBefore);
    expect(await readPersonalCredits(page)).toBe(personalCreditsBefore);
    expect(await readPersonalCredits(memberPage)).toBe(memberPersonalCreditsBefore);
    const humanNames = [
      await page.getByTestId('remote-human-message').filter({ hasText: lines[1] }).getByTestId('remote-human-name').innerText(),
      await memberPage.getByTestId('remote-human-message').filter({ hasText: lines[2] }).getByTestId('remote-human-name').innerText(),
    ];
    expect(humanNames[0]).toBeTruthy();
    expect(humanNames[1]).toBeTruthy();
    expect(humanNames[0]).not.toBe(humanNames[1]);
    for (const frames of [ownerFrames.slice(ordinaryStart), memberFrames]) {
      const ordinary = frames.filter((frame) => frame.direction === 'sent' && frame.type === 'chat_message_added' && frame.payload.team_id === teamId);
      expect(ordinary.length).toBeGreaterThan(0);
      for (const frame of ordinary) {
        expect(frame.payload.team_ai_invocation).toBeUndefined();
        expect(frame.payload.message?.encrypted_content).toBeTruthy();
        expect(frame.payload.message?.content).toBeUndefined();
      }
      expect(frames.filter((frame) => /^(ai_task_initiated|team_ai_processing|team_ai_response_completed)$/.test(frame.type) &&
        frame.payload.chat_id === chatId)).toHaveLength(0);
    }
    const ownerWindow = await assertTeamWindow(page, teamId, chatId!, lines);
    const memberWindow = await assertTeamWindow(memberPage, teamId, chatId!, lines);
    expect(new Set(ownerWindow.filter((row) => row.role === 'user').map((row) => row.hashed_user_id)).size).toBe(2);
    expect(new Set(memberWindow.filter((row) => row.role === 'user').map((row) => row.hashed_user_id)).size).toBe(2);

    ownerOrdinaryEnd = ownerFrames.length;
    memberOrdinaryEnd = memberFrames.length;
    // Rebuild the owner view from persisted Team ciphertext before the first AI turn.
    // The page-level WebSocket listener remains attached to the new socket after reload.
    await page.reload({ waitUntil: 'domcontentloaded' });
    await waitForChatReady(page);
    await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId!, { timeout: 45_000 });
    for (const line of [lines[0], lines[2]]) {
      await expect(page.getByTestId('message-user').filter({ hasText: line })).toBeVisible({ timeout: 45_000 });
    }
    for (const line of [lines[1], lines[3]]) {
      const remote = page.getByTestId('remote-human-message').filter({ hasText: line });
      await expect(remote).toBeVisible({ timeout: 45_000 });
      await expect(remote.getByTestId('remote-human-name')).toContainText(humanNames[0]);
    }
    for (const line of [lines[0], lines[2]]) {
      await expect(memberPage.getByTestId('remote-human-message').filter({ hasText: line })
        .getByTestId('remote-human-name')).toContainText(humanNames[1]);
    }
    const aiStart = memberFrames.length;
    await sendText(memberPage, '@openmates, who proposed the venue and who offered to invite volunteers for our Berlin event? Please name both teammates.');
    const aiPreflight = await waitForFrame(memberFrames, aiStart, 'sent', 'chat_turn_preflight',
      (payload) => payload.inference_request?.team_ai_invocation?.history?.length >= 5);
    const history = aiPreflight.payload.inference_request.team_ai_invocation.history as Array<{ role: string; content: string; sender_name?: string }>;
    for (const line of lines) expect(history.some((item) => item.content.includes(line))).toBe(true);
    const speakers = new Set(history.filter((item) => item.role === 'user').map((item) => item.sender_name).filter(Boolean));
    expect(speakers.size).toBe(2);
    await waitForFrame(memberFrames, aiStart, 'received', 'team_ai_response_completed',
      (payload) => payload.team_id === teamId, 180_000);
    await expect(page.getByTestId('message-assistant').last()).toContainText(/venue|volunteers/i, { timeout: 180_000 });
    const answerText = (await page.getByTestId('message-assistant').last().innerText()).toLowerCase();
    for (const name of humanNames) expect(answerText).toContain(name.toLowerCase());
    await expect(memberPage.getByTestId('message-assistant').last()).toBeVisible({ timeout: 60_000 });
    await expect.poll(() => readTeamCredits(page, teamId!), { timeout: 60_000 }).toBeLessThan(teamCreditsBefore);
    const teamCreditsAfterAI = await readTeamCredits(page, teamId);
    await expect.poll(async () => (await readTeamUsage(page, teamId!)).length, { timeout: 60_000 }).toBeGreaterThan(0);
    const usageCountAfterAI = (await readTeamUsage(page, teamId)).length;
    expect(await readPersonalCredits(page)).toBe(personalCreditsBefore);
    expect(await readPersonalCredits(memberPage)).toBe(memberPersonalCreditsBefore);

    // Completion must be durable Team ciphertext, including for the invoking
    // member after a cold page reload rather than only the live stream.
    const completedWindow = await assertTeamWindow(memberPage, teamId, chatId!, lines);
    const persistedAssistant = completedWindow.filter((row) => row.role === 'assistant');
    expect(persistedAssistant.length).toBeGreaterThan(0);
    for (const row of persistedAssistant) {
      expect(row.encrypted_content).toBeTruthy();
      expect(row.content).toBeUndefined();
    }
    expect(JSON.stringify(completedWindow).toLowerCase()).not.toContain(answerText);
    await memberPage.reload({ waitUntil: 'domcontentloaded' });
    await waitForChatReady(memberPage);
    await expect(memberPage.getByTestId('active-chat-container'))
      .toHaveAttribute('data-current-chat-id', chatId!, { timeout: 45_000 });
    await expect(memberPage.getByTestId('message-assistant').last()).toBeVisible({ timeout: 45_000 });
    const recoveredAnswer = (await memberPage.getByTestId('message-assistant').last().innerText()).toLowerCase();
    for (const name of humanNames) expect(recoveredAnswer).toContain(name.toLowerCase());

    const followStart = memberFrames.length;
    await sendText(memberPage, 'Thanks. I will send the volunteers the final venue once we confirm it.');
    await expect(page.getByTestId('remote-human-message').filter({ hasText: 'final venue' })).toBeVisible({ timeout: 45_000 });
    const followSend = await waitForFrame(memberFrames, followStart, 'sent', 'chat_message_added');
    const followMessageId = proofId(followSend.payload.message?.message_id ?? followSend.payload.message_id);
    if (followMessageId) laterOrdinaryMessageIds.push(followMessageId);
    expect(followSend.payload.team_ai_invocation).toBeUndefined();
    await waitForFrame(memberFrames, followStart, 'received', 'chat_message_confirmed',
      (payload) => payload.chat_id === chatId);
    await memberPage.waitForTimeout(1_000);
    expect(memberFrames.slice(followStart).some((frame) => frame.type === 'team_ai_processing' &&
      frame.payload.chat_id === chatId)).toBe(false);
    expect(await readTeamCredits(page, teamId)).toBe(teamCreditsAfterAI);
    expect(await readTeamUsage(page, teamId)).toHaveLength(usageCountAfterAI);
    expect(await readPersonalCredits(page)).toBe(personalCreditsBefore);
    expect(await readPersonalCredits(memberPage)).toBe(memberPersonalCreditsBefore);

    const mateStart = ownerFrames.length;
    const assistantCountBeforeMate = await page.getByTestId('message-assistant').count();
    await sendSelectedMate(page, 'please suggest one practical next step for this Berlin event.');
    const matePreflight = await waitForFrame(ownerFrames, mateStart, 'sent', 'chat_turn_preflight',
      (payload) => payload.inference_request?.team_ai_invocation?.history?.length >= 8);
    const mateHistory = matePreflight.payload.inference_request.team_ai_invocation.history as Array<{ content: string }>;
    expect(mateHistory.some((item) => item.content.includes('@mate:software_development'))).toBe(true);
    expect(mateHistory.some((item) => item.content.includes('final venue'))).toBe(true);
    await waitForFrame(ownerFrames, mateStart, 'received', 'team_ai_response_completed',
      (payload) => payload.team_id === teamId, 180_000);
    await expect.poll(() => page.getByTestId('message-assistant').count(), { timeout: 60_000 })
      .toBeGreaterThan(assistantCountBeforeMate);
    await expect.poll(() => memberPage!.getByTestId('message-assistant').count(), { timeout: 60_000 })
      .toBeGreaterThan(assistantCountBeforeMate);
    // A streaming placeholder also counts as an assistant bubble. Prove the
    // configured Mate's completed body actually renders identically for both humans.
    const ownerMateBody = page.getByTestId('message-assistant').last().locator('.chat-message-text').first();
    const memberMateBody = memberPage.getByTestId('message-assistant').last().locator('.chat-message-text').first();
    await expect(ownerMateBody).toBeVisible({ timeout: 60_000 });
    await expect.poll(async () => (await ownerMateBody.innerText()).trim().length, { timeout: 60_000 })
      .toBeGreaterThan(40);
    const mateAnswer = (await ownerMateBody.innerText()).replace(/\s+/g, ' ').trim();
    expect(mateAnswer).not.toMatch(/\[(?:Decrypting\.{3}|Content decryption failed)\]/);
    await expect.poll(async () => (await memberMateBody.innerText()).replace(/\s+/g, ' ').trim(), { timeout: 60_000 })
      .toBe(mateAnswer);
    const mateWindow = await assertTeamWindow(memberPage, teamId, chatId!, lines);
    const completedAssistants = mateWindow.filter((row) => row.role === 'assistant');
    expect(completedAssistants.length).toBeGreaterThanOrEqual(2);
    for (const row of completedAssistants) {
      expect(row.encrypted_content).toBeTruthy();
      expect(row.content).toBeUndefined();
    }
    expect(JSON.stringify(mateWindow)).not.toContain(mateAnswer);
    await expect.poll(async () => (await readTeamUsage(page, teamId!)).length, { timeout: 60_000 })
      .toBeGreaterThan(usageCountAfterAI);
    expect(await readTeamCredits(page, teamId)).toBeLessThan(teamCreditsAfterAI);
    expect(await readPersonalCredits(page)).toBe(personalCreditsBefore);
    expect(await readPersonalCredits(memberPage)).toBe(memberPersonalCreditsBefore);
    expect([...ownerFrames, ...memberFrames].filter((frame) => frame.direction === 'received' &&
      frame.type === 'error' && frame.payload.chat_id === chatId && /permission/i.test(String(frame.payload.message))))
      .toHaveLength(0);
  } catch (error) {
    runError = error;
  } finally {
    const ordinaryMessageIds = new Set(laterOrdinaryMessageIds);
    for (const [frames, end] of [[ownerFrames, ownerOrdinaryEnd], [memberFrames, memberOrdinaryEnd]] as const) {
      for (const frame of frames.slice(0, end ?? frames.length)) {
        if (frame.direction !== 'sent' || frame.type !== 'chat_message_added' || frame.payload.team_id !== teamId) continue;
        const messageId = proofId(frame.payload.message?.message_id ?? frame.payload.message_id);
        if (messageId) ordinaryMessageIds.add(messageId);
      }
    }
    const aiEvents = new Map<string, { stage: 'processing' | 'completed'; message_id: string | null; ai_task_id: string | null }>();
    for (const frame of [...ownerFrames, ...memberFrames]) {
      if (frame.direction !== 'received' || frame.payload.team_id !== teamId ||
          (frame.type !== 'team_ai_processing' && frame.type !== 'team_ai_response_completed')) continue;
      const stage = frame.type === 'team_ai_processing' ? 'processing' : 'completed';
      const messageId = proofId(frame.payload.message_id);
      const aiTaskId = proofId(frame.payload.ai_task_id ?? frame.payload.task_id);
      aiEvents.set(`${stage}:${messageId}:${aiTaskId}`, { stage, message_id: messageId, ai_task_id: aiTaskId });
    }
    try {
      // Retain only event metadata for relay diagnosis; never persist chat text,
      // ciphertext, invitation fragments, keys, or complete protocol payloads.
      const relevantTypes = new Set([
        'chat_message_added', 'chat_message_confirmed', 'team_chat_message_created',
        'chat_turn_preflight', 'team_ai_processing', 'team_ai_response_completed', 'error',
        'update_draft', 'delete_draft', 'draft_update_receipt', 'draft_delete_receipt',
        'chat_draft_updated', 'draft_deleted',
      ]);
      const protocolPath = testInfo.outputPath('team-chat-protocol-summary.json');
      const summaries = ([['owner', ownerFrames], ['member', memberFrames]] as const).flatMap(([actor, frames]) =>
        frames.filter((frame) => relevantTypes.has(frame.type)).map((frame) => ({
          actor,
          direction: frame.direction,
          type: frame.type,
          team_matches: frame.payload.team_id === teamId,
          chat_matches: (frame.payload.chat_id ?? frame.payload.chatId) === chatId,
          message_id: proofId(frame.payload.message?.message_id ?? frame.payload.message_id),
          role: frame.payload.message?.role ?? frame.payload.role ?? null,
          sender_hash_present: /^[0-9a-f]{64}$/.test(String(frame.payload.message?.hashed_user_id ?? frame.payload.hashed_user_id ?? '')),
          encrypted_content_present: Boolean(frame.payload.message?.encrypted_content ?? frame.payload.encrypted_content),
          ai_invocation_present: Boolean(frame.payload.team_ai_invocation ?? frame.payload.inference_request?.team_ai_invocation),
          error_kind: frame.type === 'error'
            ? (/permission/i.test(String(frame.payload.message)) ? 'permission' : 'other') : null,
        })),
      );
      await writeFile(protocolPath, JSON.stringify({ schema_version: 1, events: summaries }), { mode: 0o600, flag: 'wx' });
      await testInfo.attach('team-chat-protocol-summary.json', { path: protocolPath, contentType: 'application/json' });
      const idsPath = testInfo.outputPath('team-chat-private-proof-ids.json');
      await writeFile(idsPath, JSON.stringify({
        schema_version: 1,
        team_id: proofId(teamId),
        chat_id: proofId(chatId),
        ordinary_message_ids: [...ordinaryMessageIds],
        ai_events: [...aiEvents.values()],
      }), { mode: 0o600, flag: 'wx' });
      await testInfo.attach('team-chat-private-proof-ids.json', { path: idsPath, contentType: 'application/json' });
    } catch (error) { cleanupErrors.push(error instanceof Error ? error : new Error(String(error))); }
    if (teamId) {
      try {
        const deleted = await page.request.delete(`${API_URL}/v1/teams/${teamId}`);
        if (!deleted.ok()) cleanupErrors.push(new Error(`Fresh Team cleanup failed (${deleted.status()})`));
      } catch (error) { cleanupErrors.push(error instanceof Error ? error : new Error(String(error))); }
    }
    if (memberContext) {
      try { await memberContext.close(); }
      catch (error) { cleanupErrors.push(error instanceof Error ? error : new Error(String(error))); }
    }
    if (memberVideo) {
      try { await testInfo.attach('member-team-chat-video', { path: await memberVideo.path(), contentType: 'video/webm' }); }
      catch (error) { cleanupErrors.push(error instanceof Error ? error : new Error(String(error))); }
    }
    try { await page.close(); }
    catch (error) { cleanupErrors.push(error instanceof Error ? error : new Error(String(error))); }
    if (ownerVideo) {
      try { await testInfo.attach('owner-team-chat-video', { path: await ownerVideo.path(), contentType: 'video/webm' }); }
      catch (error) { cleanupErrors.push(error instanceof Error ? error : new Error(String(error))); }
    }
  }
  if (runError || cleanupErrors.length) {
    const primaryFailure = runError instanceof Error ? runError.message : String(runError ?? cleanupErrors[0]?.message);
    throw new AggregateError([...(runError ? [runError] : []), ...cleanupErrors],
      `Team chat proof, cleanup, or video capture failed: ${primaryFailure}`);
  }
});
