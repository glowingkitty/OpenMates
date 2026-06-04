/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Account export E2E test for Settings > Account > Export.
 *
 * Verifies the full data-portability flow: authenticated navigation, selectable
 * export categories, browser ZIP download, expected archive structure, included
 * chat data, and exclusion of secret key material.
 *
 * User guide: docs/user-guide/export-account.md
 */

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
 createStepScreenshotter,
 assertNoMissingTranslations,
 getTestAccount
} = require('./signup-flow-helpers');
const { docCheckpoint } = require('./helpers/doc-checkpoint');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const EXPORT_GUIDE_PATH = 'docs/user-guide/export-account.md';
const IMPORT_CHAT_TITLE_1 = 'Playwright Import Test Chat 1';
const IMPORT_CHAT_TITLE_2 = 'Playwright Import Test Chat 2';
const IMPORT_CHAT_TITLES = [IMPORT_CHAT_TITLE_1, IMPORT_CHAT_TITLE_2];

type ZipEntry = {
	name: string;
	method: number;
	compressedSize: number;
	uncompressedSize: number;
	localHeaderOffset: number;
};

function readUInt16(buffer: Buffer, offset: number): number {
	return buffer.readUInt16LE(offset);
}

function readUInt32(buffer: Buffer, offset: number): number {
	return buffer.readUInt32LE(offset);
}

function findEndOfCentralDirectory(buffer: Buffer): number {
	for (let offset = buffer.length - 22; offset >= 0; offset--) {
		if (readUInt32(buffer, offset) === 0x06054b50) return offset;
	}
	throw new Error('ZIP end-of-central-directory record not found.');
}

function parseZipEntries(buffer: Buffer): Map<string, ZipEntry> {
	const eocdOffset = findEndOfCentralDirectory(buffer);
	const entryCount = readUInt16(buffer, eocdOffset + 10);
	let centralOffset = readUInt32(buffer, eocdOffset + 16);
	const entries = new Map<string, ZipEntry>();

	for (let index = 0; index < entryCount; index++) {
		if (readUInt32(buffer, centralOffset) !== 0x02014b50) {
			throw new Error(`Invalid ZIP central directory header at ${centralOffset}.`);
		}

		const method = readUInt16(buffer, centralOffset + 10);
		const compressedSize = readUInt32(buffer, centralOffset + 20);
		const uncompressedSize = readUInt32(buffer, centralOffset + 24);
		const nameLength = readUInt16(buffer, centralOffset + 28);
		const extraLength = readUInt16(buffer, centralOffset + 30);
		const commentLength = readUInt16(buffer, centralOffset + 32);
		const localHeaderOffset = readUInt32(buffer, centralOffset + 42);
		const name = buffer.toString('utf8', centralOffset + 46, centralOffset + 46 + nameLength);

		entries.set(name, { name, method, compressedSize, uncompressedSize, localHeaderOffset });
		centralOffset += 46 + nameLength + extraLength + commentLength;
	}

	return entries;
}

function readZipEntry(buffer: Buffer, entry: ZipEntry): string {
	const localOffset = entry.localHeaderOffset;
	if (readUInt32(buffer, localOffset) !== 0x04034b50) {
		throw new Error(`Invalid ZIP local file header for ${entry.name}.`);
	}
	const nameLength = readUInt16(buffer, localOffset + 26);
	const extraLength = readUInt16(buffer, localOffset + 28);
	const dataStart = localOffset + 30 + nameLength + extraLength;
	const compressed = buffer.subarray(dataStart, dataStart + entry.compressedSize);

	if (entry.method === 0) return compressed.toString('utf8');
	if (entry.method === 8) return zlib.inflateRawSync(compressed).toString('utf8');
	throw new Error(`Unsupported ZIP compression method ${entry.method} for ${entry.name}.`);
}

function requireZipEntry(entries: Map<string, ZipEntry>, name: string): ZipEntry {
	const entry = entries.get(name);
	if (!entry) throw new Error(`Expected ZIP entry not found: ${name}`);
	return entry;
}

async function openExportSettings(page: any, log: (message: string) => void): Promise<void> {
	const settingsMenuButton = page.getByTestId('profile-container');
	await expect(settingsMenuButton).toBeVisible({ timeout: 15000 });
	await settingsMenuButton.click();

	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await settingsMenu.getByRole('menuitem', { name: /^account$/i }).click();
	await settingsMenu.getByRole('menuitem', { name: /export/i }).click();

	await expect(page.getByRole('button', { name: /export my data/i })).toBeVisible({ timeout: 15000 });
 log('Opened Settings > Account > Export.');
}

