/**
 * Flag-on version-history replay: the same chain walk as
 * utils/embedVersionReconstruction.ts `reconstructVersionRows` (kept byte-identical
 * for the flag-off build), with every patch applied by the shared Rust
 * `embed_read::patch` in the Worker. Decryption stays with the caller.
 */
import type { EncryptedVersionRow } from '../../../utils/embedVersionReconstruction';
import { applyVersionPatchInRust } from './embedDataClient';

export async function reconstructVersionRowsInRust(
	rows: EncryptedVersionRow[],
	decrypt: (ciphertext: string) => Promise<string | null>,
	typescriptPatch: (content: string, patch: string) => string
): Promise<string> {
	const sorted = [...rows].sort((a, b) => a.version_number - b.version_number);
	let content: string | null = null;
	let expected = sorted[0]?.version_number ?? 1;
	for (const row of sorted) {
		if (!Number.isSafeInteger(row.version_number) || row.version_number < 1 || row.version_number !== expected) {
			throw new Error('Version chain is incomplete');
		}
		expected += 1;
		if (row.encrypted_snapshot) {
			content = await decrypt(row.encrypted_snapshot);
			if (content === null) throw new Error('Version snapshot could not be decrypted');
		} else {
			if (content === null) throw new Error('Version history is missing the initial snapshot');
			if (!row.encrypted_patch) throw new Error('Version patch is missing');
			const patch = await decrypt(row.encrypted_patch);
			if (patch === null) throw new Error('Version patch could not be decrypted');
			// Null only when the Rust crypto arm is inactive (documented TS arm); Rust refusals reject.
			content = (await applyVersionPatchInRust(content, patch)) ?? typescriptPatch(content, patch);
		}
	}
	if (content === null) throw new Error('Version history is missing the initial snapshot');
	return content;
}
