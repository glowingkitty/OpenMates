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