async function openImportSettings(page: any, log: (message: string) => void): Promise<void> {
 const settingsMenuButton = page.getByTestId('profile-container');
 await expect(settingsMenuButton).toBeVisible({ timeout: 15000 });
 await settingsMenuButton.click();

 const settingsMenu = page.getByTestId('settings-menu');
 await expect(settingsMenu).toBeVisible({ timeout: 10000 });
 await settingsMenu.getByRole('menuitem', { name: /^account$/i }).click();
 await settingsMenu.getByRole('menuitem', { name: /import/i }).click();

 await expect(page.locator('#import-file-input')).toBeAttached({ timeout: 15000 });
 log('Opened Settings > Account > Import.');
}

async function deleteChatByTitle(page: any, title: string): Promise<void> {
 for (let attempt = 0; attempt < 6; attempt++) {
  const chatTitle = page
   .getByTestId('chat-item-wrapper')
   .getByTestId('chat-title')
   .filter({ hasText: title })
   .first();
  const exists = await chatTitle.isVisible({ timeout: 1500 }).catch(() => false);
  if (!exists) return;

  const chatItem = chatTitle.locator('xpath=ancestor::*[@data-testid="chat-item-wrapper"]').first();
  await chatItem.click({ button: 'right' });

  const deleteButton = page.getByTestId('chat-context-delete');
  await expect(deleteButton).toBeVisible({ timeout: 5000 });
  await deleteButton.click();
  await deleteButton.click();

  await expect(chatTitle).not.toBeVisible({ timeout: 10000 });
  await page.waitForTimeout(700);
 }
}

async function importKnownChats(page: any, log: (message: string, details?: unknown) => void, screenshot: any): Promise<void> {
 for (const title of IMPORT_CHAT_TITLES) {
  await deleteChatByTitle(page, title);
 }

 await openImportSettings(page, log);
 await screenshot(page, 'import-page');

 const zipFilePath = path.resolve(__dirname, 'fixtures', 'import-chats-test.zip');
 await page.setInputFiles('#import-file-input', zipFilePath);
 log('Uploaded import ZIP file.', { zipFilePath });

 const importSelectionSection = page.getByTestId('import-select-section');
 await expect(importSelectionSection).toBeVisible({ timeout: 15000 });
 await expect(importSelectionSection.getByTestId('chat-item')).toHaveCount(2, { timeout: 15000 });
 await expect(
  importSelectionSection.locator('[data-testid="chat-item"] [data-testid="chat-title"]', {
   hasText: IMPORT_CHAT_TITLE_1
  })
 ).toBeVisible();
 await expect(
  importSelectionSection.locator('[data-testid="chat-item"] [data-testid="chat-title"]', {
   hasText: IMPORT_CHAT_TITLE_2
  })
 ).toBeVisible();

 const importButton = page.getByRole('button', { name: /import selected chats/i });
 await expect(importButton).toBeEnabled({ timeout: 10000 });
 await importButton.click();
 log('Started chat import.');

const resultsContainer = page.getByTestId('import-results-container');
	await expect(resultsContainer).toBeVisible({ timeout: 45000 });
	await expect(resultsContainer).toContainText(/import complete!/i, { timeout: 45000 });
	await expect(resultsContainer.getByTestId('import-result-item').filter({ hasText: IMPORT_CHAT_TITLE_1 })).toBeVisible();
	await expect(resultsContainer.getByTestId('import-result-item').filter({ hasText: IMPORT_CHAT_TITLE_2 })).toBeVisible();
	await screenshot(page, 'import-success');

	// Close the settings menu after import so openExportSettings can work
	// without the close-icon-container overlaying profile-container.
	// Click the visible close button (data-testid="icon-button-close") which
	// calls toggleMenu() directly via Svelte's onclick handler.
	const closeButton = page.getByTestId('icon-button-close');
	await expect(closeButton).toBeVisible({ timeout: 5000 });
	await closeButton.click();
	await expect(page.getByTestId('settings-menu')).not.toBeVisible({ timeout: 5000 });
	log('Closed settings menu after import.');
}

