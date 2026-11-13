/**
 * Learning Mode passcode helper (guest, client-side only).
 *
 * Purpose: hash and verify the guest Learning Mode passcode with WebCrypto
 * PBKDF2-SHA256 so the plain passcode is never persisted and the stored record
 * is never sent in any request.
 * Architecture: used by learningModeStore for browser-local guest records; the
 * account flow keeps its passcode on the backend and does not use this module.
 * Tests: frontend/packages/ui/src/services/__tests__/learningModePasscode.test.ts
 */

export const LEARNING_MODE_PASSCODE_MIN_LENGTH = 4;
export const LEARNING_MODE_PASSCODE_MAX_LENGTH = 128;
export const LEARNING_MODE_PBKDF2_ITERATIONS = 210_000;
const SALT_BYTES = 16;
const HASH_BITS = 256;

export interface LearningModePasscodeRecord {
	hash: string;
	salt: string;
	iterations: number;
	algorithm: 'pbkdf2_sha256';
}

export class LearningModePasscodeFormatError extends Error {
	constructor(message: string) {
		super(message);
		this.name = 'LearningModePasscodeFormatError';
	}
}

export function isValidLearningModePasscode(passcode: string): boolean {
	return passcode.length >= LEARNING_MODE_PASSCODE_MIN_LENGTH
		&& passcode.length <= LEARNING_MODE_PASSCODE_MAX_LENGTH;
}

function bytesToBase64(bytes: Uint8Array): string {
	let binary = '';
	for (const byte of bytes) binary += String.fromCharCode(byte);
	return btoa(binary);
}

function base64ToBytes(value: string): Uint8Array {
	const binary = atob(value);
	const bytes = new Uint8Array(binary.length);
	for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
	return bytes;
}

async function derive(passcode: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
	const subtle = globalThis.crypto?.subtle;
	if (!subtle) throw new Error('WebCrypto is unavailable; cannot protect the Learning Mode passcode');
	const key = await subtle.importKey('raw', new TextEncoder().encode(passcode), 'PBKDF2', false, ['deriveBits']);
	const bits = await subtle.deriveBits(
		{ name: 'PBKDF2', hash: 'SHA-256', salt: salt as BufferSource, iterations },
		key,
		HASH_BITS
	);
	return new Uint8Array(bits);
}

/** Compare two byte arrays without early exit on the first differing byte. */
export function constantTimeEqual(left: Uint8Array, right: Uint8Array): boolean {
	let diff = left.length ^ right.length;
	const length = Math.max(left.length, right.length);
	for (let index = 0; index < length; index += 1) {
		diff |= (left[index] ?? 0) ^ (right[index] ?? 0);
	}
	return diff === 0;
}

export async function createLearningModePasscodeRecord(passcode: string): Promise<LearningModePasscodeRecord> {
	if (!isValidLearningModePasscode(passcode)) {
		throw new LearningModePasscodeFormatError(
			`Passcode must be ${LEARNING_MODE_PASSCODE_MIN_LENGTH}-${LEARNING_MODE_PASSCODE_MAX_LENGTH} characters`
		);
	}
	const salt = globalThis.crypto.getRandomValues(new Uint8Array(SALT_BYTES));
	const hash = await derive(passcode, salt, LEARNING_MODE_PBKDF2_ITERATIONS);
	return {
		hash: bytesToBase64(hash),
		salt: bytesToBase64(salt),
		iterations: LEARNING_MODE_PBKDF2_ITERATIONS,
		algorithm: 'pbkdf2_sha256'
	};
}

export function isLearningModePasscodeRecord(value: unknown): value is LearningModePasscodeRecord {
	if (!value || typeof value !== 'object') return false;
	const record = value as Record<string, unknown>;
	return typeof record.hash === 'string'
		&& typeof record.salt === 'string'
		&& typeof record.iterations === 'number'
		&& Number.isInteger(record.iterations)
		&& record.iterations > 0
		&& record.algorithm === 'pbkdf2_sha256';
}

export async function verifyLearningModePasscode(
	passcode: string,
	record: LearningModePasscodeRecord
): Promise<boolean> {
	if (!isValidLearningModePasscode(passcode)) return false;
	const derived = await derive(passcode, base64ToBytes(record.salt), record.iterations);
	return constantTimeEqual(derived, base64ToBytes(record.hash));
}
