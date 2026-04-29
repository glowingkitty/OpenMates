/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Chat encryption invariant helpers for Playwright E2E tests.
 *
 * These assertions inspect client-side IndexedDB and window.inspectChat output.
 * They catch mixed-key corruption before it only appears as UI decryption errors.
 * The checks are diagnostic only and never expose key material in failure output.
 *
 * Architecture context: docs/architecture/e2e-testing.md
 */
export {};

const { expect } = require('@playwright/test');

const CHAT_KEY_FIELDS = [
	'encrypted_title',
	'encrypted_category',
	'encrypted_icon',
	'encrypted_chat_summary',
	'encrypted_chat_tags',
	'encrypted_follow_up_request_suggestions',
	'encrypted_active_focus_id'
];

type FingerprintEntry = {
	store: 'chat' | 'message';
	field: string;
	fingerprint: string;
	id?: string;
};

type ChatKeyInvariantReport = {
	chatId: string;
	keyFingerprint: string | null;
	keyHeaderFingerprint: string | null;
	storedKeyFingerprint: string | null;
	candidateKeyCount: number;
	fingerprints: FingerprintEntry[];
	legacyCiphertextCount: number;
	mismatchedFingerprints: FingerprintEntry[];
	missingChat: boolean;
	inspectError?: string;
};

function getKeyHexFromInspectReport(report: string): string | null {
	const keyLine = report.split('\n').find((line) => line.startsWith('Key:'));
	if (!keyLine) return null;
	const match = keyLine.match(/^Key:\s+([0-9a-f]{64})\b/i);
	return match ? match[1].toLowerCase() : null;
}

function computeHeaderFingerprintFromKeyHex(keyHex: string): string {
	let hash = 0x811c9dc5;
	for (let i = 0; i < keyHex.length; i += 2) {
		hash ^= parseInt(keyHex.slice(i, i + 2), 16);
		hash = Math.imul(hash, 0x01000193);
	}
	return (hash >>> 0).toString(16).padStart(8, '0');
}

async function getChatKeyInvariantReport(page: any, chatId: string): Promise<ChatKeyInvariantReport> {
	return await page.evaluate(
		async ({ id, chatKeyFields }: { id: string; chatKeyFields: string[] }) => {
			const report: ChatKeyInvariantReport = {
				chatId: id,
				keyFingerprint: null,
				keyHeaderFingerprint: null,
				storedKeyFingerprint: null,
				candidateKeyCount: 0,
				fingerprints: [],
				legacyCiphertextCount: 0,
				mismatchedFingerprints: [],
				missingChat: false
			};

			const inspectChat = (window as any).inspectChat;
			if (typeof inspectChat === 'function') {
				try {
					const rawInspectReport = await inspectChat(id, { hideKeys: false });
					const keyLine = String(rawInspectReport)
						.split('\n')
						.find((line) => line.startsWith('Key:'));
					const keyMatch = keyLine?.match(/^Key:\s+([0-9a-f]{64})\b/i);
					if (keyMatch) {
						const keyHex = keyMatch[1].toLowerCase();
						report.keyFingerprint = keyHex.slice(0, 16);

						let hash = 0x811c9dc5;
						for (let i = 0; i < keyHex.length; i += 2) {
							hash ^= parseInt(keyHex.slice(i, i + 2), 16);
							hash = Math.imul(hash, 0x01000193);
						}
						report.keyHeaderFingerprint = (hash >>> 0).toString(16).padStart(8, '0');
					}
				} catch (error) {
					report.inspectError = error instanceof Error ? error.message : String(error);
				}
			}

			const db = await new Promise<IDBDatabase>((resolve, reject) => {
				const request = indexedDB.open('chats_db');
				request.onerror = () => reject(request.error);
				request.onsuccess = () => resolve(request.result);
			});

			const getChat = () =>
				new Promise<Record<string, any> | undefined>((resolve, reject) => {
					const tx = db.transaction('chats', 'readonly');
					const store = tx.objectStore('chats');
					const request = store.get(id);
					request.onerror = () => reject(request.error);
					request.onsuccess = () => resolve(request.result);
				});

			const getMessages = () =>
				new Promise<Record<string, any>[]>((resolve, reject) => {
					const tx = db.transaction('messages', 'readonly');
					const store = tx.objectStore('messages');
					const index = store.index('chat_id');
					const request = index.getAll(id);
					request.onerror = () => reject(request.error);
					request.onsuccess = () => resolve(request.result || []);
				});

			const fingerprintFromCiphertext = (value: unknown): string | null => {
				if (typeof value !== 'string' || value.length === 0) return null;
				try {
					const binary = atob(value);
					if (binary.length < 6) return null;
					if (binary.charCodeAt(0) !== 0x4f || binary.charCodeAt(1) !== 0x4d) {
						report.legacyCiphertextCount += 1;
						return null;
					}
					return Array.from(binary.slice(2, 6))
						.map((char) => char.charCodeAt(0).toString(16).padStart(2, '0'))
						.join('');
				} catch {
					return null;
				}
			};

			try {
				const [chat, messages] = await Promise.all([getChat(), getMessages()]);
				if (!chat) {
					report.missingChat = true;
					return report;
				}

				report.storedKeyFingerprint =
					typeof chat.key_fingerprint === 'string' ? chat.key_fingerprint : null;
				report.candidateKeyCount = Array.isArray(chat.candidate_encrypted_keys)
					? chat.candidate_encrypted_keys.length
					: 0;

				for (const field of chatKeyFields) {
					const fingerprint = fingerprintFromCiphertext(chat[field]);
					if (fingerprint) {
						report.fingerprints.push({ store: 'chat', field, fingerprint });
					}
				}

				for (const message of messages) {
					const fingerprint = fingerprintFromCiphertext(message.encrypted_content);
					if (fingerprint) {
						report.fingerprints.push({
							store: 'message',
							field: 'encrypted_content',
							fingerprint,
							id: message.message_id || message.id
						});
					}
				}
			} finally {
				db.close();
			}

			if (report.keyHeaderFingerprint) {
				report.mismatchedFingerprints = report.fingerprints.filter(
					(entry) => entry.fingerprint !== report.keyHeaderFingerprint
				);
			}

			return report;
		},
		{ id: chatId, chatKeyFields: CHAT_KEY_FIELDS }
	);
}

async function assertChatKeyInvariants(
	page: any,
	chatId: string,
	phase: string,
	logFn: (msg: string) => void = () => {}
): Promise<ChatKeyInvariantReport> {
	const report = await getChatKeyInvariantReport(page, chatId);
	logFn(
		`[${phase}] Chat key invariant report: key=${report.keyFingerprint ?? 'N/A'} ` +
			`ciphertextFp=${report.keyHeaderFingerprint ?? 'N/A'} ` +
			`fields=${report.fingerprints.length} candidates=${report.candidateKeyCount} ` +
			`legacy=${report.legacyCiphertextCount}`
	);

	if (report.inspectError) {
		logFn(`[${phase}] inspectChat error while checking key invariants: ${report.inspectError}`);
	}

	expect(report.missingChat).toBe(false);
	expect(report.keyFingerprint).toBeTruthy();
	expect(report.keyHeaderFingerprint).toBeTruthy();
	expect(report.fingerprints.length).toBeGreaterThan(0);
	expect(report.mismatchedFingerprints).toEqual([]);
	expect(report.candidateKeyCount).toBe(0);

	return report;
}

module.exports = {
	assertChatKeyInvariants,
	computeHeaderFingerprintFromKeyHex,
	getChatKeyInvariantReport,
	getKeyHexFromInspectReport
};
