import { describe, expect, it } from 'vitest';
import { applyVersionPatch, reconstructVersionRows } from '../embedVersionReconstruction';

// contract-test: supporting surface=gui.web assertions=storage.versions.bounded-reconstruction
describe('exact artifact version replay shared with the CLI', () => {
	// contract-test: supporting surface=gui.web assertions=storage.versions.bounded-reconstruction
	it('inserts at the beginning and after the declared line for zero-count hunks', () => {
		expect(applyVersionPatch('first\nlast', '@@ -0,0 +1 @@\n+new')).toBe('new\nfirst\nlast');
		expect(applyVersionPatch('first\nlast', '@@ -1,0 +2 @@\n+new')).toBe('first\nnew\nlast');
		expect(applyVersionPatch('', '@@ -0,0 +1 @@\n+new')).toBe('new');
	});

	// contract-test: supporting surface=gui.web assertions=storage.versions.bounded-reconstruction
	it('preserves legacy LF endings and explicit no-newline markers', () => {
		expect(applyVersionPatch('old\n', '@@ -1,2 +1,2 @@\n-old\n-\n+new\n+')).toBe('new\n');
		expect(applyVersionPatch('old\n', '@@ -1 +1 @@\n-old\n+new\n\\ No newline at end of file')).toBe('new');
		expect(applyVersionPatch('old', '@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new')).toBe('new\n');
	});

	// contract-test: supporting surface=gui.web assertions=storage.versions.bounded-reconstruction
	it('rejects truncated, overlapping and mismatched hunks', () => {
		for (const patch of ['', 'not a diff', '@@ -1,2 +1 @@\n-old\n+new',
			'@@ -1 +1 @@\n-wrong\n+new', '@@ -1 +1 @@\n-old\n+new\n@@ -1 +1 @@\n-old\n+again']) {
			expect(() => applyVersionPatch('old', patch)).toThrow();
		}
	});

	// contract-test: supporting surface=gui.web assertions=storage.versions.bounded-reconstruction
	it('uses a periodic snapshot and contiguous patches', async () => {
		const rows = [{ version_number: 32, encrypted_snapshot: 'old' },
			{ version_number: 33, encrypted_patch: '@@ -1 +1 @@\n-old\n+new' }];
		await expect(reconstructVersionRows(rows, async (value) => value)).resolves.toBe('new');
	});

	// contract-test: supporting surface=gui.web assertions=storage.versions.bounded-reconstruction
	it('rejects missing rows, duplicate versions, missing patches and failed decryption', async () => {
		for (const rows of [[], [{ version_number: 1, encrypted_snapshot: 'old' }, { version_number: 3, encrypted_patch: 'patch' }],
			[{ version_number: 1, encrypted_snapshot: 'old' }, { version_number: 1, encrypted_snapshot: 'new' }],
			[{ version_number: 1, encrypted_snapshot: 'old' }, { version_number: 2 }]]) {
			await expect(reconstructVersionRows(rows, async (value) => value)).rejects.toThrow();
		}
		await expect(reconstructVersionRows([{ version_number: 1, encrypted_snapshot: 'bad' }], async () => null))
			.rejects.toThrow('snapshot could not be decrypted');
		await expect(reconstructVersionRows([{ version_number: 1, encrypted_snapshot: 'old' },
			{ version_number: 2, encrypted_patch: 'bad' }], async (value) => value === 'bad' ? null : value))
			.rejects.toThrow('patch could not be decrypted');
	});
});
