// proof-video: not_required reason=visual_smoke_not_needed
/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: pii-placeholder-substitution
export {};

/**
 * A send waits for the local name and address detector, however slow the device.
 *
 * Owner decision 2026-11-20 (TASK-6594): while the detector is still working the
 * message waits and is sent only once personal data is replaced; when the
 * detector fails the message is not sent and the user sees a short notice to
 * try again. A CPU-only browser used to miss the 2.5 s scan budget and send the
 * name and the street address as written.
 *
 * The real model runs in the browser. Its worker is served with a short prefix
 * that delays (or fails) every model reply, so slowness is deterministic:
 * - slow: every model reply waits SLOW_REPLY_MS; the send must still carry
 *   placeholders for name, address, email and phone, and nothing raw leaves.
 * - failing: scan replies are errors; nothing is sent, the notice appears and
 *   the draft stays in the composer.
 * - fast: no delay; after a first (cold) send the second send leaves within seconds.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, deleteActiveChat, fillMessageEditor } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const WORKER = '/pii-runtime/redact-4.1.0-litert-2.6.0/worker.js';
const PREVIEW_BUDGET_MS = 2_500;
const SLOW_REPLY_MS = 4_000;
// Synthetic co-speaker; none of these strings may leave the browser raw.
const RAW_PERSONAL_DATA = ['Jonas', 'Albrecht', 'Lindenstrasse', 'jonas.albrecht@example.org', '23456789'];
const MESSAGE =
	"Please help me polish this talk proposal. Talk proposal draft: 'Private by default: building an AI " +
	"assistant that never sees your secrets'. Speakers: me and my co-speaker Jonas Albrecht " +
	'(jonas.albrecht@example.org, +49 151 23456789, Lindenstrasse 12, 10969 Berlin). Length: 25 minutes plus Q&A.';

const FOLLOW_UP =
	'Also draft a short bio for my co-speaker Jonas Albrecht (jonas.albrecht@example.org, +49 151 23456789, ' +
	'Lindenstrasse 12, 10969 Berlin) for the same proposal.';

type DetectorMode = 'slow' | 'failing';

/** Worker prefix: tracks load/scan request ids and delays or fails their replies only. */
function detectorPrefix(mode: DetectorMode): string {
	return `(() => {
  const kinds = new Map();
  self.addEventListener('message', ({ data }) => {
    if (data && (data.kind === 'load' || data.kind === 'scan')) kinds.set(data.id, data.kind);
  });
  const post = self.postMessage.bind(self);
  self.postMessage = (message, transfer) => {
    const kind = message && typeof message === 'object' && !('kind' in message) ? kinds.get(message.id) : undefined;
    if (!kind) return transfer === undefined ? post(message) : post(message, transfer);
    const reply = ${mode === 'failing' ? "kind === 'scan' ? { id: message.id, error: true } : message" : 'message'};
    setTimeout(() => post(reply), ${mode === 'slow' ? SLOW_REPLY_MS : 0});
  };
})();
`;
}

async function serveDetector(page: any, mode: DetectorMode): Promise<void> {
	await page.route(`**${WORKER}`, async (route: any) => {
		const response = await route.fetch();
		await route.fulfill({ response, body: detectorPrefix(mode) + (await response.text()) });
	});
}

/** Every client→server text that could carry the message: WS frames and request bodies. */
function recordOutgoing(page: any) {
	const outgoing: string[] = [];
	const turns: Array<{ at: number; content: string }> = [];
	page.on('websocket', (socket: any) => {
		socket.on('framesent', ({ payload }: { payload: string }) => {
			const text = payload.toString();
			outgoing.push(text);
			try {
				const frame = JSON.parse(text);
				if (frame.type === 'chat_turn_admit' || frame.type === 'chat_turn_preflight') {
					const content = frame.payload?.inference_request?.message?.content;
					if (typeof content === 'string') turns.push({ at: Date.now(), content });
				}
			} catch { /* Non-JSON transport frames are unrelated. */ }
		});
	});
	page.on('request', (request: any) => {
		const body = request.postData();
		if (body) outgoing.push(body);
	});
	return { outgoing, turns };
}

async function typeMessage(page: any, message: string = MESSAGE): Promise<any> {
	const editor = page.getByTestId('message-editor').last();
	await expect(editor).toBeVisible({ timeout: 10000 });
	// CI answers from the committed PII send fixture; on dev the real model answers.
	await fillMessageEditor(page, editor, withMockMarker(message, 'pii_detection_send'));
	// The composer has processed the draft once its basic check marks the email.
	await expect(page.locator('[data-testid="pii-highlight"][data-pii-type="EMAIL"]').first()).toBeVisible({ timeout: 15000 });
	await expect(page.locator('[data-action="send-message"]')).toBeVisible({ timeout: 10000 });
	return editor;
}

