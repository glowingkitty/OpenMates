import { webcrypto } from 'node:crypto';
import { beforeAll, describe, expect, it } from 'vitest';

import {
	LEARNING_MODE_PASSCODE_MAX_LENGTH,
	LEARNING_MODE_PBKDF2_ITERATIONS,
	LearningModePasscodeFormatError,
	constantTimeEqual,
	createLearningModePasscodeRecord,
	isLearningModePasscodeRecord,
	isValidLearningModePasscode,
	verifyLearningModePasscode
} from '../learningModePasscode';

// The shared test setup mocks crypto; guest passcode hashing needs the real WebCrypto.
beforeAll(() => {
	Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
});

describe('learningModePasscode', () => {
	// contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
	it('creates a PBKDF2-SHA256 record with a random 16-byte salt', async () => {
		const first = await createLearningModePasscodeRecord('correct-horse');
		const second = await createLearningModePasscodeRecord('correct-horse');

		expect(first.algorithm).toBe('pbkdf2_sha256');
		expect(first.iterations).toBe(210_000);
		expect(LEARNING_MODE_PBKDF2_ITERATIONS).toBe(210_000);
		expect(atob(first.salt)).toHaveLength(16);
		expect(atob(first.hash)).toHaveLength(32);
		expect(first.salt).not.toBe(second.salt);
		expect(first.hash).not.toBe(second.hash);
		expect(JSON.stringify(first)).not.toContain('correct-horse');
		expect(isLearningModePasscodeRecord(first)).toBe(true);
	});

	// contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
	it('verifies the right passcode and rejects wrong ones', async () => {
		const record = await createLearningModePasscodeRecord('correct-horse');

		await expect(verifyLearningModePasscode('correct-horse', record)).resolves.toBe(true);
		await expect(verifyLearningModePasscode('wrong-horse', record)).resolves.toBe(false);
		await expect(verifyLearningModePasscode('abc', record)).resolves.toBe(false);
	});

	// contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
	it('enforces passcode length bounds of 4 to 128 characters', async () => {
		expect(isValidLearningModePasscode('abc')).toBe(false);
		expect(isValidLearningModePasscode('abcd')).toBe(true);
		expect(isValidLearningModePasscode('x'.repeat(LEARNING_MODE_PASSCODE_MAX_LENGTH))).toBe(true);
		expect(isValidLearningModePasscode('x'.repeat(LEARNING_MODE_PASSCODE_MAX_LENGTH + 1))).toBe(false);
		await expect(createLearningModePasscodeRecord('abc')).rejects.toBeInstanceOf(LearningModePasscodeFormatError);
	});

	// contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
	it('compares bytes in constant time semantics', () => {
		expect(constantTimeEqual(new Uint8Array([1, 2, 3]), new Uint8Array([1, 2, 3]))).toBe(true);
		expect(constantTimeEqual(new Uint8Array([1, 2, 3]), new Uint8Array([1, 2, 4]))).toBe(false);
		expect(constantTimeEqual(new Uint8Array([1, 2, 3]), new Uint8Array([1, 2]))).toBe(false);
	});

	// contract-test: supporting surface=gui.web assertions=learning-mode.anonymous-client-side
	it('rejects malformed records', () => {
		expect(isLearningModePasscodeRecord(null)).toBe(false);
		expect(isLearningModePasscodeRecord({ hash: 'a', salt: 'b', iterations: 0, algorithm: 'pbkdf2_sha256' })).toBe(false);
		expect(isLearningModePasscodeRecord({ hash: 'a', salt: 'b', iterations: 1, algorithm: 'md5' })).toBe(false);
	});
});
