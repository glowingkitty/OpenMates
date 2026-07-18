/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Account export E2E test for Settings > Account > Export.
 *
 * Verifies the data-portability flow: authenticated navigation, selectable
 * export categories, browser ZIP download, V1 archive structure, selected
 * account export domains, and exclusion of secret key material.
 *
 * User guide: docs/user-guide/export-account.md
 */

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const childProcess = require('child_process');
const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
 createStepScreenshotter,
 assertNoMissingTranslations,
 getTestAccount
} = require('./signup-flow-helpers');
const { docAssert, docCheckpoint } = require('./helpers/doc-checkpoint');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const EXPORT_GUIDE_PATH = 'docs/user-guide/export-account.md';
const REPO_ROOT = path.resolve(__dirname, '../../../..');
const ACCOUNT_EXPORT_JOB_STORAGE_KEY = 'openmates.account_export.resume_job';
type ZipEntry = {
	name: string;
	method: number;
	compressedSize: number;
	uncompressedSize: number;
	localHeaderOffset: number;
};

type AccountExportMockConfig = {
	exportId: string;
	selectedDomains: string[];
	completeStatus?: string;
	failures?: Array<Record<string, unknown>>;
};

type AccountExportMockCall = {
	method: string;
	path: string;
	body: Record<string, unknown> | null;
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

function runStandaloneArchiveVerifier(zipPath: string): void {
	childProcess.execFileSync(
		'python3',
		[path.join(REPO_ROOT, 'scripts/verify_account_export_archive.py'), '--zip', zipPath, '--layout-v1', '--forbid-secrets'],
		{ cwd: REPO_ROOT, stdio: 'pipe' }
	);
}

function readManifestJson(zipBuffer: Buffer, entries: Map<string, ZipEntry>): Record<string, unknown> {
	return JSON.parse(readZipEntry(zipBuffer, requireZipEntry(entries, 'manifest.json')));
}

async function installAccountExportMock(page: any, config: AccountExportMockConfig): Promise<AccountExportMockCall[]> {
	const calls: AccountExportMockCall[] = [];
	const chunks = config.selectedDomains.map((domain: string, index: number) => ({
		chunk_id: `${domain}-chunk-1`,
		domain,
		sequence: index + 1,
		status: 'ready',
		payload: buildMockDomainPayload(domain),
	}));
	const domains = Object.fromEntries(chunks.map((chunk: Record<string, unknown>) => [chunk.domain, {
		status: 'ready',
		count: payloadCount(chunk.payload as Record<string, unknown>),
		source: mockDomainSource(String(chunk.domain)),
	}]));
	const manifest = {
		schema_version: 'account-export-v1',
		selected_domains: config.selectedDomains,
		filters: {},
		domains,
		report: {
			status: config.completeStatus === 'partial' ? 'partial' : 'complete',
			failures: config.failures ?? [],
			partial_requires_acceptance: config.completeStatus === 'partial',
			redactions: ['api_credentials'],
		},
	};

	await page.route('**/v1/account-exports**', async (route: any) => {
		const request = route.request();
		const url = new URL(request.url());
		let body: Record<string, unknown> | null = null;
		try {
			body = request.postData() ? JSON.parse(request.postData() || '{}') : null;
		} catch {
			body = null;
		}
		calls.push({ method: request.method(), path: url.pathname, body });

		if (request.method() === 'POST' && url.pathname === '/v1/account-exports') {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ export: { export_id: config.exportId, status: 'queued', selected_domains: body?.domains ?? config.selectedDomains } }) });
			return;
		}
		if (request.method() === 'GET' && url.pathname === `/v1/account-exports/${config.exportId}`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ export: { export_id: config.exportId, status: 'queued', selected_domains: config.selectedDomains } }) });
			return;
		}
		if (request.method() === 'GET' && url.pathname === `/v1/account-exports/${config.exportId}/manifest`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ manifest }) });
			return;
		}
		if (request.method() === 'GET' && url.pathname === `/v1/account-exports/${config.exportId}/chunks`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ chunks: chunks.map(({ chunk_id, domain, sequence, status }: Record<string, unknown>) => ({ chunk_id, domain, sequence, status })) }) });
			return;
		}
		const chunk = chunks.find((candidate: Record<string, unknown>) => url.pathname === `/v1/account-exports/${config.exportId}/chunks/${candidate.chunk_id}`);
		if (request.method() === 'GET' && chunk) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ chunk }) });
			return;
		}
		if (request.method() === 'POST' && url.pathname === `/v1/account-exports/${config.exportId}/complete`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ export: { export_id: config.exportId, status: config.completeStatus ?? 'complete' } }) });
			return;
		}
		if (request.method() === 'POST' && url.pathname === `/v1/account-exports/${config.exportId}/accept-partial`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ export: { export_id: config.exportId, status: 'partial_accepted' } }) });
			return;
		}
		if (request.method() === 'POST' && url.pathname === `/v1/account-exports/${config.exportId}/cancel`) {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ export: { export_id: config.exportId, status: 'cancelled' } }) });
			return;
		}
		await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: `Unhandled mock route ${request.method()} ${url.pathname}` }) });
	});
	return calls;
}

