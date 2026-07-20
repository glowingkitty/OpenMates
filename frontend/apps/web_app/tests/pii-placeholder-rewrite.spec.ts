/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: pii-placeholder-rewrite
/**
 * Web regression for client-side PII placeholder rewrite.
 *
 * This spec captures the real websocket send payload. The contract is that a
 * follow-up typed with a previously mapped original value is rewritten before
 * the inference payload leaves the browser.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createSignupLogger,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const PRIVATE_EMAIL = 'rewrite-owner@example.net';
const SEED_TEXT = `Remember ${PRIVATE_EMAIL} as my private contact for this rewrite test.`;
const FOLLOW_UP_TEXT = `Use ${PRIVATE_EMAIL} for the signup form in one short sentence.`;

type CapturedOutboundFrame = {
	type: string;
	content: string;
	raw: string;
};

function redactTestValues(value: string): string {
	return value.split(PRIVATE_EMAIL).join('<private-email>');
}

function createRedactingLogger(label: string): (message: string, metadata?: Record<string, unknown>) => void {
	const baseLogger = createSignupLogger(label);
	return (message: string, metadata?: Record<string, unknown>) => {
		baseLogger(redactTestValues(message), metadata);
	};
}

function extractOutboundContent(parsed: Record<string, any>): string | null {
	if (parsed.type === 'chat_message_added') {
		return typeof parsed.payload?.message?.content === 'string'
			? parsed.payload.message.content
			: null;
	}

	if (parsed.type === 'chat_turn_preflight') {
		return typeof parsed.payload?.inference_request?.message?.content === 'string'
			? parsed.payload.inference_request.message.content
			: null;
	}

	return null;
}

function captureOutboundInferenceFrames(page: any, frames: CapturedOutboundFrame[]): void {
	page.on('websocket', (ws: any) => {
		ws.on('framesent', (frame: any) => {
			const raw = String(frame.payload ?? '');
			try {
				const parsed = JSON.parse(raw) as Record<string, any>;
				const content = extractOutboundContent(parsed);
				if (content === null) return;

				frames.push({
					type: parsed.type,
					content,
					raw
				});
			} catch {
				// Ignore non-JSON websocket frames.
			}
		});
	});
}

function findPlaceholder(content: string): string | null {
	return content.match(/\[EMAIL_\d+_[A-Za-z0-9]+\]/)?.[0] ?? null;
}

async function waitForSentContent(
	frames: CapturedOutboundFrame[],
	startIndex: number,
	predicate: (content: string) => boolean,
	message: string
): Promise<CapturedOutboundFrame[]> {
	let matchingFrames: CapturedOutboundFrame[] = [];
	await expect
		.poll(
			() => {
				matchingFrames = frames.slice(startIndex).filter((frame) => predicate(frame.content));
				return matchingFrames.length;
			},
			{ timeout: 30000, message }
		)
		.toBeGreaterThan(0);
	return matchingFrames;
}

async function expectLastUserMessageContains(page: any, expectedText: string | RegExp): Promise<void> {
	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toBeVisible({ timeout: 15000 });
	await expect(userMessage).toContainText(expectedText, { timeout: 15000 });
}

test('rewrites prior PII originals before outbound follow-up send', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logCheckpoint = createRedactingLogger('PII_PLACEHOLDER_REWRITE');
	const outboundFrames: CapturedOutboundFrame[] = [];
	captureOutboundInferenceFrames(page, outboundFrames);

	await loginToTestAccount(page, logCheckpoint);
	await startNewChat(page, logCheckpoint);

	const seedFrameStart = outboundFrames.length;
	await sendMessage(
		page,
		withMockMarker(SEED_TEXT, 'pii_detection_check'),
		logCheckpoint,
		undefined,
		'pii-rewrite-seed'
	);

	const seedFrames = await waitForSentContent(
		outboundFrames,
		seedFrameStart,
		(content) => content.includes('private contact'),
		'Initial send should produce a redacted outbound inference payload'
	);
	const seedContent = seedFrames[0].content;
	const placeholder = findPlaceholder(seedContent);
	expect(placeholder).toBeTruthy();
	expect(seedContent).not.toContain(PRIVATE_EMAIL);

	await expectLastUserMessageContains(page, placeholder as string);

	const chatPiiToggle = page.getByTestId('chat-pii-toggle');
	await expect(chatPiiToggle).toBeVisible({ timeout: 15000 });
	await chatPiiToggle.click();
	await expectLastUserMessageContains(page, PRIVATE_EMAIL);
	await chatPiiToggle.click();
	await expectLastUserMessageContains(page, placeholder as string);

	await waitForAssistantMessage(page, {
		which: 'last',
		timeout: 120000,
		logCheckpoint
	});

	const followUpFrameStart = outboundFrames.length;
	await sendMessage(
		page,
		withMockMarker(FOLLOW_UP_TEXT, 'manual_follow_up_hides_suggestions'),
		logCheckpoint,
		undefined,
		'pii-rewrite-followup'
	);

	const followUpFrames = await waitForSentContent(
		outboundFrames,
		followUpFrameStart,
		(content) => content.includes('signup form') && content.includes(placeholder as string),
		'Follow-up send should include the prior placeholder in outbound inference payloads'
	);

	for (const frame of followUpFrames) {
		expect(frame.content).toContain(placeholder as string);
		expect(frame.content).not.toContain(PRIVATE_EMAIL);
	}

	await expectLastUserMessageContains(page, placeholder as string);
	await deleteActiveChat(page, logCheckpoint, undefined, 'pii-rewrite-cleanup');
});