test('exports account data ZIP from account settings', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('EXPORT_ACCOUNT');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'export-account' });
	await archiveExistingScreenshots(log);

 await loginToTestAccount(page, log, screenshot);
 log('Logged in to test account.');

 await importKnownChats(page, log, screenshot);

 await openExportSettings(page, log);
	await screenshot(page, 'export-options');
	await docCheckpoint(page, {
		id: 'export-options',
		guide: EXPORT_GUIDE_PATH,
		title: 'Account export category selection',
		screenshot: 'docs/images/user-guide/export-account/export-options.jpg'
	});

	await expect(page.getByText(/what's included/i)).toBeVisible({ timeout: 10000 });
	await expect(page.getByLabel(/all your chats and conversations/i)).toBeChecked();
	await expect(page.getByLabel(/your profile and preferences/i)).toBeChecked();
	await expect(page.getByLabel(/app settings and ai memories/i)).toBeChecked();
	await expect(page.getByLabel(/usage history and credit transactions/i)).toBeChecked();
	await expect(page.getByLabel(/invoice history/i)).toBeChecked();

	const exportButton = page.getByRole('button', { name: /export my data/i });
	await page.getByRole('button', { name: /deselect all/i }).click();
	await expect(exportButton).toBeDisabled();
	await page.getByRole('button', { name: /^select all$/i }).click();
	await expect(exportButton).toBeEnabled();

	const exportPath = testInfo.outputPath('account-export-flow.zip');
	const artifactsDir = path.dirname(exportPath);
	fs.mkdirSync(artifactsDir, { recursive: true });

	const downloadPromise = page.waitForEvent('download', { timeout: 180000 });
	await exportButton.click();
	const download = await downloadPromise;
	expect(download.suggestedFilename()).toMatch(/^openmates_export_.+_\d{8}_\d{6}\.zip$/);
	await download.saveAs(exportPath);
	log('Saved account export ZIP.', { exportPath, filename: download.suggestedFilename() });

	await expect(page.getByText(/export completed/i)).toBeVisible({ timeout: 30000 });
	await screenshot(page, 'export-downloaded');
	await docCheckpoint(page, {
		id: 'export-downloaded',
		guide: EXPORT_GUIDE_PATH,
		title: 'Account export completed and ZIP downloaded',
		screenshot: 'docs/images/user-guide/export-account/export-downloaded.jpg'
	});

	const zipBuffer = fs.readFileSync(exportPath);
	expect(zipBuffer.length, 'Export ZIP should not be empty.').toBeGreaterThan(1000);
	const entries = parseZipEntries(zipBuffer);
	const names = Array.from(entries.keys());

	for (const requiredFile of ['README.md', 'metadata.yml', 'profile/profile.yml']) {
		expect(entries.has(requiredFile), `Expected ${requiredFile} in export ZIP.`).toBe(true);
	}
	expect(names.some((name: string) => name.startsWith('chats/') && name.endsWith('.yml'))).toBe(true);
	expect(names.some((name: string) => name.startsWith('chats/') && name.endsWith('.md'))).toBe(true);
	expect(names.some((name: string) => name.startsWith('chats/') && name.endsWith('code/sample.py'))).toBe(true);
	expect(names.some((name: string) => name.startsWith('chats/') && name.endsWith('images/import-test-image.png'))).toBe(true);

	const metadata = readZipEntry(zipBuffer, requireZipEntry(entries, 'metadata.yml'));
	expect(metadata).toContain('export_version: "2.0"');
	expect(metadata).toContain('chats: true');
	expect(metadata).toContain('profile: true');
	expect(metadata).toMatch(/total_chats:\s*[1-9]/);

	const profile = readZipEntry(zipBuffer, requireZipEntry(entries, 'profile/profile.yml'));
	expect(profile).toContain('export_schema_version: "2.0"');
	expect(profile).toContain('email_verified:');
	expect(profile).toContain('credits:');

 const chatContents = names
  .filter((name: string) => name.startsWith('chats/') && (name.endsWith('.yml') || name.endsWith('.md')))
  .map((name: string) => readZipEntry(zipBuffer, requireZipEntry(entries, name)))
  .join('\n');
	expect(chatContents).toContain(IMPORT_CHAT_TITLE_1);
	expect(chatContents).toContain(IMPORT_CHAT_TITLE_2);
	expect(chatContents).toContain('import-test-code-embed');
	expect(chatContents).toContain('import-test-image-embed');

	const codeEntryName = names.find((name: string) => name.startsWith('chats/') && name.endsWith('code/sample.py'));
	const imageEntryName = names.find((name: string) => name.startsWith('chats/') && name.endsWith('images/import-test-image.png'));
	if (!codeEntryName || !imageEntryName) throw new Error('Expected imported code and image files in export ZIP.');
	const exportedCode = readZipEntry(zipBuffer, requireZipEntry(entries, codeEntryName));
	expect(exportedCode).toContain('def factorial(n):');
	expect(requireZipEntry(entries, imageEntryName).uncompressedSize).toBeGreaterThan(0);

	const allTextEntries = names
		.filter((name: string) => /\.(md|yml|csv|txt)$/i.test(name))
		.map((name: string) => readZipEntry(zipBuffer, requireZipEntry(entries, name)))
		.join('\n')
		.toLowerCase();
	for (const forbiddenSecret of [
		'master_key',
		'chat_key',
		'device_key',
		'private_key',
		'password_hash',
		'credential_secret'
	]) {
		expect(allTextEntries, `Export must not include ${forbiddenSecret}.`).not.toContain(forbiddenSecret);
	}

 await assertNoMissingTranslations(page);
 for (const title of IMPORT_CHAT_TITLES) {
  await deleteChatByTitle(page, title);
 }
 log('Account export flow verified and test chat cleaned up.');
});
