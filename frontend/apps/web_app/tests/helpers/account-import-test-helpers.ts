/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Shared Account Import V1 Playwright helpers.
 *
 * These helpers build synthetic provider exports and mock only the Account
 * Import V1 control-plane endpoints. Specs still run against the deployed web
 * shell, login, settings navigation, IndexedDB, and browser encryption path.
 * Fixtures must stay synthetic and safe for artifact scanning.
 */
export {};

const fs = require('fs');
const { expect } = require('../helpers/cookie-audit');
const { loginToTestAccount } = require('../helpers/chat-test-helpers');

type ImportMockCall = {
	method: string;
	path: string;
	body: Record<string, unknown> | null;
};

type ImportMockConfig = {
	importId?: string;
	defaultSelectionCount?: number;
	maxBatchCount?: number;
	freeRemaining?: number;
	duplicateFingerprints?: string[];
	estimatedCredits?: number;
	canImport?: boolean;
	reason?: string;
	scanFailures?: Array<Record<string, unknown>>;
	scanChats?: Array<Record<string, unknown>>;
	messagesBlocked?: Array<Record<string, unknown>>;
};

function buildClaudeExportJson(chatCount: number, options: { duplicateTitle?: string } = {}): string {
	const now = Date.UTC(2026, 6, 18, 12, 0, 0);
	return JSON.stringify(Array.from({ length: chatCount }, (_, index) => ({
		uuid: `claude-chat-${index + 1}`,
		name: options.duplicateTitle && index === 0 ? options.duplicateTitle : `Claude import chat ${index + 1}`,
		created_at: new Date(now + index * 60_000).toISOString(),
		updated_at: new Date(now + index * 60_000 + 30_000).toISOString(),
		chat_messages: [
			{
				uuid: `claude-message-${index + 1}-1`,
				sender: 'human',
				text: `Synthetic web import user message ${index + 1}`,
				created_at: new Date(now + index * 60_000).toISOString(),
			},
			{
				uuid: `claude-message-${index + 1}-2`,
				sender: 'assistant',
				text: `Synthetic web import assistant message ${index + 1}`,
				created_at: new Date(now + index * 60_000 + 30_000).toISOString(),
			},
		],
	})));
}

function crc32(buffer: Buffer): number {
	let crc = 0xffffffff;
	for (const byte of buffer) {
		crc ^= byte;
		for (let bit = 0; bit < 8; bit++) {
			crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
		}
	}
	return (crc ^ 0xffffffff) >>> 0;
}

function writeUInt16(value: number): Buffer {
	const buffer = Buffer.alloc(2);
	buffer.writeUInt16LE(value, 0);
	return buffer;
}

function writeUInt32(value: number): Buffer {
	const buffer = Buffer.alloc(4);
	buffer.writeUInt32LE(value >>> 0, 0);
	return buffer;
}

function buildZip(entries: Record<string, string>): Buffer {
	const localParts: Buffer[] = [];
	const centralParts: Buffer[] = [];
	let offset = 0;

	for (const [name, text] of Object.entries(entries)) {
		const nameBuffer = Buffer.from(name, 'utf8');
		const data = Buffer.from(text, 'utf8');
		const checksum = crc32(data);
		const localHeader = Buffer.concat([
			writeUInt32(0x04034b50),
			writeUInt16(20),
			writeUInt16(0),
			writeUInt16(0),
			writeUInt16(0),
			writeUInt16(0),
			writeUInt32(checksum),
			writeUInt32(data.length),
			writeUInt32(data.length),
			writeUInt16(nameBuffer.length),
			writeUInt16(0),
			nameBuffer,
		]);
		localParts.push(localHeader, data);
		centralParts.push(Buffer.concat([
			writeUInt32(0x02014b50),
			writeUInt16(20),
			writeUInt16(20),
			writeUInt16(0),
			writeUInt16(0),
			writeUInt16(0),
			writeUInt16(0),
			writeUInt32(checksum),
			writeUInt32(data.length),
			writeUInt32(data.length),
			writeUInt16(nameBuffer.length),
			writeUInt16(0),
			writeUInt16(0),
			writeUInt16(0),
			writeUInt16(0),
			writeUInt32(0),
			writeUInt32(offset),
			nameBuffer,
		]));
		offset += localHeader.length + data.length;
	}

	const centralDirectory = Buffer.concat(centralParts);
	const endOfCentralDirectory = Buffer.concat([
		writeUInt32(0x06054b50),
		writeUInt16(0),
		writeUInt16(0),
		writeUInt16(centralParts.length),
		writeUInt16(centralParts.length),
		writeUInt32(centralDirectory.length),
		writeUInt32(offset),
		writeUInt16(0),
	]);
	return Buffer.concat([...localParts, centralDirectory, endOfCentralDirectory]);
}