function buildMockDomainPayload(domain: string): Record<string, unknown> {
	if (domain === 'usage') {
		return { source: 'usage+usage_archives', items: [{ id: 'usage-row-1', usage_type: 'chat', credits_charged: 1 }], archives: [] };
	}
	if (domain === 'chats') {
		return { source: 'chats+messages+embeds', items: [{ id: 'chat-row-1', title: 'Mock chat', messages: [{ role: 'user', content: 'Hello export' }], embeds: [] }] };
	}
	return { source: mockDomainSource(domain), items: [{ id: `${domain}-row-1` }] };
}

function mockDomainSource(domain: string): string {
	return ({ usage: 'usage+usage_archives', chats: 'chats+messages+embeds' } as Record<string, string>)[domain] ?? domain;
}

function payloadCount(payload: Record<string, unknown>): number {
	const items = Array.isArray(payload.items) ? payload.items.length : 0;
	const runs = Array.isArray(payload.runs) ? payload.runs.length : 0;
	return items + runs;
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

async function loginAndOpenExportSettings(page: any, log: (message: string) => void, screenshot?: (page: any, name: string) => Promise<void>): Promise<void> {
	await loginToTestAccount(page, log, screenshot ?? (async () => undefined));
	log('Logged in to test account.');
	await openExportSettings(page, log);
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

  await openExportSettings(page, log);
	await screenshot(page, 'export-options');
	await docCheckpoint(page, {
		id: 'export-options',
		guide: EXPORT_GUIDE_PATH,
		title: 'Account export category selection',
		screenshot: 'docs/images/user-guide/export-account/export-options.jpg'
	});

	await docAssert('export-page-shows-data-categories', async () => {
		await expect(page.getByText(/what's included/i)).toBeVisible({ timeout: 10000 });
		await expect(page.getByLabel(/all your chats and conversations/i)).toBeChecked();
		await expect(page.getByLabel(/your profile and preferences/i)).toBeChecked();
		await expect(page.getByLabel(/app settings and ai memories/i)).toBeChecked();
		await expect(page.getByLabel(/usage history and credit transactions/i)).toBeChecked();
		await expect(page.getByLabel(/invoice history/i)).toBeChecked();
	});

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

	await docAssert('export-download-completes', async () => {
		await expect(page.getByText(/export completed/i)).toBeVisible({ timeout: 30000 });
	});
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

	await docAssert('export-zip-contains-account-and-chat-data', async () => {
		for (const requiredFile of ['README.md', 'manifest.yml', 'manifest.json', 'export-report.yml']) {
			expect(entries.has(requiredFile), `Expected ${requiredFile} in export ZIP.`).toBe(true);
		}
		expect(names.some((name: string) => name.startsWith('domains/') && name.endsWith('.json'))).toBe(true);
	});

	const manifest = readZipEntry(zipBuffer, requireZipEntry(entries, 'manifest.yml'));
	expect(manifest).toContain('schema_version: account-export-v1');
	expect(manifest).toContain('selected_domains:');
	expect(manifest).toContain('chats');
	expect(manifest).toContain('usage');

	const report = readZipEntry(zipBuffer, requireZipEntry(entries, 'export-report.yml'));
	expect(report).toContain('redacted_secret_categories:');
	expect(report).toContain('api_credentials');

	const chatsDomainEntry = requireZipEntry(entries, 'domains/chats.json');
	const chatsDomain = readZipEntry(zipBuffer, chatsDomainEntry);
	expect(chatsDomain).toContain('items');

	const chatContents = names
	  .filter((name: string) => name.startsWith('chats/') && (name.endsWith('.yml') || name.endsWith('.md')))
	  .map((name: string) => readZipEntry(zipBuffer, requireZipEntry(entries, name)))
	  .join('\n');
	if (chatContents.length > 0) {
		expect(chatContents).toContain('No readable message records were included');
	}

	const allTextEntries = names
		.filter((name: string) => /\.(json|md|yml|yaml|csv|txt)$/i.test(name))
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
  log('Account export flow verified.');
});

test('exports selected account domains and verifies the browser ZIP with the standalone scanner', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('EXPORT_ACCOUNT_FILTERS');
	const calls = await installAccountExportMock(page, { exportId: 'filtered-export-web', selectedDomains: ['usage'] });
	await loginAndOpenExportSettings(page, log);

	await page.getByRole('button', { name: /deselect all/i }).click();
	await page.getByLabel(/usage history and credit transactions/i).check();

	const exportPath = testInfo.outputPath('account-export-filtered.zip');
	const downloadPromise = page.waitForEvent('download', { timeout: 120000 });
	await page.getByRole('button', { name: /export my data/i }).click();
	const download = await downloadPromise;
	await download.saveAs(exportPath);

	const startCall = calls.find((call) => call.method === 'POST' && call.path === '/v1/account-exports');
	expect(startCall?.body?.domains).toEqual(['usage']);
	expect(startCall?.body?.filters).toEqual({});

	const zipBuffer = fs.readFileSync(exportPath);
	const entries = parseZipEntries(zipBuffer);
	const manifestJson = readManifestJson(zipBuffer, entries);
	expect(manifestJson.selected_domains).toEqual(['usage']);
	expect(entries.has('domains/usage.json')).toBe(true);
	expect(entries.has('domains/chats.json')).toBe(false);
	runStandaloneArchiveVerifier(exportPath);
});

test('resumes a stored account export job without starting a duplicate job', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('EXPORT_ACCOUNT_RESUME');
	const exportId = 'resume-export-web';
	const calls = await installAccountExportMock(page, { exportId, selectedDomains: ['usage'] });
	await loginAndOpenExportSettings(page, log);
	await page.evaluate(({ storageKey, storedExportId }) => {
		localStorage.setItem(storageKey, JSON.stringify({
			exportId: storedExportId,
			signature: JSON.stringify({ domains: ['usage'], filters: {} }),
			createdAt: new Date().toISOString(),
		}));
	}, { storageKey: ACCOUNT_EXPORT_JOB_STORAGE_KEY, storedExportId: exportId });

	await page.getByRole('button', { name: /deselect all/i }).click();
	await page.getByLabel(/usage history and credit transactions/i).check();

	const exportPath = testInfo.outputPath('account-export-resumed.zip');
	const downloadPromise = page.waitForEvent('download', { timeout: 120000 });
	await page.getByRole('button', { name: /export my data/i }).click();
	const download = await downloadPromise;
	await download.saveAs(exportPath);

	expect(calls.some((call) => call.method === 'GET' && call.path === `/v1/account-exports/${exportId}`)).toBe(true);
	expect(calls.some((call) => call.method === 'POST' && call.path === '/v1/account-exports')).toBe(false);
	expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), ACCOUNT_EXPORT_JOB_STORAGE_KEY)).toBeNull();
});

