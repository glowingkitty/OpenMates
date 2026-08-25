/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Focused code-file upload regression test.
 * Verifies authenticated .py uploads render as code-code embeds immediately.
 * Guards against leaking internal JSON embed reference blocks to users.
 * Uses the deployed dev app through the standard Playwright CI workflow.
 * Keep this separate from file-attachment-flow.spec.ts image/vision cases.
 */

const path = require('path');
const JSZip = require('jszip');
const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { closeFullscreen } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const SAMPLE_PY = path.join(__dirname, 'fixtures', 'sample.py');
const CODE_RUN_REQUESTS_PY = path.join(__dirname, 'fixtures', 'code_run_requests.py');
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';

const CODE_RUN_PROOF_CONTRACT = defineVideoProof({
	id: 'code-run-terminal-artifact-history',
	title: 'Run code and keep generated artifacts',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'request-visible',
			text: 'A Python file is attached in a saved OpenMates chat and opened in the code workspace.',
			checkpoint: 'request-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'result-visible',
			text: 'Code Run executes the file in its sandbox and lists outputs/chart.png and outputs/result.txt as navigable child embeds.',
			checkpoint: 'result-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'history-visible',
			text: 'The image opens in its native viewer, the text output opens in the safe File viewer, and returning keeps the Code Run terminal state.',
			checkpoint: 'history-visible',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'code-run.request.visible',
			checkpoint: 'request-visible',
			visual: 'The saved chat visibly contains the Python code embed without raw JSON or implementation error text.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'code-run.result.visible',
			checkpoint: 'result-visible',
			visual: 'The Code Run terminal shows Hello, World!, a successful exit, and ordered child cards for outputs/chart.png and outputs/result.txt.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'code-run.history.visible',
			checkpoint: 'history-visible',
			visual: 'Native image and generic File child navigation return to the same Code Run parent, where rerun history remains available.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

async function captureBrowserProofFrame(page: any): Promise<Buffer> {
	return page.screenshot({ type: 'png' });
}

async function createDocxBuffer(textLines: string[]): Promise<Buffer> {
  const zip = new JSZip();
  zip.file('word/document.xml', [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>',
    ...textLines.map((line) => `<w:p><w:r><w:t>${line}</w:t></w:r></w:p>`),
    '</w:body></w:document>'
  ].join(''));
  return Buffer.from(await zip.generateAsync({ type: 'uint8array' }));
}

async function createXlsxBuffer(rows: string[][]): Promise<Buffer> {
  const strings = Array.from(new Set(rows.flat()));
  const stringIndex = new Map(strings.map((value, index) => [value, index]));
  const zip = new JSZip();
  zip.file('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>');
  zip.file('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>');
  zip.file('xl/sharedStrings.xml', `<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">${strings.map((value) => `<si><t>${value}</t></si>`).join('')}</sst>`);
  const rowXml = rows.map((row, rowIndex) => `<row r="${rowIndex + 1}">${row.map((cell, colIndex) => `<c r="${String.fromCharCode(65 + colIndex)}${rowIndex + 1}" t="s"><v>${stringIndex.get(cell)}</v></c>`).join('')}</row>`).join('');
  zip.file('xl/worksheets/sheet1.xml', `<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${rowXml}</sheetData></worksheet>`);
  return Buffer.from(await zip.generateAsync({ type: 'uint8array' }));
}

async function openNewChat(page: any, logCheckpoint: (msg: string) => void): Promise<void> {
	await startNewChat(page, logCheckpoint);
	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	logCheckpoint('New chat opened and editor ready.');
}

async function stopActiveResponseIfNeeded(
	page: any,
	logCheckpoint: (msg: string) => void
): Promise<void> {
	const stopButton = page.getByTestId('stop-processing-button');
	if (await stopButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		const stopped = await stopButton.click({ timeout: 3000 })
			.then(() => true)
			.catch(async () => {
				const stillVisible = await stopButton.isVisible({ timeout: 250 }).catch(() => false);
				logCheckpoint(stillVisible
					? 'Stop button was unstable during cleanup; continuing best-effort cleanup.'
					: 'Assistant response completed before the cleanup click settled.');
				return false;
			});
		if (!stopped) return;
		await expect(stopButton)
			.not.toBeVisible({ timeout: 15000 })
			.catch(() => logCheckpoint('Stop button remained visible after cleanup click; continuing best-effort cleanup.'));
		logCheckpoint('Stopped active assistant response before cleanup.');
	}
}

async function attachFiles(
	page: any,
	filePaths: any[],
	logCheckpoint: (msg: string) => void
): Promise<void> {
	const fileInput = page.locator('input[type="file"][multiple]');
	await expect(fileInput).toBeAttached({ timeout: 10000 });

	logCheckpoint(`Attaching ${filePaths.length} file(s): ${filePaths.join(', ')}`);
	await fileInput.setInputFiles(filePaths);
	logCheckpoint('Files attached via setInputFiles().');
}

async function openEmbedFullscreen(page: any, embed: any): Promise<any> {
	const fullscreenOverlay = page.getByTestId('embed-fullscreen-overlay');
	await embed.scrollIntoViewIfNeeded();
	await embed.click();
	await expect(fullscreenOverlay).toBeVisible({ timeout: 15000 });
	return fullscreenOverlay;
}

async function waitForCodeRunSurface(page: any, fileSelection: any, terminal: any): Promise<'selection' | 'terminal'> {
	const deadline = Date.now() + 30000;
	while (Date.now() < deadline) {
		if (await terminal.isVisible({ timeout: 250 }).catch(() => false)) return 'terminal';
		if (await fileSelection.isVisible({ timeout: 250 }).catch(() => false)) return 'selection';
		await page.waitForTimeout(250);
	}
	throw new Error('Code Run did not show file selection or terminal output in time.');
}

// contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
test('uploaded Python file renders as code embed without JSON leakage', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('FILE_ATTACH_CODE_ONLY');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-code-only' });
	await archiveExistingScreenshots(log);

	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	await openNewChat(page, log);
	await screenshot(page, 'new-chat-ready');

	const editor = page.getByTestId('message-editor');
	await editor.click();
	await page.keyboard.type('Please review this Python code:');

	await attachFiles(page, [SAMPLE_PY], log);
	await page.waitForTimeout(5000);
	await screenshot(page, 'after-code-attach');

	const editorCodeEmbed = editor.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'
	);
	await expect(editorCodeEmbed).toBeVisible({ timeout: 20000 });
	await expect(editor).not.toContainText('```json');
	await expect(editor).not.toContainText('"embed_id"');
	log('Code embed rendered in editor without raw JSON reference.');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();
	log('Message with Python file sent.');

	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toBeVisible({ timeout: 20000 });
	await screenshot(page, 'code-message-in-chat');

	const chatCodeEmbed = userMessage.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'
	);
	await expect(chatCodeEmbed).toBeVisible({ timeout: 20000 });

	const visibleTextOutsideEmbeds = await userMessage.evaluate((el: HTMLElement) => {
		const clone = el.cloneNode(true) as HTMLElement;
		clone.querySelectorAll('[data-testid="embed-full-width-wrapper"]').forEach((embed) => embed.remove());
		return clone.textContent || '';
	});
	expect(visibleTextOutsideEmbeds).not.toContain('```json');
	expect(visibleTextOutsideEmbeds).not.toContain('"embed_id"');
	log('Code embed rendered in sent message without raw JSON leakage.');

	await stopActiveResponseIfNeeded(page, log);
	await deleteActiveChat(page, log, screenshot, 'cleanup');
});

