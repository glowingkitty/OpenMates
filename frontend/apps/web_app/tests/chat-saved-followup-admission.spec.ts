/* eslint-disable @typescript-eslint/no-require-imports */
/** Same completed-follow-up regression, isolated for short debugging loops. */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { createSignupLogger, createStepScreenshotter, archiveExistingScreenshots,
  getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

/**
 * Shared login helper: navigates to home, logs in with email/password/OTP,
 * waits for /chat redirect, and clicks "New Chat" if available.
 */
async function loginAndNavigateToChat(
	page: any,
	testInstance: any,
	logPrefix: string
): Promise<{
	logCheckpoint: (msg: string, meta?: Record<string, unknown>) => void;
	takeStepScreenshot: (page: any, label: string) => Promise<void>;
}> {
	const logCheckpoint = createSignupLogger(logPrefix);
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	testInstance.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	testInstance.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	testInstance.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);

	logCheckpoint('Logging in via loginToTestAccount (includes OTP retry with clock-drift compensation).');
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);

	await startNewChat(page, logCheckpoint);

	return { logCheckpoint, takeStepScreenshot };
}

/**
 * Helper: send a message in the chat editor and return the chat ID from URL.
 */
async function sendMessageAndGetChatId(
	page: any,
	message: string,
	logCheckpoint: (msg: string, meta?: Record<string, unknown>) => void
): Promise<string> {
	await sendMessage(page, message, logCheckpoint);

	// Wait for chat ID to appear in URL
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const urlAfterSend = page.url();
	const chatIdMatch = urlAfterSend.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	logCheckpoint(`Chat ID: ${chatId}`, { chatId });
	return chatId;
}

// contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
test('saved Personal follow-up admits full history before phased routing and details', async ({ page }: { page: any }, testInfo: any) => {
  test.setTimeout(180000);
  const events: Array<Record<string, any>> = [];
  const jobChats = new Map<string, string>();
  page.on('websocket', (socket: any) => {
    const capture = (direction: string) => (frame: any) => {
      try {
        const parsed = JSON.parse(String(frame.payload));
        const body = parsed.payload ?? {};
        if (direction === 'sent' && parsed.type === 'recovery_job_persist') {
          jobChats.set(body.job_id, body.encrypted_assistant_message?.chat_id);
        }
        const request = body.inference_request;
        events.push({ direction, type: parsed.type, turnId: body.turn_id,
          chatId: body.chat_id ?? jobChats.get(body.job_id), messageId: parsed.type === 'ai_message_update' ? body.user_message_id : body.message_id ?? body.user_message_id,
          expected: body.expected_messages_v, committed: body.committed_messages_v,
          phase: body.phase, state: body.state, status: body.status, contextPending: request?.client_context_pending,
          metadataIncluded: body.encrypted_chat_metadata !== undefined, code: body.code,
          historyIds: request?.message_history?.map((row: any) => row.message_id),
          historyRoles: request?.message_history?.map((row: any) => row.role) });
      } catch { /* Ignore non-JSON control frames. */ }
    };
    socket.on('framesent', capture('sent')); socket.on('framereceived', capture('received'));
  });
  try {
  const { logCheckpoint } = await loginAndNavigateToChat(page, test, 'SAVED_FOLLOWUP_PHASES');
  const chatId = await sendMessageAndGetChatId(page,
    withMockMarker('What is the capital?', 'chat_flow_capital'), logCheckpoint);
  await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 90000 });
  const terminal = () => events.find(event => event.direction === 'received'
    && event.type === 'recovery_job_persisted' && event.chatId === chatId && event.state === 'TERMINAL'
    && Number.isSafeInteger(event.committed));
  await expect.poll(terminal, { timeout: 90000 }).toBeTruthy();
  const canonicalVersion = terminal()!.committed;
  const first = events.find(event => event.direction === 'sent' && event.type === 'chat_turn_admit' && event.chatId === chatId);
  expect(first?.expected).toBe(0);
  expect(canonicalVersion).toBeGreaterThan(0);
  // The composer increments the local counter when saving its optimistic user
  // row: zero here deliberately becomes stale messages_v=1 in the sender.
  await page.evaluate(async (id: string) => {
    await new Promise<void>((resolve, reject) => {
      const open = indexedDB.open('chats_db');
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const db = open.result;
        const tx = db.transaction('chats', 'readwrite');
        const store = tx.objectStore('chats');
        const read = store.get(id);
        read.onsuccess = () => {
          if (!read.result) { tx.abort(); return; }
          store.put({ ...read.result, messages_v: 0 });
        };
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror = () => { db.close(); reject(tx.error); };
        tx.onabort = () => { db.close(); reject(new Error('Stale local version fixture failed')); };
      };
    });
  }, chatId);
  await sendMessage(page, withMockMarker('And the next capital?', 'chat_flow_capital'), logCheckpoint);
  const followup = () => events.find(event => event.direction === 'sent' && event.type === 'chat_turn_admit'
    && event.chatId === chatId && event.messageId !== first?.messageId);
  await expect.poll(followup, { timeout: 30000 }).toBeTruthy();
  const admitted = followup()!;
  expect(admitted.expected).toBe(canonicalVersion);
  expect(admitted.metadataIncluded).toBe(false);
  await expect.poll(() => events.filter(event => event.direction === 'received'
    && event.type === 'chat_turn_preflight_ack' && event.turnId === admitted.turnId).length,
    { timeout: 30000 }).toBe(1);
  expect(admitted.contextPending).toBe(true);
  expect(admitted.historyIds).toContain(first!.messageId);
  expect(admitted.historyRoles).toContain('assistant');
  expect(admitted.historyIds).toContain(admitted.messageId);
  await expect(page.getByTestId('message-assistant')).toHaveCount(2, { timeout: 90000 });
  expect(events.filter(event => event.direction === 'received' && event.type === 'error')).toEqual([]);
  expect(events.some(event => event.direction === 'received' && event.type === 'chat_message_confirmed'
    && event.messageId === admitted.messageId)).toBe(true);
  const admissionIndex = events.indexOf(admitted);
  const routingIndex = events.findIndex(event => event.direction === 'sent' && event.type === 'chat_turn_context_ready'
    && event.turnId === admitted.turnId && event.phase === 'routing');
  const detailsIndex = events.findIndex(event => event.direction === 'sent' && event.type === 'chat_turn_context_ready'
    && event.turnId === admitted.turnId && event.phase === 'details');
  expect(routingIndex).toBeGreaterThan(admissionIndex);
  expect(detailsIndex).toBeGreaterThan(routingIndex);
  await expect.poll(() => events.findIndex(event => event.direction === 'received' && event.type === 'chat_turn_context_ack'
    && event.turnId === admitted.turnId && event.phase === 'details' && event.status === 'accepted'),
    { timeout: 30000 }).toBeGreaterThan(detailsIndex);
  expect(events.findIndex(event => event.direction === 'received' && event.type === 'ai_message_update'
    && event.messageId === admitted.messageId)).toBeGreaterThan(detailsIndex);
  expect(events.some(event => event.direction === 'sent' && ['chat_message_added', 'chat_turn_preflight'].includes(event.type)
    && event.messageId === admitted.messageId)).toBe(false);
  } finally {
    await testInfo.attach('saved-followup-admission-protocol', {
      body: JSON.stringify(events.slice(-160)), contentType: 'application/json',
    });
  }
});

