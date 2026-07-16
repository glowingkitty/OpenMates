/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Broad web-rendered chat UI contract extraction for Apple parity.
 * Captures chat shell, sidebar/list, transcript, and composer structure from
 * the browser source of truth so native Apple audits can rank deterministic
 * parity gaps before screenshot review. Runtime artifacts are not fixtures.
 * Spec source: docs/specs/apple-ui-parity-program/spec.yml
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	captureContractState,
	createContract,
	writeContractArtifact
} = require('./helpers/apple-ui-contract-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const EXAMPLE_CHAT_PATH = '/#chat-id=example-artemis-ii-mission';
const DIMENSIONS = [
	{ id: 'iphone', width: 390, height: 844 },
	{ id: 'ipad', width: 1024, height: 1366 }
] as const;

const SHELL_ELEMENTS = [
	{ testId: 'sidebar-toggle', semanticId: 'sidebar-toggle' },
	{ testId: 'chat-history', semanticId: 'chat-list', required: false, severity: 'fail' },
	{ testId: 'chat-history-container', semanticId: 'chat-transcript-container', required: false, severity: 'fail' }
];

const CHAT_LIST_ELEMENTS = [
	{ testId: 'chat-history', semanticId: 'chat-list', required: false, severity: 'fail' },
	{ testId: 'chat-item-wrapper', semanticId: 'chat-list-row', required: false, severity: 'fail' },
	{ testId: 'chat-item', semanticId: 'chat-list-item', required: false, severity: 'fail' },
	{ testId: 'group-title', semanticId: 'chat-list-group-title', required: false, severity: 'fail' },
	{ testId: 'unread-badge', semanticId: 'chat-list-unread-badge', required: false, severity: 'warn' }
];

const TRANSCRIPT_ELEMENTS = [
	{ testId: 'chat-history-container', semanticId: 'chat-transcript-container' },
	{ testId: 'chat-history-content', semanticId: 'chat-transcript-content' },
	{ testId: 'chat-header-banner', semanticId: 'chat-header-banner' },
	{ testId: 'chat-header-title', semanticId: 'chat-header-title', required: false, severity: 'fail' },
	{ testId: 'message-assistant', semanticId: 'assistant-message' },
	{ testId: 'mate-profile', semanticId: 'mate-profile' },
	{ testId: 'mate-message-content', semanticId: 'assistant-message-content' }
];

const COMPOSER_ELEMENTS = [
	{ testId: 'message-field', semanticId: 'message-field' },
	{ testId: 'message-editor', semanticId: 'message-editor' },
	{ testId: 'action-buttons', semanticId: 'action-buttons', required: false, severity: 'fail' },
	{ testId: 'record-audio-button', semanticId: 'record-audio-button', required: false, severity: 'fail' }
];

async function openAuthenticatedChat(page: any): Promise<void> {
	await loginToTestAccount(page);
	await page.goto(getE2EDebugUrl('/'));
	await page.waitForLoadState('load');
	await expect(page.getByTestId('sidebar-toggle')).toBeVisible({ timeout: 30_000 });
	const chatList = page.getByTestId('chat-history');
	if (!(await chatList.isVisible({ timeout: 2000 }).catch(() => false))) {
		const toggle = page.getByTestId('sidebar-toggle');
		if (await toggle.isVisible({ timeout: 5000 }).catch(() => false)) {
			await toggle.click();
		}
	}
}

async function openExampleTranscript(page: any): Promise<void> {
	await page.goto(getE2EDebugUrl(EXAMPLE_CHAT_PATH), { waitUntil: 'networkidle' });
	await expect(page.getByTestId('chat-history-container')).toBeVisible({ timeout: 45_000 });
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30_000 });
}

test.describe('Apple broad chat UI web contracts', () => {
	for (const dimension of DIMENSIONS) {
		test(`captures ${dimension.id} chat UI umbrella contract`, async ({ page }) => {
			test.setTimeout(180_000);
			skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
			await page.setViewportSize({ width: dimension.width, height: dimension.height });

			const states = [];
			await openAuthenticatedChat(page);
			states.push(await captureContractState(page, {
				id: 'authenticated-shell',
				description: 'Authenticated app shell with chat navigation entry points.',
				elements: SHELL_ELEMENTS
			}));
			states.push(await captureContractState(page, {
				id: 'chat-list',
				description: 'Authenticated chat list/sidebar signals for Apple testability mapping.',
				elements: CHAT_LIST_ELEMENTS
			}));

			await openExampleTranscript(page);
			states.push(await captureContractState(page, {
				id: 'example-transcript',
				description: 'Public example transcript structure for chat message and header parity.',
				elements: TRANSCRIPT_ELEMENTS
			}));
			await page.getByTestId('message-editor').click();
			states.push(await captureContractState(page, {
				id: 'composer',
				description: 'Visible composer and action affordance structure for chat parity.',
				elements: COMPOSER_ELEMENTS
			}));

			const contract = createContract('chat-ui', dimension, states);
			const outputPath = writeContractArtifact(contract, `chat-ui.${dimension.id}.generated.json`);
			expect(states).toHaveLength(4);
			expect(outputPath).toContain(`chat-ui.${dimension.id}.generated.json`);
		});
	}
});
