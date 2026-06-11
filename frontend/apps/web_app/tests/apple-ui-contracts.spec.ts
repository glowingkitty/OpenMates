/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Web-rendered UI contract extraction for Apple parity tests.
 * Drives the real browser UI and writes normalized contract artifacts for the
 * native Apple audit/test pipeline. Committed fixtures are promoted explicitly
 * with scripts/apple_ui_contracts.py; this spec only produces runtime evidence.
 * Spec source: docs/specs/apple-ui-contracts/spec.yml
 */
export {};

const path = require('path');
const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const {
	captureContractState,
	createContract,
	writeContractArtifact
} = require('./helpers/apple-ui-contract-helpers');

test.use({
	viewport: { width: 390, height: 844 },
	launchOptions: {
		args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']
	},
	permissions: ['microphone']
});

const SAMPLE_PNG = path.join(__dirname, 'fixtures', 'sample.png');
const SAMPLE_PY = path.join(__dirname, 'fixtures', 'sample.py');

const DEFAULT_ELEMENTS = [
	{ testId: 'message-field', semanticId: 'message-field' },
	{ testId: 'message-editor', semanticId: 'message-editor' },
	{ testId: 'action-buttons', semanticId: 'action-buttons' },
	{ testId: 'record-audio-button', semanticId: 'record-audio-button' }
];

async function openUsableComposer(page: any): Promise<void> {
	await page.goto(getE2EDebugUrl('/'));
	await page.waitForLoadState('load');
	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 15000
	});
	const newChatButton = page.getByTestId('new-chat-cta-fullwidth');
	if (await newChatButton.isVisible({ timeout: 10000 }).catch(() => false)) {
		await newChatButton.click();
	}
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 20000 });
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');
	await expect(page.getByTestId('action-buttons').first()).toBeVisible({ timeout: 20000 });
}

async function attachFiles(page: any, filePaths: string[]): Promise<void> {
	const fileInput = page.locator('input[type="file"][multiple]');
	await expect(fileInput).toBeAttached({ timeout: 10000 });
	await fileInput.setInputFiles(filePaths);
	await expect(page.getByTestId('embed-full-width-wrapper').first()).toBeVisible({ timeout: 30000 });
}

test('captures message input web UI contract for Apple parity', async ({ page }) => {
	test.setTimeout(120000);

	await openUsableComposer(page);

	const states = [];
	states.push(await captureContractState(page, {
		id: 'default',
		description: 'Focused authenticated message composer before attachments.',
		elements: DEFAULT_ELEMENTS
	}));

	await page.getByTestId('message-editor').click();
	states.push(await captureContractState(page, {
		id: 'focused',
		description: 'Focused composer with action buttons visible.',
		elements: DEFAULT_ELEMENTS
	}));

	await attachFiles(page, [SAMPLE_PNG]);
	states.push(await captureContractState(page, {
		id: 'image-pending-embed',
		description: 'Composer with uploaded image pending embed preview.',
		elements: [
			...DEFAULT_ELEMENTS,
			{ testId: 'embed-full-width-wrapper', semanticId: 'pending-composer-embed' }
		]
	}));

	await attachFiles(page, [SAMPLE_PY]);
	states.push(await captureContractState(page, {
		id: 'file-pending-embed',
		description: 'Composer with uploaded file/code pending embed preview.',
		elements: [
			...DEFAULT_ELEMENTS,
			{ testId: 'embed-full-width-wrapper', semanticId: 'pending-composer-embed' }
		]
	}));

	const freshPage = await page.context().newPage();
	await openUsableComposer(freshPage);
	const recordButton = freshPage.getByTestId('record-audio-button');
	await expect(recordButton).toBeVisible({ timeout: 20000 });
	await recordButton.dispatchEvent('mousedown', { button: 0 });
	await expect(freshPage.getByTestId('record-overlay')).toBeVisible({ timeout: 5000 });
	states.push(await captureContractState(freshPage, {
		id: 'recording-overlay',
		description: 'Press-and-hold audio recording overlay.',
		elements: [
			{ testId: 'record-overlay', semanticId: 'record-overlay' },
			{ testId: 'release-text', semanticId: 'release-text' },
			{ testId: 'timer-pill', semanticId: 'timer-pill' },
			{ testId: 'cancel-hint', semanticId: 'cancel-hint' },
			{ testId: 'mic-button', semanticId: 'mic-button' }
		]
	}));
	await freshPage.dispatchEvent('body', 'mouseup');
	await freshPage.close();

	const contract = createContract('message-input', { width: 390, height: 844 }, states);
	const outputPath = writeContractArtifact(contract, 'message-input.generated.json');
	expect(contract.states).toHaveLength(5);
	expect(outputPath).toContain('message-input.generated.json');
});
