/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: pii-placeholder-substitution
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
const FIRST_ADDRESS = '42 Maple Avenue, Bristol BS1 4QA';
const SECOND_ADDRESS = '18 Cedar Lane, York YO1 7AA';
const SEED_TEXT = `Our customer Amina Okafor lives at ${FIRST_ADDRESS}. Remember ${PRIVATE_EMAIL} as my private contact for this rewrite test.`;
const FOLLOW_UP_TEXT = `Use ${PRIVATE_EMAIL} for the signup form. Send deliveries to ${SECOND_ADDRESS} and keep ${FIRST_ADDRESS} as the alternate.`;

type CapturedOutboundFrame = {
	type: string;
	content: string;
	raw: string;
};

function redactTestValues(value: string): string {
	return value.split(PRIVATE_EMAIL).join('<private-email>')
		.split(FIRST_ADDRESS).join('<first-address>')
		.split(SECOND_ADDRESS).join('<second-address>');
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

	if (parsed.type === 'chat_turn_admit' || parsed.type === 'chat_turn_preflight') {
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
	return content.match(/\[EMAIL_\d+(?:_[A-Za-z0-9]+)?\]/)?.[0] ?? null;
}

function addressPlaceholders(content: string): string[] {
	const placeholders = [...new Set(content.match(/\[ADDRESS_[^\]]+\]/g) ?? [])];
	expect(placeholders.length, 'The actual model must redact at least one address span').toBeGreaterThan(0);
	for (const placeholder of placeholders) {
		expect(placeholder, 'Outbound tokens retain their collision-resistant identity').toMatch(/^\[ADDRESS_[1-9]\d*_[A-Za-z0-9_]+\]$/);
	}
	return placeholders;
}

async function expectCompactAddressDisplay(page: any, internalTokens: string[]): Promise<void> {
	const message = page.getByTestId('message-user').last();
	const labels = message.getByTestId('pii-placeholder-label').filter({ hasText: /^\[ADDRESS_/ });
	await expect(labels.first()).toBeVisible();
	// A decoration transaction can replace spans between separate async reads.
	// Inspect the complete rendered state in one synchronous DOM snapshot.
	await expect.poll(async () => {
		const snapshot = await labels.evaluateAll((elements: Element[]) => elements.map(element => ({
			label: element.getAttribute('data-pii-display-label'),
			content: getComputedStyle(element, '::after').content,
			fontSize: getComputedStyle(element, '::after').fontSize,
			canonicalFontSize: getComputedStyle(element).fontSize,
			width: element.getBoundingClientRect().width,
			height: element.getBoundingClientRect().height,
			connected: element.isConnected,
		})));
		return { hasLabels: snapshot.length > 0, invalid: snapshot.filter((item: {
			label: string | null; content: string; fontSize: string; canonicalFontSize: string;
			width: number; height: number; connected: boolean;
		}) => !item.connected || !/^\[ADDRESS_[1-9]\d*\]$/.test(item.label ?? '') ||
			item.content !== JSON.stringify(item.label) || item.canonicalFontSize !== '0px' ||
			!(parseFloat(item.fontSize) > 0 && item.width > 0 && item.height > 0)) };
	}, { timeout: 5000 }).toEqual({ hasLabels: true, invalid: [] });
	// Display aliases must not replace canonical tokens used by copy/send.
	for (const token of internalTokens) await expect(message).toContainText(token);
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

// contract-test: direct surface=gui.web assertions=pii.outbound.known-original-rewrite,pii.message.owner-local-reveal
test('shows compact address labels while preserving unique wire tokens and owner restoration after reload', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(420000);
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
	expect(seedContent).not.toContain('Maple Avenue');
	const seedAddresses = addressPlaceholders(seedContent);

	await expectLastUserMessageContains(page, placeholder as string);
	await expectCompactAddressDisplay(page, seedAddresses);

	const chatPiiToggle = page.getByTestId('chat-pii-toggle');
	await expect(chatPiiToggle).toBeVisible({ timeout: 15000 });
	const compactLabel = page.getByTestId('message-user').last().getByTestId('pii-placeholder-label').first();
	await compactLabel.focus();
	await compactLabel.press('Enter');
	await expect(chatPiiToggle).toHaveAttribute('data-pii-revealed', 'true');
	await expectLastUserMessageContains(page, PRIVATE_EMAIL);
	await expectLastUserMessageContains(page, FIRST_ADDRESS);
	await chatPiiToggle.click();
	await expectLastUserMessageContains(page, placeholder as string);
	await expectCompactAddressDisplay(page, seedAddresses);

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
		expect(frame.content).not.toContain('Maple Avenue');
		expect(frame.content).not.toContain('Cedar Lane');
		const followUpAddresses = addressPlaceholders(frame.content);
		expect(followUpAddresses.some(token => seedAddresses.includes(token)), 'Known address components retain their prior tokens').toBe(true);
		expect(followUpAddresses.some(token => !seedAddresses.includes(token)), 'A different address must retain a distinct internal token').toBe(true);
	}

	await expectLastUserMessageContains(page, placeholder as string);
	const followUpAddresses = addressPlaceholders(followUpFrames[0].content);
	await expectCompactAddressDisplay(page, followUpAddresses);
	await page.reload({ waitUntil: 'domcontentloaded' });
	await expectLastUserMessageContains(page, placeholder as string);
	await expectCompactAddressDisplay(page, followUpAddresses);
	await expect(chatPiiToggle).toHaveAttribute('data-pii-revealed', 'false');
	await chatPiiToggle.click();
	await expectLastUserMessageContains(page, PRIVATE_EMAIL);
	await expectLastUserMessageContains(page, FIRST_ADDRESS);
	await expectLastUserMessageContains(page, SECOND_ADDRESS);
	await chatPiiToggle.click();
	await expectLastUserMessageContains(page, placeholder as string);
	await expect(page.getByTestId('message-user').last()).not.toContainText('Cedar Lane');
	await deleteActiveChat(page, logCheckpoint, undefined, 'pii-rewrite-cleanup');
});
