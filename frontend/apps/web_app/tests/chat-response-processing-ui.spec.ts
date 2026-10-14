/* eslint-disable @typescript-eslint/no-require-imports */
const { waitForContextSyncComplete, openChatAfterContextSync } = require('./helpers/chat-hydration');
/**
 * Deterministic rendered contract for the complete assistant response lifecycle.
 * Synthetic events enter through the real browser WebSocket handler chain while
 * fixture-chat outbound traffic is suppressed to avoid shared backend storage.
 * The same staged JSON is consumed by Apple parity tests.
 */
export {};

const fs = require('fs');
const path = require('path');
const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createSignupLogger,
	createStepScreenshotter,
	getE2EDebugUrl,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');

const FIXTURE_PATH = path.resolve(
	__dirname,
	'../../../../shared/chat/fixtures/chat-response-lifecycle-v1.json'
);
const FIXTURE = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8')).cases[0];
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Idle chat processing feedback', () => {
	// contract-test: direct surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance,chat-processing-feedback.turn-lifecycle
	test('does not select a mate before a guest sends a message, including after reload', async ({ page }: { page: any }) => {
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-editor')).toBeVisible();
		await expect(page.getByTestId('typing-indicator')).toHaveCount(0);
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-editor')).toBeVisible();
		await expect(page.getByTestId('typing-indicator')).toHaveCount(0);
	});
});

async function installLifecycleSocketHarness(page: any, fixtureChatId: string): Promise<void> {
	await page.context().addInitScript(({ chatId }) => {
		const NativeWebSocket = window.WebSocket;
		let activeSocket: WebSocket | null = null;

		function FixtureWebSocket(this: WebSocket, ...args: ConstructorParameters<typeof WebSocket>) {
			const socket = new NativeWebSocket(...args);
			activeSocket = socket;
			const nativeSend = socket.send.bind(socket);

			socket.send = (data: string | ArrayBufferLike | Blob | ArrayBufferView) => {
				if (typeof data === 'string') {
					try {
						const message = JSON.parse(data);
						if (message?.payload?.chat_id === chatId || message?.payload?.chatId === chatId) {
							return;
						}
					} catch {
						// Preserve non-JSON frames for the real connection.
					}
				}
				nativeSend(data);
			};

			return socket;
		}

		Object.setPrototypeOf(FixtureWebSocket, NativeWebSocket);
		FixtureWebSocket.prototype = NativeWebSocket.prototype;
		Object.defineProperty(window, 'WebSocket', {
			configurable: true,
			writable: true,
			value: FixtureWebSocket as typeof WebSocket
		});

		(window as any).__openmatesE2ELifecycle = {
			emit(type: string, payload: Record<string, unknown>) {
				if (!activeSocket) throw new Error('No active WebSocket for lifecycle fixture');
				activeSocket.dispatchEvent(
					new MessageEvent('message', { data: JSON.stringify({ type, payload }) })
				);
			}
		};
	}, { chatId: fixtureChatId });
}

async function seedFixtureChat(page: any, userContent = FIXTURE.seed.user_content): Promise<void> {
	await page.evaluate(async ({ fixture, content }) => {
		const seedChat = (window as any).__openmatesE2ESeedChat;
		if (!seedChat) throw new Error('E2E chat seed helper is unavailable');
		const now = Math.floor(Date.now() / 1000);
		await seedChat({
			chat: {
				chat_id: fixture.chat_id,
				title: fixture.seed.title,
				messages_v: 1,
				title_v: 1,
				created_at: now,
				updated_at: now,
				last_edited_overall_timestamp: now
			},
			messages: [{
				message_id: fixture.user_message_id,
				chat_id: fixture.chat_id,
				role: 'user',
				created_at: now,
				status: 'synced',
				content
			}]
		});
	}, { fixture: FIXTURE, content: userContent });
}

async function emitStage(page: any, stageId: string): Promise<void> {
	const stage = FIXTURE.stages.find((candidate: any) => candidate.id === stageId);
	if (!stage) throw new Error(`Unknown lifecycle fixture stage: ${stageId}`);
	await page.evaluate(({ events }) => {
		const lifecycle = (window as any).__openmatesE2ELifecycle;
		if (!lifecycle) throw new Error('Lifecycle socket harness is unavailable');
		for (const event of events) lifecycle.emit(event.type, event.payload);
	}, { events: stage.events });
}