// contract-test: direct surface=gui.web assertions=chats.completion.recovery-takeover,chats.completion.lease-fenced,chats.message.identity-idempotent,chats.send.immediate-admission
test('reload restores a leased completed reply before admitting the question-mark follow-up and survives a cold login', async ({ page, browser }: { page: any; browser: any }, testInfo: any) => {
  test.setTimeout(300000);
  const events: Array<Record<string, any>> = [];
  const admissions: Array<Record<string, any>> = [];
  const admittedIds = new Set<string>();
  let reloaded = false;
  let seedAssistantId = '';
  let held: Record<string, any> | null = null;
  let coldContext: any = null;
  let coldPage: any = null;
  await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, (socket: any) => {
    const server = socket.connectToServer();
    const capture = (direction: string, raw: unknown) => {
      try {
        const frame = JSON.parse(String(raw)), body = frame.payload ?? {};
        const event = { direction, type: frame.type, jobId: body.job_id, state: body.state, requestId: body.request_id,
          turnId: body.turn_id, messageId: body.message_id, committed: body.committed_messages_v,
          pendingIds: body.pending_jobs?.map((job: any) => job.job_id),
          historyIds: body.inference_request?.message_history?.map((row: any) => row.message_id),
          expected: body.expected_messages_v };
        events.push(event);
        if (direction === 'sent' && ['chat_turn_admit', 'chat_turn_preflight'].includes(frame.type)
          && typeof body.message_id === 'string' && !admittedIds.has(body.message_id)) {
          admittedIds.add(body.message_id);
          admissions.push({ ...event, eventIndex: events.length - 1 });
        }
        return frame;
      } catch { return null; }
    };
    socket.onMessage((raw: unknown) => {
      const frame = capture('sent', raw);
      const body = frame?.payload ?? {};
      if (!reloaded && admissions.length === 2 && frame?.type === 'recovery_job_persist'
        && body.encrypted_assistant_message?.client_message_id !== seedAssistantId) {
        held = { jobId: body.job_id, assistantId: body.encrypted_assistant_message.client_message_id };
        return; // The old connection holds a real lease but misses its terminal write.
      }
      server.send(raw);
    });
    server.onMessage((raw: unknown) => {
      const frame = capture('received', raw);
      if (!reloaded && frame?.type === 'ai_message_update'
        && frame.payload?.user_message_id === admissions[1]?.messageId) return;
      socket.send(raw);
    });
  });
  try {
    const { logCheckpoint } = await loginAndNavigateToChat(page, test, 'RELOADED_FOLLOWUP');
    const chatId = await sendMessageAndGetChatId(page,
      withMockMarker('Seed the existing conversation.', 'chat_flow_capital'), logCheckpoint);
    await expect.poll(() => events.some(event => event.direction === 'received'
      && event.type === 'recovery_job_persisted' && event.state === 'TERMINAL'), { timeout: 90000 }).toBe(true);
    seedAssistantId = await page.getByTestId('message-assistant').first().getAttribute('data-message-id');
    expect(seedAssistantId).toBeTruthy();
    await sendMessage(page, withMockMarker('A second request in this existing chat.', 'chat_flow_capital'), logCheckpoint);
    await expect(page.getByTestId('message-user')).toHaveCount(2);
    await expect.poll(() => held, { timeout: 90000 }).toBeTruthy();
    expect(admissions).toHaveLength(2);
    reloaded = true;
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('message-user')).toHaveCount(2, { timeout: 30000 });
    await expect(page.getByTestId('message-assistant')).toHaveCount(1);
    const followupStart = events.length;
    // Observe the optimistic phase before acceptance: the old connection's
    // real lease must keep this turn pending until recovery finishes.
    await sendMessage(page, withMockMarker('?', 'chat_flow_capital'), logCheckpoint,
      undefined, 'pending-followup', { waitUntil: 'visible' });
    await expect(page.getByTestId('message-user')).toHaveCount(3);
    await expect(page.getByTestId('message-user').last()).toHaveAttribute('data-status', 'sending');
    await expect.poll(() => events.slice(followupStart).some(event => event.direction === 'received'
      && event.type === 'recovery_jobs_available' && event.pendingIds?.includes(held!.jobId)),
      { timeout: 15000 }).toBe(true);
    expect(admissions, 'The live old lease must prevent another inference with incomplete history').toHaveLength(2);
    await expect.poll(() => admissions.length, { timeout: 120000 }).toBe(3);
    const recoveredAckIndex = events.findIndex(event => event.direction === 'received'
      && event.type === 'recovery_job_persisted' && event.jobId === held!.jobId && event.state === 'TERMINAL');
    expect(recoveredAckIndex).toBeGreaterThan(followupStart);
    expect(admissions[2].eventIndex).toBeGreaterThan(recoveredAckIndex);
    expect(admissions[2].historyIds).toContain(held!.assistantId);
    expect(admissions[2].historyIds).toContain(seedAssistantId);
    expect(admissions[2].expected).toBe(events[recoveredAckIndex].committed);
    await expect(page.getByTestId('message-assistant')).toHaveCount(3, { timeout: 90000 });
    await expect.poll(() => events.filter(event => event.direction === 'received'
      && event.type === 'recovery_job_persisted' && event.state === 'TERMINAL').length,
      { timeout: 90000 }).toBeGreaterThanOrEqual(3);
    const originalOrder = await page.locator('[data-testid="message-user"], [data-testid="message-assistant"]').evaluateAll((nodes: Element[]) =>
      nodes.map(node => node.getAttribute('data-message-id')));
    expect(originalOrder.indexOf(held!.assistantId)).toBeLessThan(originalOrder.indexOf(admissions[2].messageId));
    expect(originalOrder.filter((id: string) => id === held!.assistantId)).toHaveLength(1);
    await testInfo.attach('recovered-before-followup', { body: await page.screenshot(), contentType: 'image/png' });

    const baseURL = new URL(page.url()).origin;
    coldContext = await browser.newContext({ baseURL, viewport: { width: 1280, height: 900 },
      storageState: { cookies: [], origins: [] }, recordVideo: { dir: testInfo.outputPath('cold-login-video') } });
    coldPage = await coldContext.newPage();
    await loginToTestAccount(coldPage, logCheckpoint, async () => {});
    const { getE2EDebugUrl } = require('./signup-flow-helpers');
    await coldPage.goto(getE2EDebugUrl(`/#chat-id=${chatId}`), { waitUntil: 'domcontentloaded' });
    await expect(coldPage.getByTestId('message-assistant')).toHaveCount(3, { timeout: 90000 });
    await expect(coldPage.getByTestId('message-user')).toHaveCount(3);
    const coldOrder = await coldPage.locator('[data-testid="message-user"], [data-testid="message-assistant"]').evaluateAll((nodes: Element[]) =>
      nodes.map(node => node.getAttribute('data-message-id')));
    expect(coldOrder).toEqual(originalOrder);
    expect(admissions).toHaveLength(3);
  } finally {
    if (coldContext) {
      const video = coldPage?.video();
      await coldContext.close();
      if (video) await testInfo.attach('cold-login-retains-response-order', { path: await video.path(), contentType: 'video/webm' });
    }
    await testInfo.attach('reload-followup-protocol', { body: JSON.stringify(events), contentType: 'application/json' });
  }
});
