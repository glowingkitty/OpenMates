/**
 * A phone match never lies inside a dotted version number: lockfile versions
 * such as "1.0.30001690" stay intact, as in the Rust core detector, while long
 * digit runs (IBANs) are still redacted.
 */
import { describe, expect, it } from 'vitest';
import { detectPII } from '../piiDetectionService';

describe('phone detection and version numbers', () => {
	// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
	it('leaves dotted versions of a lockfile untouched', () => {
		// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
		const lock = '"caniuse-lite": "^1.0.30001690", "electron-to-chromium": "1.5.0076543210",';
		expect(detectPII(lock).filter((match) => match.type === 'PHONE')).toEqual([]);
	});

	// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
	it('still detects real local phone numbers', () => {
		// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
		const phones = detectPII('call 030 1234 5678 or 0171-123-4567').filter((match) => match.type === 'PHONE');
		expect(phones.map((match) => match.match)).toEqual(['030 1234 5678', '0171-123-4567']);
	});

	// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
	it('still redacts every part of a long digit run such as an IBAN', () => {
		const phones = detectPII('DE89370400440532013000').filter((match) => match.type === 'PHONE');
		expect(phones.map((match) => match.match)).toEqual(['8937040044', '0532013000']);
	});
});