// contract-test: direct surface=gui.web assertions=code-run.execution.stream-status-visible,code-run.output.chat-bound-encrypted,code-run.artifacts.encrypted-indexed,code-run.artifacts.chat-bound-versioned,code-run.artifacts.child-renderer-routing,code-run.artifacts.parent-child-navigation,code-run.gui.split-layout-width,code-run.surface-parity,message-input.drafts.preview-persistence,message-input.embeds.gated-send
test('code run output becomes the default code embed preview after reload', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const proof = IS_PROOF_CAPTURE ? createVideoProofRuntime(CODE_RUN_PROOF_CONTRACT, {
		device: PROOF_DEVICE,
		attach: testInfo.attach.bind(testInfo),
		captureFrame: () => captureBrowserProofFrame(page)
	}) : null;

	const log = createSignupLogger('FILE_ATTACH_CODE_RUN_OUTPUT_PREVIEW');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-code-run-output' });
	await archiveExistingScreenshots(log);

	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	await openNewChat(page, log);
	const editor = page.getByTestId('message-editor');
	const editable = editor.locator('[contenteditable="true"]').first();
	const requestText = 'Please run this Python file and keep the result visible:';
	await expect(editable).toBeVisible({ timeout: 10000 });
	await editable.click();
	await editable.pressSequentially(requestText);
	await expect(editor).toContainText(requestText);

	await attachFiles(page, [CODE_RUN_REQUESTS_PY], log);
	await page.waitForTimeout(5000);
	await expect(editor).toContainText(requestText);

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();
	log('Message with Python file sent for Code Run output preview regression.');

	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const chatUrl = page.url();
	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toBeVisible({ timeout: 20000 });
	const chatCodeEmbed = userMessage.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'
	);
	await expect(chatCodeEmbed).toBeVisible({ timeout: 20000 });
	if (proof) {
		await proof.assert('code-run.request.visible', async () => {
			await expect(chatCodeEmbed).toBeVisible();
			await expect(userMessage).not.toContainText('```json');
			await expect(page.getByText('The AI service encountered an error while processing your request.')).toHaveCount(0);
		});
		await proof.checkpoint('request-visible');
	}

	const fullscreenOverlay = await openEmbedFullscreen(page, chatCodeEmbed);
	await fullscreenOverlay.getByTestId('embed-run-button').click();

	const fileSelection = fullscreenOverlay.getByTestId('code-run-file-selection');
	const terminal = fullscreenOverlay.getByTestId('code-run-terminal');
	if ((await waitForCodeRunSurface(page, fileSelection, terminal)) === 'selection') {
		await expect(fileSelection.getByText('requests', { exact: true })).toBeVisible({ timeout: 30000 });
		await expect(fileSelection).not.toContainText('Install Python packages');
		const selectAllButton = fileSelection.getByRole('button', { name: 'Select all' });
		if (await selectAllButton.isVisible({ timeout: 1000 }).catch(() => false)) {
			await selectAllButton.click();
		}
		await fileSelection.getByTestId('code-run-continue').click();
	}

	await expect(terminal).toBeVisible({ timeout: 20000 });
	const terminalOverlay = fullscreenOverlay.getByTestId('code-run-overlay');
	await expect(terminalOverlay).toBeVisible({ timeout: 20000 });
	const terminalOutput = fullscreenOverlay.getByTestId('code-run-output');
	const terminalActions = fullscreenOverlay.getByTestId('code-run-terminal-actions');
	const chatHistoryContent = page.getByTestId('chat-history-content');
	await expect(terminalOutput).toBeVisible();
	await expect(terminalActions).toBeVisible();
	if (page.viewportSize()?.width === 1440) {
		const splitPadding = await chatHistoryContent.evaluate((element: HTMLElement) => {
			const style = getComputedStyle(element);
			return Math.max(Number.parseFloat(style.paddingInlineStart), Number.parseFloat(style.paddingInlineEnd));
		});
		expect(splitPadding).toBeLessThanOrEqual(24);
	}
	if (page.viewportSize()?.width === 390) {
		expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThan(8);
	}
	await expect(terminalOutput).toHaveCSS('overflow-y', 'auto');
	await expect.poll(async () => {
		const [outputBox, actionsBox] = await Promise.all([
			terminalOutput.boundingBox(),
			terminalActions.boundingBox()
		]);
		return Boolean(outputBox && actionsBox && outputBox.y + outputBox.height <= actionsBox.y + 1);
	}).toBe(true);
	await expect(fullscreenOverlay.getByTestId('code-run-view-code')).toBeVisible({ timeout: 10000 });
	await expect(fullscreenOverlay.getByRole('button', { name: 'Hide output' })).toHaveCount(0);
	await expect(terminal).toContainText('Hello, World!', { timeout: 120000 });
	await expect(terminal).toContainText('Exited', { timeout: 120000 });
	await expect(terminalActions).toContainText('Copy output');
	await expect(terminalActions).toContainText('Run again');
	const artifacts = fullscreenOverlay.getByTestId('code-run-artifacts');
	const artifactCards = artifacts.getByTestId('code-run-artifact');
	await expect(artifacts).toBeVisible({ timeout: 120000 });
	await expect(artifactCards).toHaveCount(2);
	await expect(artifactCards.nth(0)).toContainText('outputs/chart.png');
	await expect(artifactCards.nth(1)).toContainText('outputs/result.txt');
	await expect(
		artifactCards.nth(1).getByTestId('code-run-artifact-download')
			.or(artifactCards.nth(1).getByTestId('code-run-artifact-download-unavailable'))
	).toBeVisible();
	await artifactCards.nth(0).getByTestId('code-run-artifact-child-open').click();
	const imageChild = fullscreenOverlay.getByTestId('image-embed-fullscreen');
	await expect(imageChild).toBeVisible({ timeout: 30000 });
	await closeFullscreen(page, imageChild);
	await expect(terminal).toBeVisible({ timeout: 10000 });
	await expect(terminal).toContainText('Hello, World!');
	await artifactCards.nth(1).getByTestId('code-run-artifact-child-open').click();
	const fileChild = page.getByTestId('file-embed-fullscreen');
	await expect(fileChild).toBeVisible({ timeout: 10000 });
	await expect(fileChild).toContainText('outputs/result.txt');
	await expect(fileChild.getByTestId('file-embed-executable-preview')).toHaveCount(0);
	await closeFullscreen(page, fileChild);
	await expect(terminal).toBeVisible({ timeout: 10000 });
	if (proof) {
		await terminalActions.scrollIntoViewIfNeeded();
		await expect(terminalActions).toBeInViewport({ ratio: 1 });
		await proof.assert('code-run.result.visible', async () => {
			await expect(terminal).toContainText('Hello, World!');
			await expect(terminal).toContainText('Exited');
			await expect(artifactCards).toHaveCount(2);
			await expect(artifactCards.nth(0)).toContainText('outputs/chart.png');
			await expect(artifactCards.nth(1)).toContainText('outputs/result.txt');
		});
		await proof.checkpoint('result-visible');
	}

	const runAgainButton = fullscreenOverlay.getByTestId('code-run-action-run-again');
	await runAgainButton.click();
	await expect(runAgainButton).toBeDisabled({ timeout: 10000 });
	await expect(runAgainButton).toBeEnabled({ timeout: 120000 });
	await expect(terminal).toContainText('Exited', { timeout: 120000 });
	await expect(artifactCards).toHaveCount(2, { timeout: 120000 });
	const artifactHistory = artifactCards.nth(1).getByTestId('code-run-artifact-history');
	await expect(artifactHistory).toBeVisible({ timeout: 30000 });
	await artifactHistory.locator('summary').click();
	await expect(artifactHistory).toContainText('outputs/result.txt');
	if (proof) {
		await artifacts.scrollIntoViewIfNeeded();
		await proof.assert('code-run.history.visible', async () => {
			await expect(artifactCards).toHaveCount(2);
			await expect(artifactHistory).toBeVisible();
			await expect(artifactHistory).toContainText('outputs/result.txt');
		});
		await proof.checkpoint('history-visible');
		await proof.attach();
	}
	await stopActiveResponseIfNeeded(page, log);
	await screenshot(page, 'code-run-output-visible-fullscreen');
	await fullscreenOverlay.getByTestId('code-run-view-code').click();
	await expect(terminalOverlay).not.toBeVisible({ timeout: 10000 });
	await expect(fullscreenOverlay.getByTestId('code-source-panel')).toBeVisible({ timeout: 10000 });

	await fullscreenOverlay.getByTestId('embed-minimize').click();
	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 10000 });
	await expect(chatCodeEmbed).toContainText('Hello, World!', { timeout: 120000 });
	await expect(chatCodeEmbed).not.toContainText('def greet');
	log('Code embed preview switched to run output after execution.');

	await page.goto(chatUrl);
	await page.reload({ waitUntil: 'networkidle' });
	const reloadedUserMessage = page.getByTestId('message-user').last();
	await expect(reloadedUserMessage).toBeVisible({ timeout: 30000 });
	const reloadedCodeEmbed = reloadedUserMessage.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'
	);
	await expect(reloadedCodeEmbed).toBeVisible({ timeout: 30000 });
	await expect(reloadedCodeEmbed).toContainText('Hello, World!', { timeout: 120000 });
	await expect(reloadedCodeEmbed).not.toContainText('def greet');
	const reloadedFullscreenOverlay = await openEmbedFullscreen(page, reloadedCodeEmbed);
	await expect(reloadedFullscreenOverlay.getByTestId('code-source-panel')).toBeVisible({ timeout: 10000 });
	await reloadedFullscreenOverlay.getByTestId('embed-run-button').click();
	await expect(reloadedFullscreenOverlay.getByTestId('code-run-terminal')).toBeVisible({ timeout: 10000 });
	await expect(reloadedFullscreenOverlay.getByTestId('code-run-terminal')).toContainText('Hello, World!', { timeout: 10000 });
	await expect(reloadedFullscreenOverlay.getByTestId('code-run-artifact')).toHaveCount(2);
	await expect(reloadedFullscreenOverlay.getByTestId('code-run-artifact-history')).toHaveCount(2);
	await reloadedFullscreenOverlay.getByTestId('code-run-view-code').click();
	await expect(reloadedFullscreenOverlay.getByTestId('code-run-overlay')).not.toBeVisible({ timeout: 10000 });
	await screenshot(page, 'code-run-output-visible-after-reload');
	await reloadedFullscreenOverlay.getByTestId('embed-minimize').click();
	await expect(reloadedFullscreenOverlay).not.toBeVisible({ timeout: 10000 });
	log('Code embed preview still shows run output after reload.');
	await deleteActiveChat(page, log, screenshot, 'cleanup');
});

