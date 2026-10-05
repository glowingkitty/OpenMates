/** Exact replay of legacy artifact diffs, shared by browser and CLI readers. */
import { applyProjectFilePatch } from './projectFilePatch.js';
export interface EncryptedVersionRow {
	version_number: number;
	encrypted_snapshot?: string | null;
	encrypted_patch?: string | null;
}

export async function reconstructVersionRows(
	rows: EncryptedVersionRow[],
	decrypt: (ciphertext: string) => Promise<string | null>,
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
			content = applyVersionPatch(content, patch);
		}
	}
	if (content === null) throw new Error('Version history is missing the initial snapshot');
	return content;
}

/** Legacy version writers represent text with split/join LF and optional file headers. */
export function applyVersionPatch(content: string, patch: string): string {
	if (patch.includes('\\ No newline at end of file')) {
		const withHeaders = patch.startsWith('@@ ') ? `--- version\n+++ version\n${patch}` : patch;
		return applyProjectFilePatch(content, withHeaders).content;
	}
	const source = content === '' ? [] : content.split('\n');
	const lines = patch.split('\n');
	if (lines.at(-1) === '') lines.pop();
	let index = 0;
	if (lines[0]?.startsWith('--- ') && lines[1]?.startsWith('+++ ')) index = 2;
	const output: string[] = [];
	let sourceIndex = 0;
	let hunkCount = 0;
	while (index < lines.length) {
		const header = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$/.exec(lines[index] ?? '');
		if (!header) throw new Error('Version patch contains an invalid hunk');
		const oldStart = Number(header[1]);
		const oldCount = header[2] === undefined ? 1 : Number(header[2]);
		const newStart = Number(header[3]);
		const newCount = header[4] === undefined ? 1 : Number(header[4]);
		const start = oldCount === 0 ? oldStart : oldStart - 1;
		const outputStart = newCount === 0 ? newStart : newStart - 1;
		if (![oldStart, oldCount, newStart, newCount].every(Number.isSafeInteger)
			|| start < sourceIndex || start > source.length) throw new Error('Version patch hunks overlap or exceed content');
		output.push(...source.slice(sourceIndex, start));
		if (output.length !== outputStart) throw new Error('Version patch coordinates do not match content');
		sourceIndex = start;
		let removed = 0;
		let added = 0;
		index += 1;
		while (index < lines.length && !lines[index]?.startsWith('@@ ')) {
			const line = lines[index] ?? '';
			if (line === '\\ No newline at end of file') {
				// Legacy writers omit these markers; LF shape is preserved by split/join.
				index += 1;
				continue;
			}
			if (![' ', '-', '+'].includes(line[0] ?? '')) throw new Error('Version patch has an invalid line');
			if (line[0] !== '+') {
				if (source[sourceIndex] !== line.slice(1)) throw new Error('Version patch context does not match local content');
				sourceIndex += 1;
				removed += 1;
			}
			if (line[0] !== '-') {
				output.push(line.slice(1));
				added += 1;
			}
			index += 1;
		}
		if (removed !== oldCount || added !== newCount) throw new Error('Version patch line counts do not match its header');
		hunkCount += 1;
	}
	if (hunkCount === 0) throw new Error('Version patch has no hunks');
	output.push(...source.slice(sourceIndex));
	return output.join('\n');
}
