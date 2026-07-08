/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Web lifecycle notification suppression contract.
 *
 * Verifies the web app reports foreground/background visibility over the
 * existing WebSocket lifecycle channel. Backend assistant-completion push
 * suppression depends on this metadata: hidden tabs must not look like a
 * foreground viewer of the chat.
 */

const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test('web tab visibility sends lifecycle state for notification suppression', async ({ page }: { page: any }) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	test.slow();
	test.setTimeout(180000);

	const logStep = createSignupLogger('WEB_LIFECYCLE_NOTIFY');
	const takeScreenshot = createStepScreenshotter(logStep);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await page.addInitScript(() => {
		type LifecycleMessage = {
			is_foreground?: boolean;
			client_type?: string;
			source?: string;
		};

		const lifecycleMessages: LifecycleMessage[] = [];
		let visibilityState = 'visible';
		Object.defineProperty(document, 'visibilityState', {
			configurable: true,
			get: () => visibilityState
		});
		Object.defineProperty(document, 'hidden', {
			configurable: true,
			get: () => visibilityState !== 'visible'
		});

		(window as any).__openmatesLifecycleMessages = lifecycleMessages;
		(window as any).__setOpenMatesVisibilityState = (nextState: 'visible' | 'hidden') => {
			visibilityState = nextState;
			document.dispatchEvent(new Event('visibilitychange'));
		};

		const OriginalWebSocket = window.WebSocket;
		function WrappedWebSocket(this: WebSocket, url: string | URL, protocols?: string | string[]) {
			const socket = protocols === undefined ? new OriginalWebSocket(url) : new OriginalWebSocket(url, protocols);
			const originalSend = socket.send.bind(socket);
			socket.send = (data: string | ArrayBufferLike | Blob | ArrayBufferView) => {
				if (typeof data === 'string') {
					try {
						const parsed = JSON.parse(data);
						if (parsed?.type === 'native_client_lifecycle') {
							lifecycleMessages.push(parsed.payload ?? {});
						}
					} catch {
						// Non-JSON websocket payloads are unrelated to this contract.
					}
				}
				return originalSend(data);
			};
			return socket;
		}
		Object.setPrototypeOf(WrappedWebSocket, OriginalWebSocket);
		WrappedWebSocket.prototype = OriginalWebSocket.prototype;
		(window as any).WebSocket = WrappedWebSocket as unknown as typeof WebSocket;
	});

	await archiveExistingScreenshots(logStep);
	logStep('Starting web lifecycle notification suppression contract test.', { email: TEST_EMAIL });

	await loginToTestAccount(page, logStep, takeScreenshot);
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 20000 });
	await takeScreenshot(page, 'after-login');

	await page.waitForFunction(() => {
		return (window as any).__openmatesLifecycleMessages?.some(
			(message: any) => message.client_type === 'web' && message.is_foreground === true
		);
	}, { timeout: 20000 });
	logStep('Observed foreground lifecycle message from web client.');

	await page.evaluate(() => (window as any).__setOpenMatesVisibilityState('hidden'));
	await page.waitForFunction(() => {
		return (window as any).__openmatesLifecycleMessages?.some(
			(message: any) =>
				message.client_type === 'web' &&
				message.is_foreground === false &&
				message.source === 'visibilitychange'
		);
	}, { timeout: 10000 });
	logStep('Observed hidden lifecycle message from web client.');

	await page.evaluate(() => (window as any).__setOpenMatesVisibilityState('visible'));
	await page.waitForFunction(() => {
		return (window as any).__openmatesLifecycleMessages?.filter(
			(message: any) =>
				message.client_type === 'web' &&
				message.is_foreground === true &&
				message.source === 'visibilitychange'
		).length >= 1;
	}, { timeout: 10000 });
	logStep('Observed visible lifecycle message from web client.');

	const lifecycleMessages = await page.evaluate(() => (window as any).__openmatesLifecycleMessages);
	expect(lifecycleMessages).toEqual(
		expect.arrayContaining([
			expect.objectContaining({ client_type: 'web', is_foreground: false, source: 'visibilitychange' }),
			expect.objectContaining({ client_type: 'web', is_foreground: true, source: 'visibilitychange' })
		])
	);
});