function buildOpenMatesExportZip(): Buffer {
	return buildZip({
		'manifest.yml': [
			'format: openmates-account-export',
			'version: 1',
			'domains:',
			'  chats: {}',
			'  embeds: {}',
			'  uploads: {}',
			'  projects: {}',
		].join('\n'),
		'chats/openmates-chat-1.yml': [
			'id: openmates-chat-1',
			'title: OpenMates imported fixture',
			"created_at: '2026-07-18T12:00:00Z'",
			"updated_at: '2026-07-18T12:01:00Z'",
			'messages:',
			'  - id: openmates-message-1',
			'    role: user',
			'    content: Synthetic OpenMates web import message',
		].join('\n'),
	});
}

async function installAccountImportMock(page: any, config: ImportMockConfig = {}): Promise<ImportMockCall[]> {
	const calls: ImportMockCall[] = [];
	const importId = config.importId ?? 'web-import-1';
	await page.route('**/v1/account-imports**', async (route: any) => {
		const request = route.request();
		const url = new URL(request.url());
		let body: Record<string, unknown> | null = null;
		try {
			body = request.postData() ? JSON.parse(request.postData() || '{}') : null;
		} catch {
			body = null;
		}
		calls.push({ method: request.method(), path: url.pathname, body });

		if (request.method() === 'POST' && url.pathname === '/v1/account-imports/preview') {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					import_id: importId,
					free_remaining: config.freeRemaining,
					default_selection_count: config.defaultSelectionCount ?? 1,
					max_batch_count: config.maxBatchCount ?? 1,
					duplicate_fingerprints: config.duplicateFingerprints ?? [],
					estimated_credits: config.estimatedCredits ?? 1,
					can_import: config.canImport ?? true,
					reason: config.reason ?? 'paid_import_available',
				}),
			});
			return;
		}

		if (request.method() === 'POST' && url.pathname === `/v1/account-imports/${importId}/scan`) {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					chats: config.scanChats ?? body?.chats ?? [],
					credits_reserved: config.estimatedCredits ?? 1,
					messages_blocked: config.messagesBlocked ?? [],
					failures: config.scanFailures ?? [],
				}),
			});
			return;
		}

		if (request.method() === 'POST' && url.pathname === `/v1/account-imports/${importId}/persist-encrypted`) {
			const chats = Array.isArray(body?.chats) ? body.chats as Array<Record<string, unknown>> : [];
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					status: 'complete',
					imported_chat_ids: chats.map((chat) => chat.chat_id).filter(Boolean),
					encrypted_record_counts: {
						chats: chats.length,
						messages: chats.reduce((count, chat) => count + (Array.isArray(chat.messages) ? chat.messages.length : 0), 0),
					},
					failures: [],
				}),
			});
			return;
		}

		if (request.method() === 'POST' && url.pathname === `/v1/account-imports/${importId}/complete`) {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					status: Array.isArray(body?.client_failures) && body.client_failures.length > 0 ? 'partial' : 'complete',
					imported_count: Array.isArray(body?.imported_chat_ids) ? body.imported_chat_ids.length : 0,
					credits_charged: 0,
					credits_released: 0,
					failures: body?.client_failures ?? [],
				}),
			});
			return;
		}

		await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: `Unhandled mock route ${request.method()} ${url.pathname}` }) });
	});
	return calls;
}

async function openImportSettings(page: any): Promise<void> {
	const settingsMenuButton = page.getByTestId('profile-container');
	await expect(settingsMenuButton).toBeVisible({ timeout: 15000 });
	await settingsMenuButton.click();

	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await settingsMenu.getByRole('menuitem', { name: /^account$/i }).click();
	await settingsMenu.getByRole('menuitem', { name: /import/i }).click();

	await expect(page.getByTestId('account-import-file-upload')).toBeVisible({ timeout: 15000 });
}

async function loginAndOpenImportSettings(page: any, credentials: Record<string, string>): Promise<void> {
	await loginToTestAccount(page, () => undefined, async () => undefined, { credentials });
	await openImportSettings(page);
}

async function uploadClaudeJson(page: any, chatCount: number, options: { duplicateTitle?: string } = {}): Promise<void> {
	await page.getByTestId('account-import-file-upload-input').setInputFiles({
		name: 'claude-export.json',
		mimeType: 'application/json',
		buffer: Buffer.from(buildClaudeExportJson(chatCount, options), 'utf8'),
	});
}

async function uploadOpenMatesZip(page: any): Promise<void> {
	await page.getByTestId('account-import-file-upload-input').setInputFiles({
		name: 'openmates-export.zip',
		mimeType: 'application/zip',
		buffer: buildOpenMatesExportZip(),
	});
}

function persistPayloads(calls: ImportMockCall[]): Array<Record<string, unknown>> {
	return calls
		.filter((call) => call.path.endsWith('/persist-encrypted'))
		.map((call) => call.body ?? {});
}

function writePersistArtifacts(testInfo: any, calls: ImportMockCall[], filename: string): string {
	const outputPath = testInfo.outputPath(filename);
	fs.writeFileSync(outputPath, JSON.stringify({ persist_payloads: persistPayloads(calls) }, null, 2));
	return outputPath;
}

module.exports = {
	buildClaudeExportJson,
	installAccountImportMock,
	loginAndOpenImportSettings,
	openImportSettings,
	persistPayloads,
	uploadClaudeJson,
	uploadOpenMatesZip,
	writePersistArtifacts,
};