function expectNothingRawLeft(outgoing: string[]): void {
	for (const needle of RAW_PERSONAL_DATA) {
		expect(outgoing.filter((text) => text.includes(needle)), `"${needle}" must never leave the browser`).toEqual([]);
	}
}

// contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.web.local-bounded-inference
test('a slow detector delays the send until name and address are replaced', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(300000);
	const logCheckpoint = createSignupLogger('PII_SLOW_DETECTOR');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'pii-slow-detector' });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await serveDetector(page, 'slow');
	const { outgoing, turns } = recordOutgoing(page);

	await archiveExistingScreenshots(logCheckpoint);
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);
	await typeMessage(page);
	await takeStepScreenshot(page, 'typed-before-detector-finished');

	// Send at once, before the slowed model has marked anything.
	const sentAt = Date.now();
	await page.locator('[data-action="send-message"]').click();
	await page.waitForTimeout(PREVIEW_BUDGET_MS + 500);
	expect(turns, 'the message must still wait after the old 2.5 s budget').toEqual([]);
	await takeStepScreenshot(page, 'waiting-for-detector');

	await expect.poll(() => turns.length, { timeout: 180000, message: 'the message is sent once the detector finishes' })
		.toBeGreaterThan(0);
	const waitedMs = turns[0].at - sentAt;
	logCheckpoint(`Message left ${waitedMs} ms after send (each model reply delayed ${SLOW_REPLY_MS} ms).`);
	expect(waitedMs).toBeGreaterThan(SLOW_REPLY_MS);
	expect(turns[0].content).toMatch(/\[EMAIL_\w+\]/);
	expect(turns[0].content).toMatch(/\[PHONE_\w+\]/);
	expectNothingRawLeft(outgoing);

	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toBeVisible({ timeout: 30000 });
	await userMessage.scrollIntoViewIfNeeded();
	await takeStepScreenshot(page, 'sent-with-placeholders');

	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'pii-slow-detector-cleanup');
	expectNothingRawLeft(outgoing);
});

// contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.web.local-bounded-inference
test('a failing detector blocks the send, keeps the draft and asks to try again', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(240000);
	const logCheckpoint = createSignupLogger('PII_FAILING_DETECTOR');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'pii-failing-detector' });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await serveDetector(page, 'failing');
	const { outgoing, turns } = recordOutgoing(page);

	await archiveExistingScreenshots(logCheckpoint);
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);
	const editor = await typeMessage(page);
	await page.locator('[data-action="send-message"]').click();

	await expect(page.getByText('Your message was not sent', { exact: false }).first()).toBeVisible({ timeout: 120000 });
	await expect(editor).toContainText('Jonas Albrecht', { timeout: 10000 });
	await takeStepScreenshot(page, 'blocked-with-notice');
	// Pressing send again retries the detector; it fails again, so still nothing leaves.
	await page.locator('[data-action="send-message"]').click();
	await page.waitForTimeout(5000);
	expect(turns).toEqual([]);
	expectNothingRawLeft(outgoing);
	await expect(editor).toContainText('Jonas Albrecht');
	await takeStepScreenshot(page, 'still-blocked-after-retry');
});

// contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.web.local-bounded-inference
test('with a warm detector the protected send still leaves quickly', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(300000);
	const logCheckpoint = createSignupLogger('PII_FAST_DETECTOR');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'pii-fast-detector' });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const { outgoing, turns } = recordOutgoing(page);

	await archiveExistingScreenshots(logCheckpoint);
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);
	// The first send downloads and starts the model (cold); it may take a while.
	await typeMessage(page);
	await page.locator('[data-action="send-message"]').click();
	await expect.poll(() => turns.length, { timeout: 180000, message: 'the cold send leaves' }).toBe(1);
	await expect(page.getByTestId('message-user').last()).toBeVisible({ timeout: 30000 });
	logCheckpoint(`Cold send left after the model started.`);

	// The second send in the same chat uses the warm model and must leave quickly.
	await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 60000 });
	await typeMessage(page, FOLLOW_UP);
	await takeStepScreenshot(page, 'second-message-typed');
	const sentAt = Date.now();
	await page.locator('[data-action="send-message"]').click();
	await expect.poll(() => turns.length, { timeout: 30000 }).toBe(2);
	const waitedMs = turns[1].at - sentAt;
	logCheckpoint(`Warm send left after ${waitedMs} ms.`);
	// CI runners have slow shared CPUs; dev reports the real number on a normal device.
	expect(waitedMs).toBeLessThan(10000);
	expect(turns[1].content).toMatch(/\[EMAIL_\w+\]/);
	expectNothingRawLeft(outgoing);
	await takeStepScreenshot(page, 'sent-quickly');
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'pii-fast-detector-cleanup');
});
