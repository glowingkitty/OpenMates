/* eslint-disable @typescript-eslint/no-require-imports */
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
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const FIXTURE_PATH = path.resolve(
	__dirname,
	'../../../../shared/chat/fixtures/chat-response-lifecycle-v1.json'
);
const FIXTURE = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8')).cases[0];
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

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

async function seedFixtureChat(page: any): Promise<void> {
	await page.evaluate(async ({ fixture }) => {
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
				content: fixture.seed.user_content
			}]
		});
	}, { fixture: FIXTURE });
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

async function openFixtureChat(page: any): Promise<void> {
	const log = createSignupLogger('CHAT_RESPONSE_PROCESSING_UI');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'chat-response-processing-ui' });
	await loginToTestAccount(page, log, screenshot);
	await seedFixtureChat(page);
	await page.goto(getE2EDebugUrl(`/#chat-id=${FIXTURE.chat_id}`), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('message-user')).toContainText(FIXTURE.seed.user_content, {
		timeout: 20000
	});
}

test.describe('Assistant response processing rendered contract', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test.beforeEach(async ({ page }: { page: any }) => {
		await installLifecycleSocketHarness(page, FIXTURE.chat_id);
	});

	test('keeps rainbow, thinking, progressive answer, and cleanup on one assistant turn', async ({ page }: { page: any }) => {
		await openFixtureChat(page);
		const activeChat = page.getByTestId('active-chat-container');
		const initialBox = await activeChat.boundingBox();

		await emitStage(page, 'task-initiated');
		await emitStage(page, 'preprocessing');
		await emitStage(page, 'typing');
		await expect(activeChat).toHaveClass(/ai-typing/);

		const rainbow = await activeChat.evaluate((element: HTMLElement) => {
			const style = getComputedStyle(element, '::after');
			return {
				animationDuration: style.animationDuration,
				animationTimingFunction: style.animationTimingFunction,
				borderRadius: style.borderRadius,
				filter: style.filter,
				pointerEvents: style.pointerEvents
			};
		});
		expect(rainbow).toEqual({
			animationDuration: '3s',
			animationTimingFunction: 'linear',
			borderRadius: '17px',
			filter: 'blur(1.5px)',
			pointerEvents: 'none'
		});
		expect(await activeChat.boundingBox()).toEqual(initialBox);

		await emitStage(page, 'thinking-first');
		const assistant = page.getByTestId('message-assistant');
		await expect(assistant).toHaveCount(1);
		const thinking = assistant.getByTestId('thinking-section');
		await expect(thinking).toBeVisible();
		await expect(thinking).toContainText('inspect the fixture');

		await emitStage(page, 'thinking-second');
		await expect(thinking).toContainText('inspect the fixture');
		await expect(thinking).toContainText('select a safe answer');
		await expect(thinking.getByTestId('thinking-header')).toHaveAttribute('aria-expanded', 'true');

		await emitStage(page, 'thinking-complete');
		await emitStage(page, 'answer-first');
		await expect(assistant).toContainText('A deterministic');
		await emitStage(page, 'answer-rich');
		await expect(assistant).toHaveCount(1);
		await expect(assistant).toContainText('a synthetic link');

		await emitStage(page, 'final');
		await expect(activeChat).not.toHaveClass(/ai-typing/);
		await expect(page.getByTestId('typing-indicator')).toHaveCount(0);
		await expect(assistant).toHaveCount(1);
	});

	test('keeps processing state visible but static under reduced motion', async ({ page }: { page: any }) => {
		await page.emulateMedia({ reducedMotion: 'reduce' });
		await openFixtureChat(page);
		await emitStage(page, 'task-initiated');
		await emitStage(page, 'typing');

		const activeChat = page.getByTestId('active-chat-container');
		await expect(activeChat).toHaveClass(/ai-typing/);
		const rainbowAnimation = await activeChat.evaluate(
			(element: HTMLElement) => getComputedStyle(element, '::after').animationName
		);
		expect(rainbowAnimation).toBe('none');

		await emitStage(page, 'thinking-first');
		const thinkingContent = page.getByTestId('thinking-content');
		await expect(thinkingContent).toBeVisible();
		const motion = await thinkingContent.evaluate((element: HTMLElement) => ({
			animationName: getComputedStyle(element).animationName,
			scrollBehavior: getComputedStyle(element).scrollBehavior
		}));
		expect(motion.animationName).toBe('none');
		expect(motion.scrollBehavior).not.toBe('smooth');
	});
});