async function openFixtureChat(page: any, userContent = FIXTURE.seed.user_content): Promise<void> {
	const log = createSignupLogger('CHAT_RESPONSE_PROCESSING_UI');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'chat-response-processing-ui' });
	await loginToTestAccount(page, log, screenshot);
	await waitForContextSyncComplete(page, test.info());
	await seedFixtureChat(page, userContent);
	await openChatAfterContextSync(page, FIXTURE.chat_id, test.info());
	await waitForChatReady(page, log);
	await expect(page.getByTestId('message-user')).toContainText(userContent.replace('@mate:software_development', '@sophia'), {
		timeout: 20000
	});
}

test.describe('Assistant response processing rendered contract', () => {
  test.describe.configure({ timeout: 180000 });
  skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

  test.beforeEach(async ({ page }: { page: any }) => {
    await installLifecycleSocketHarness(page, FIXTURE.chat_id);
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance,chat-processing-feedback.selected-mate-identity,chat-processing-feedback.response-container-glow
  test('opens one transient Thinking response only after the identified Mate is confirmed', async ({ page }: { page: any }) => {
    await openFixtureChat(page);
    await expect(page.getByTestId('pending-assistant-response')).toHaveCount(0);
    await emitStage(page, 'task-initiated');
    const pending = page.getByTestId('pending-assistant-response');
    await expect(pending).toHaveCount(0);
    await expect(page.getByTestId('assistant-transient-thinking')).toHaveCount(0);
    await expect(page.getByTestId('typing-indicator')).toHaveCount(0);
    await expect(page.getByTestId('chat-history-content')).toHaveAttribute('data-source-message-count', '1');

    await page.evaluate(({ fixture }) => {
      const lifecycle = (window as any).__openmatesE2ELifecycle;
      lifecycle.emit('preprocessing_step', {
        chat_id: fixture.chat_id, step: 'mate_selected', skipped: false,
        data: { mate_id: 'software_development', mate_name: 'Sophia', mate_category: 'software_development' }
      });
    }, { fixture: FIXTURE });
    await expect(pending).toHaveCount(0);
    await page.evaluate(({ fixture }) => {
      const lifecycle = (window as any).__openmatesE2ELifecycle;
      lifecycle.emit('preprocessing_step', {
        chat_id: fixture.chat_id, step: 'model_selected', skipped: false,
        data: { model_name: 'Synthetic Reasoning Model', provider_name: 'Synthetic Provider', server_region: 'EU' }
      });
    }, { fixture: FIXTURE });
    await expect(pending).toHaveCount(0);
    await page.evaluate(({ fixture }) => {
      const lifecycle = (window as any).__openmatesE2ELifecycle;
      lifecycle.emit('ai_typing_started', {
        chat_id: fixture.chat_id, message_id: fixture.task_id, task_id: fixture.task_id,
        user_message_id: fixture.user_message_id, category: 'software_development',
        model_name: 'Synthetic Reasoning Model', provider_name: 'Synthetic Provider', server_region: 'EU'
      });
    }, { fixture: FIXTURE });
    await expect(pending).toBeVisible();
    await expect(pending.getByTestId('assistant-transient-thinking')).toContainText('Thinking');
    await expect(pending.getByTestId('chat-mate-name')).toHaveText('Sophia');
    await expect(pending.getByTestId('generated-by-container')).toContainText('Synthetic Reasoning Model');
    await expect(pending.getByTestId('generated-by-container')).toContainText('🇪🇺');
    await emitStage(page, 'task-initiated');
    await expect(pending).toHaveCount(1);
    await expect(pending.getByTestId('chat-mate-name')).toHaveText('Sophia');

    await page.evaluate(({ fixture }) => {
      const lifecycle = (window as any).__openmatesE2ELifecycle;
      lifecycle.emit('ai_message_ready', { chat_id: fixture.chat_id, message_id: fixture.task_id });
      lifecycle.emit('ai_typing_ended', {
        chat_id: fixture.chat_id, message_id: fixture.task_id, user_message_id: fixture.user_message_id
      });
    }, { fixture: FIXTURE });
    await expect(pending).toHaveCount(0);
    await expect(page.getByTestId('message-assistant')).toHaveCount(0);
    await emitStage(page, 'task-initiated');
    await expect(pending).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.selected-mate-identity,chat-processing-feedback.selection-after-acceptance
  test('keeps an explicitly selected Mate in the accepted response', async ({ page }: { page: any }) => {
    await openFixtureChat(page, '@mate:software_development Please review this deterministic fixture.');
    await emitStage(page, 'task-initiated');
    const pending = page.getByTestId('pending-assistant-response');
    await expect(pending).toHaveCount(0);
    await page.evaluate(({ fixture }) => {
      (window as any).__openmatesE2ELifecycle.emit('preprocessing_step', {
        chat_id: fixture.chat_id, step: 'mate_selected', skipped: true,
        skip_reason: 'user_override',
        data: { mate_id: 'software_development', mate_name: 'Sophia', mate_category: 'software_development' }
      });
    }, { fixture: FIXTURE });
    await expect(pending).toHaveCount(0);
    await page.evaluate(({ fixture }) => {
      (window as any).__openmatesE2ELifecycle.emit('ai_typing_started', {
        chat_id: fixture.chat_id, message_id: fixture.task_id, task_id: fixture.task_id,
        user_message_id: fixture.user_message_id, category: 'software_development',
        model_name: 'Synthetic Reasoning Model', provider_name: 'Synthetic Provider', server_region: 'EU'
      });
    }, { fixture: FIXTURE });
    await expect(pending.getByTestId('chat-mate-name')).toHaveText('Sophia');
    await expect(page.getByTestId('typing-indicator')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.selected-mate-identity,chat-processing-feedback.turn-lifecycle
  test('uses turn-identified typing when task initiation is late and ignores unfenced selection', async ({ page }: { page: any }) => {
    await openFixtureChat(page);
    const pending = page.getByTestId('pending-assistant-response');
    await page.evaluate(({ fixture }) => {
      const lifecycle = (window as any).__openmatesE2ELifecycle;
      lifecycle.emit('preprocessing_step', {
        chat_id: fixture.chat_id, step: 'mate_selected', skipped: false,
        data: { mate_id: 'general_knowledge', mate_name: 'Old Mate', mate_category: 'general_knowledge' }
      });
    }, { fixture: FIXTURE });
    await expect(pending).toHaveCount(0);
    await page.evaluate(({ fixture }) => {
      (window as any).__openmatesE2ELifecycle.emit('ai_typing_started', {
        chat_id: fixture.chat_id, message_id: fixture.task_id, task_id: fixture.task_id,
        user_message_id: fixture.user_message_id, category: 'software_development',
        model_name: 'Synthetic Reasoning Model', provider_name: 'Synthetic Provider', server_region: 'EU'
      });
    }, { fixture: FIXTURE });
    await expect(pending.getByTestId('chat-mate-name')).toHaveText('Sophia');
    await expect(pending.getByTestId('generated-by-container')).toContainText('Synthetic Reasoning Model');
    await emitStage(page, 'task-initiated');
    await expect(pending).toHaveCount(1);
    await expect(pending.getByTestId('chat-mate-name')).toHaveText('Sophia');
    await page.evaluate(({ fixture }) => {
      (window as any).__openmatesE2ELifecycle.emit('preprocessing_step', {
        chat_id: fixture.chat_id, step: 'mate_selected', skipped: false,
        data: { mate_id: 'general_knowledge', mate_name: 'Old Mate', mate_category: 'general_knowledge' }
      });
    }, { fixture: FIXTURE });
    await expect(pending.getByTestId('chat-mate-name')).toHaveText('Sophia');
    await page.evaluate(({ fixture }) => {
      (window as any).__openmatesE2ELifecycle.emit('ai_message_update', {
        type: 'ai_message_chunk', chat_id: fixture.chat_id, task_id: fixture.task_id,
        message_id: fixture.assistant_message_id, user_message_id: fixture.user_message_id,
        sequence: 1, full_content_so_far: 'Finished after late initiation.',
        is_final_chunk: true, category: 'ai', model_name: 'Synthetic Reasoning Model'
      });
    }, { fixture: FIXTURE });
    const assistant = page.getByTestId('message-assistant');
    await expect(assistant).toContainText('Finished after late initiation.');
    await expect(assistant.getByTestId('mate-message-content')).not.toHaveClass(/assistant-response-active/);
    await emitStage(page, 'task-initiated');
    await expect(pending).toHaveCount(0);
    await expect(assistant.getByTestId('mate-message-content')).not.toHaveClass(/assistant-response-active/);
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle,chat-processing-feedback.response-container-glow
  test('hands the transient slot to one streamed assistant response and clears its glow', async ({ page }: { page: any }) => {
    await openFixtureChat(page);
    const activeChat = page.getByTestId('active-chat-container');
    await emitStage(page, 'task-initiated');
    const pending = page.getByTestId('pending-assistant-response');
    await expect(pending).toHaveCount(0);
    await emitStage(page, 'preprocessing');
    await expect(pending).toHaveCount(0);
    await emitStage(page, 'typing');
    await expect(pending).toBeVisible();
    await expect(activeChat).not.toHaveClass(/ai-typing/);
    await emitStage(page, 'thinking-first');
    const assistant = page.getByTestId('message-assistant');
    await expect(assistant).toHaveCount(1);
    await expect(pending).toHaveCount(0);
    await expect(assistant.getByTestId('assistant-response-thinking')).toContainText('inspect the fixture');
    await expect(assistant.getByTestId('mate-message-content')).toHaveClass(/assistant-response-active/);
    await emitStage(page, 'thinking-second');
    await expect(assistant.getByTestId('assistant-response-thinking')).toContainText('select a safe answer');
    await emitStage(page, 'thinking-complete');
    await emitStage(page, 'answer-first');
    await expect(assistant).toContainText('A deterministic');
    await expect(assistant.getByTestId('assistant-response-status')).toContainText('Working');
    await emitStage(page, 'answer-rich');
    await expect(assistant).toHaveCount(1);
    await expect(assistant).toContainText('a synthetic link');
    await emitStage(page, 'final');
    await expect(assistant.getByTestId('mate-message-content')).not.toHaveClass(/assistant-response-active/);
    await expect(assistant.getByTestId('assistant-activity-toggle')).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('typing-indicator')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=chats.completion.independent-metadata,chat-processing-feedback.turn-lifecycle
  test('finishes the response before optional metadata and accepts late chips without replacing the draft', async ({ page }: { page: any }) => {
    await openFixtureChat(page);
    await emitStage(page, 'task-initiated');
    await emitStage(page, 'preprocessing');
    await emitStage(page, 'typing');
    await emitStage(page, 'answer-first');
    await emitStage(page, 'final');
    const assistant = page.getByTestId('message-assistant');
    await expect(assistant.getByTestId('mate-message-content')).not.toHaveClass(/assistant-response-active/);
    await expect(page.getByTestId('pending-assistant-response')).toHaveCount(0);
    const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]');
    await editor.fill('Late');
    await page.evaluate(({ fixture }) => {
      (window as any).__openmatesE2ELifecycle.emit('post_processing_completed', {
        chat_id: fixture.chat_id, task_id: fixture.task_id, user_message_id: fixture.user_message_id,
        follow_up_request_suggestions: ['Late fixture follow-up'], new_chat_request_suggestions: [],
        chat_summary: 'The metadata arrived after the answer.', chat_tags: [], harmful_response: 0,
        updated_chat_title: 'Late metadata fixture title',
      });
    }, { fixture: FIXTURE });
    await expect(page.getByTestId('follow-up-suggestion-item').filter({ hasText: 'Late fixture follow-up' })).toBeVisible();
    await expect(page.getByTestId('chat-header-title')).toHaveText('Late metadata fixture title');
    await expect(editor).toHaveText('Late');
    await expect(assistant.getByTestId('mate-message-content')).not.toHaveClass(/assistant-response-active/);
    // A newer task owns subsequent suggestions even if the older job finishes last.
    await page.evaluate(({ fixture }) => {
      const harness = (window as any).__openmatesE2ELifecycle;
      harness.emit('ai_task_initiated', { chat_id: fixture.chat_id, ai_task_id: 'newer-task', user_message_id: 'newer-user', status: 'processing_started' });
      harness.emit('post_processing_completed', {
        chat_id: fixture.chat_id, task_id: fixture.task_id, user_message_id: fixture.user_message_id,
        follow_up_request_suggestions: ['Late stale chips'], new_chat_request_suggestions: [],
        chat_summary: '', chat_tags: [], harmful_response: 0,
        source_title_v: 2, updated_chat_title: 'Earlier turn arrived during the next turn',
      });
    }, { fixture: FIXTURE });
    await expect(page.getByTestId('chat-header-title')).toHaveText('Earlier turn arrived during the next turn');
    await expect(page.getByTestId('follow-up-suggestion-item').filter({ hasText: 'Late stale chips' })).toHaveCount(0);
    await expect(editor).toHaveText('Late');
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.accessible-responsive,chat-processing-feedback.response-container-glow
  test('keeps the response glow static under reduced motion', async ({ page }: { page: any }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openFixtureChat(page);
    await emitStage(page, 'task-initiated');
    await emitStage(page, 'preprocessing');
    await emitStage(page, 'typing');
    const response = page.getByTestId('pending-assistant-response').getByTestId('mate-message-content');
    await expect(response).toBeVisible();
    expect(await response.evaluate((element: HTMLElement) => getComputedStyle(element, '::after').animationName)).toBe('none');
    await expect(page.getByTestId('active-chat-container')).not.toHaveClass(/ai-typing/);
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle,chat-processing-feedback.response-container-glow
  test('keeps interim skill continuation active until the terminal final', async ({ page }: { page: any }) => {
    await openFixtureChat(page);
    await emitStage(page, 'task-initiated');
    await emitStage(page, 'preprocessing');
    await emitStage(page, 'typing');
    await emitStage(page, 'answer-first');
    const assistant = page.getByTestId('message-assistant');
    const bubble = assistant.getByTestId('mate-message-content');
    await expect(bubble).toHaveClass(/assistant-response-active/);
    await page.evaluate(({ fixture }) => {
      (window as any).__openmatesE2ELifecycle.emit('ai_message_update', {
        type: 'ai_message_chunk', chat_id: fixture.chat_id, task_id: fixture.task_id,
        message_id: fixture.assistant_message_id, user_message_id: fixture.user_message_id,
        sequence: 2, full_content_so_far: 'A deterministic **answer**',
        is_final_chunk: true, awaiting_async_skill_continuation: true,
        category: 'ai', model_name: 'Synthetic Reasoning Model'
      });
    }, { fixture: FIXTURE });
    await expect(assistant).toHaveAttribute('data-status', 'streaming');
    await expect(bubble).toHaveClass(/assistant-response-active/);
    await expect(assistant.getByTestId('using-model')).toBeVisible();
    await expect(assistant.getByTestId('generated-by')).toHaveCount(0);
    await page.evaluate(({ fixture }) => {
      (window as any).__openmatesE2ELifecycle.emit('ai_message_update', {
        type: 'ai_message_chunk', chat_id: fixture.chat_id, task_id: fixture.task_id,
        message_id: fixture.assistant_message_id, user_message_id: fixture.user_message_id,
        sequence: 3, full_content_so_far: 'A deterministic **answer** continues.',
        is_final_chunk: false, category: 'ai', model_name: 'Synthetic Reasoning Model'
      });
    }, { fixture: FIXTURE });
    await expect(assistant).toContainText('continues');
    await expect(bubble).toHaveClass(/assistant-response-active/);
    await page.evaluate(({ fixture }) => {
      (window as any).__openmatesE2ELifecycle.emit('ai_message_update', {
        type: 'ai_message_chunk', chat_id: fixture.chat_id, task_id: fixture.task_id,
        message_id: fixture.assistant_message_id, user_message_id: fixture.user_message_id,
        sequence: 4, full_content_so_far: 'A deterministic **answer** continues.',
        is_final_chunk: true, category: 'ai', model_name: 'Synthetic Reasoning Model'
      });
    }, { fixture: FIXTURE });
    await expect(bubble).not.toHaveClass(/assistant-response-active/);
    await expect(assistant.getByTestId('generated-by')).toBeVisible();
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  test('shows a terminal inference failure instead of an empty completed turn', async ({ page }: { page: any }) => {
    await openFixtureChat(page);
    await emitStage(page, 'task-initiated');
    await emitStage(page, 'typing');
    const errorText = 'The AI service encountered an error while processing your request. Please try again in a moment.';
    await page.evaluate(({ fixture, error }) => {
      const lifecycle = (window as any).__openmatesE2ELifecycle;
      const payload = { chat_id: fixture.chat_id, task_id: fixture.task_id,
        message_id: fixture.assistant_message_id, user_message_id: fixture.user_message_id };
      lifecycle.emit('ai_message_update', { ...payload, type: 'ai_message_chunk', sequence: 1,
        full_content_so_far: error, is_final_chunk: true, category: 'ai' });
      lifecycle.emit('ai_message_ready', { chat_id: fixture.chat_id, message_id: fixture.assistant_message_id });
      lifecycle.emit('ai_typing_ended', { chat_id: fixture.chat_id, message_id: fixture.assistant_message_id });
    }, { fixture: FIXTURE, error: errorText });
    await expect(page.getByTestId('message-assistant')).toHaveCount(1);
    await expect(page.getByTestId('message-assistant')).toContainText(errorText);
    await expect(page.getByTestId('pending-assistant-response')).toHaveCount(0);
  });
});