// contract-test: direct surface=gui.web assertions=message-input.embeds.gated-send,pii.composer.detect-redact-exclude,pii.surface.semantic-parity
test('uploaded code, CSV, EML, DOCX, and XLSX files render as redacted embeds', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('FILE_ATTACH_TEXT_PII');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-text-pii' });
	await archiveExistingScreenshots(log);

	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	await openNewChat(page, log);
	const editor = page.getByTestId('message-editor');
	await editor.click();
	await page.keyboard.type('Please review these uploaded text files:');

	await attachFiles(
		page,
		[
			{
				name: 'secret-config.py',
				mimeType: 'text/x-python',
				buffer: Buffer.from([
					'OPENAI_API_KEY="sk-proj-abcdefghijklmnopqrstuvwxyz123456"',
					'OWNER_EMAIL="developer.private@example.com"'
				].join('\n'))
			},
			{
				name: 'contacts.csv',
				mimeType: 'text/csv',
				buffer: Buffer.from('Name,Email\nAda,ada.private@example.com\nGrace,grace.secret@example.com')
			},
			{
				name: 'message.eml',
				mimeType: 'message/rfc822',
				buffer: Buffer.from([
					'From: Mail Sender <sender.include@example.com>',
					'To: Mail Receiver <receiver.include@example.com>',
					'Subject: Private launch note',
					'',
					'Please call +1 555 123 4567 before launch.'
				].join('\n'))
			},
			{
				name: 'brief.docx',
				mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
				buffer: await createDocxBuffer([
					'Private DOCX launch note',
					'Reach Ada at docx.private@example.com before launch.'
				])
			},
			{
				name: 'contacts.xlsx',
				mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
				buffer: await createXlsxBuffer([
					['Name', 'Email'],
					['Xlsx Ada', 'xlsx.private@example.com']
				])
			}
		],
		log
	);
	await page.waitForTimeout(5000);
	await screenshot(page, 'after-text-file-attach');

	// Sheet/mail embeds can be re-mounted by draft autosave, so assert the rendered wrapper globally.
	const sheetEmbed = page.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="sheets-sheet"]'
	).first();
	const mailEmbed = page.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="mail-email"]'
	).first();
	const docEmbed = page.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="docs-doc"]'
	).first();
	const codeEmbed = page.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'
	).first();
	await expect(codeEmbed).toBeVisible({ timeout: 20000 });
	await expect(sheetEmbed).toBeVisible({ timeout: 20000 });
	await expect(mailEmbed).toBeVisible({ timeout: 20000 });
	await expect(docEmbed).toBeVisible({ timeout: 20000 });
	await expect(page.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="sheets-sheet"]')).toHaveCount(2, { timeout: 20000 });
	await expect(editor).not.toContainText('sk-proj-abcdefghijklmnopqrstuvwxyz123456');
	await expect(editor).not.toContainText('developer.private@example.com');
	await expect(editor).not.toContainText('ada.private@example.com');
	await expect(editor).not.toContainText('grace.secret@example.com');
	await expect(editor).not.toContainText('receiver.include@example.com');
	await expect(editor).not.toContainText('docx.private@example.com');
	await expect(editor).not.toContainText('xlsx.private@example.com');
	await expect(editor).toContainText('[EMAIL_');
	const codeFullscreen = await openEmbedFullscreen(page, codeEmbed);
	const codeSourcePanel = codeFullscreen.getByTestId('code-source-panel');
	await expect(codeSourcePanel).toContainText('[OPENAI_KEY_', { timeout: 10000 });
	await expect(codeSourcePanel).toContainText('[EMAIL_', { timeout: 10000 });
	await expect(codeSourcePanel).not.toContainText('sk-proj-abcdefghijklmnopqrstuvwxyz123456');
	await expect(codeSourcePanel).not.toContainText('developer.private@example.com');
	try {
		await codeFullscreen.getByTestId('embed-minimize').click({ timeout: 5000 });
	} catch {
		await page.keyboard.press('Escape');
	}
	await expect(codeFullscreen).not.toBeVisible({ timeout: 10000 });
	log('Code, CSV, EML, DOCX, and XLSX embeds rendered with PII placeholders in the editor.');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();
	log('Message with code, CSV, EML, DOCX, and XLSX files sent.');

	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toBeVisible({ timeout: 20000 });
	await expect(userMessage).not.toContainText('sk-proj-abcdefghijklmnopqrstuvwxyz123456');
	await expect(userMessage).not.toContainText('developer.private@example.com');
	await expect(userMessage).not.toContainText('ada.private@example.com');
	await expect(userMessage).not.toContainText('grace.secret@example.com');
	await expect(userMessage).not.toContainText('docx.private@example.com');
	await expect(userMessage).not.toContainText('xlsx.private@example.com');
	await screenshot(page, 'after-text-file-send');

	const sentCodeEmbed = userMessage.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'
	).first();
	const sentDocEmbed = userMessage.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="docs-doc"]'
	).first();
	const sentSheetEmbeds = userMessage.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="sheets-sheet"]'
	);
	await expect(sentCodeEmbed).toBeVisible({ timeout: 20000 });
	await expect(sentDocEmbed).toBeVisible({ timeout: 20000 });
	await expect(sentSheetEmbeds).toHaveCount(2, { timeout: 20000 });

	const sentCodeFullscreen = await openEmbedFullscreen(page, sentCodeEmbed);
	await expect(sentCodeFullscreen.getByTestId('code-source-panel')).toContainText('[OPENAI_KEY_', { timeout: 10000 });
	await expect(sentCodeFullscreen.getByTestId('code-source-panel')).toContainText('[EMAIL_', { timeout: 10000 });
	await expect(sentCodeFullscreen.getByTestId('code-source-panel')).not.toContainText('sk-proj-abcdefghijklmnopqrstuvwxyz123456');
	await expect(sentCodeFullscreen.getByTestId('code-source-panel')).not.toContainText('developer.private@example.com');
	await sentCodeFullscreen.getByTestId('embed-minimize').click();
	await expect(sentCodeFullscreen).not.toBeVisible({ timeout: 10000 });

	const sentDocFullscreen = await openEmbedFullscreen(page, sentDocEmbed);
	await expect(sentDocFullscreen).toContainText('[EMAIL', { timeout: 10000 });
	await expect(sentDocFullscreen).not.toContainText('docx.private@example.com');
	await sentDocFullscreen.getByTestId('embed-minimize').click();
	await expect(sentDocFullscreen).not.toBeVisible({ timeout: 10000 });

	for (const index of [0, 1]) {
		const sentSheetFullscreen = await openEmbedFullscreen(page, sentSheetEmbeds.nth(index));
		await expect(sentSheetFullscreen).toContainText('[EMAIL', { timeout: 10000 });
		await expect(sentSheetFullscreen).not.toContainText('ada.private@example.com');
		await expect(sentSheetFullscreen).not.toContainText('grace.secret@example.com');
		await expect(sentSheetFullscreen).not.toContainText('xlsx.private@example.com');
		await sentSheetFullscreen.getByTestId('embed-minimize').click();
		await expect(sentSheetFullscreen).not.toBeVisible({ timeout: 10000 });
	}
	log('Sent code, CSV, DOCX, and XLSX embeds remained placeholder-only in chat.');
	await stopActiveResponseIfNeeded(page, log);
	await deleteActiveChat(page, log, screenshot, 'cleanup');
});