test('requires explicit user acceptance before downloading a partial account export', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('EXPORT_ACCOUNT_PARTIAL');
	const exportId = 'partial-export-web';
	const calls = await installAccountExportMock(page, {
		exportId,
		selectedDomains: ['usage'],
		completeStatus: 'partial',
		failures: [{ domain: 'usage', item_id: 'usage-row-2', reason: 'mock_partial_failure' }],
	});
	await loginAndOpenExportSettings(page, log);
	await page.getByRole('button', { name: /deselect all/i }).click();
	await page.getByLabel(/usage history and credit transactions/i).check();

	await page.getByRole('button', { name: /export my data/i }).click();
	await expect(page.getByTestId('account-export-partial-message')).toBeVisible({ timeout: 30000 });
	expect(calls.some((call) => call.method === 'POST' && call.path === `/v1/account-exports/${exportId}/complete`)).toBe(true);

	const exportPath = testInfo.outputPath('account-export-partial.zip');
	const downloadPromise = page.waitForEvent('download', { timeout: 120000 });
	await page.getByTestId('account-export-accept-partial').click();
	const download = await downloadPromise;
	await download.saveAs(exportPath);

	expect(calls.some((call) => call.method === 'POST' && call.path === `/v1/account-exports/${exportId}/accept-partial`)).toBe(true);
	const zipBuffer = fs.readFileSync(exportPath);
	const entries = parseZipEntries(zipBuffer);
	const report = readZipEntry(zipBuffer, requireZipEntry(entries, 'export-report.yml'));
	expect(report).toContain('partial_accepted');
	runStandaloneArchiveVerifier(exportPath);
});
