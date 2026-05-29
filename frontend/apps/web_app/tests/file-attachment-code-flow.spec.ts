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
const { skipWithoutCredentials } = require('./helpers/env-guard');

const SAMPLE_PY = path.join(__dirname, 'fixtures', 'sample.py');
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

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
		await stopButton.click();
		await expect(stopButton).not.toBeVisible({ timeout: 15000 });
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

test('uploaded CSV, EML, DOCX, and XLSX files render as redacted embeds', async ({
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
				name: 'contacts.csv',
				mimeType: 'text/csv',
				buffer: Buffer.from('Name,Email\nAda,ada.private@example.com\nGrace,grace.secret@example.com')
			},
			{
				name: 'message.eml',
				mimeType: 'message/rfc822',
				buffer: Buffer.from([
					'From: Ada <ada.private@example.com>',
					'To: Grace <grace.secret@example.com>',
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
	await expect(sheetEmbed).toBeVisible({ timeout: 20000 });
	await expect(mailEmbed).toBeVisible({ timeout: 20000 });
	await expect(docEmbed).toBeVisible({ timeout: 20000 });
	await expect(page.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="sheets-sheet"]')).toHaveCount(2, { timeout: 20000 });
	await expect(editor).not.toContainText('ada.private@example.com');
	await expect(editor).not.toContainText('grace.secret@example.com');
	await expect(editor).not.toContainText('docx.private@example.com');
	await expect(editor).not.toContainText('xlsx.private@example.com');
	await expect(editor).toContainText('[EMAIL_');
	log('CSV, EML, DOCX, and XLSX embeds rendered with email placeholders in the editor.');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();

	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toBeVisible({ timeout: 20000 });
	await expect(userMessage.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="sheets-sheet"]')).toBeVisible({ timeout: 20000 });
	await expect(userMessage.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="mail-email"]')).toBeVisible({ timeout: 20000 });
	await expect(userMessage.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="docs-doc"]')).toBeVisible({ timeout: 20000 });
	await expect(userMessage).not.toContainText('ada.private@example.com');
	await expect(userMessage).not.toContainText('grace.secret@example.com');
	await expect(userMessage).not.toContainText('docx.private@example.com');
	await expect(userMessage).not.toContainText('xlsx.private@example.com');
	await expect(userMessage).toContainText('[EMAIL_');
	log('Sent CSV, EML, DOCX, and XLSX embeds preserve placeholders without raw PII.');

	await deleteActiveChat(page, log, screenshot, 'cleanup');
});

test('fullscreen draft embed can include original PII before send', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('FILE_ATTACH_PII_INCLUDE_ORIGINAL');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-pii-include-original' });
	await archiveExistingScreenshots(log);

	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	await openNewChat(page, log);
	const editor = page.getByTestId('message-editor');
	await editor.click();
	await page.keyboard.type('Please review this draft email:');

	await attachFiles(
		page,
		[
			{
				name: 'include-original.eml',
				mimeType: 'message/rfc822',
				buffer: Buffer.from([
					'From: Ada <ada.include@example.com>',
					'To: Grace <grace.include@example.com>',
					'Subject: Include original test',
					'',
					'Call +1 555 765 4321 before launch.'
				].join('\n'))
			}
		],
		log
	);

	const mailEmbed = page.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="mail-email"]'
	).first();
	await expect(mailEmbed).toBeVisible({ timeout: 20000 });
	await expect(editor).not.toContainText('grace.include@example.com');
	await mailEmbed.click();

	const includeOriginalButton = page.getByTestId('embed-pii-include-original');
	await expect(includeOriginalButton).toBeVisible({ timeout: 10000 });
	await includeOriginalButton.click();
	await expect(includeOriginalButton).not.toBeVisible({ timeout: 10000 });
	await expect(page.locator('.fullscreen-embed-container')).toContainText('grace.include@example.com', { timeout: 10000 });
	await screenshot(page, 'after-include-original');

	await page.getByTestId('embed-minimize').click();
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();

	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toBeVisible({ timeout: 20000 });
	await expect(userMessage).toContainText('grace.include@example.com', { timeout: 20000 });
	log('Draft embed sent with original PII after explicit fullscreen action.');

	await deleteActiveChat(page, log, screenshot, 'cleanup');
});
