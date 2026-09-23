/** A deliberately small, exact unified-diff applier shared by browser previews and the CLI. */

export interface AppliedProjectFilePatch {
	content: string;
	appliedDiff: string;
	oldPath: string;
	newPath: string;
}

export class ProjectFilePatchError extends Error {
	constructor(message: string) {
		super(message);
		this.name = 'ProjectFilePatchError';
	}
}

interface PatchLine {
	value: string;
	hasNewline: boolean;
}

interface PatchHunk {
	oldStart: number;
	oldCount: number;
	newStart: number;
	newCount: number;
	lines: Array<{ kind: 'context' | 'remove' | 'add'; line: PatchLine }>;
}

const HEADER = /^(---|\+\+\+) ([^\t]+)(?:\t.*)?$/;
const HUNK = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$/;

/**
 * Apply one-file unified diff hunks only at their declared line positions.
 * Context, counts, ordering and final-newline markers must all match exactly.
 */
export function applyProjectFilePatch(
	original: string,
	unifiedDiff: string,
	expectedPath?: string,
): AppliedProjectFilePatch {
	if (!unifiedDiff || unifiedDiff.includes('\0') || unifiedDiff.includes('\r')) {
		throw new ProjectFilePatchError('Patch must be a non-empty LF unified diff');
	}
	const rows = unifiedDiff.split('\n');
	if (rows.at(-1) === '') rows.pop();
	if (rows.length < 3) throw new ProjectFilePatchError('Patch is missing file headers or hunks');

	const oldHeader = HEADER.exec(rows[0] ?? '');
	const newHeader = HEADER.exec(rows[1] ?? '');
	if (!oldHeader || oldHeader[1] !== '---' || !newHeader || newHeader[1] !== '+++') {
		throw new ProjectFilePatchError('Patch must start with one old and one new file header');
	}
	const oldPath = normalizeHeaderPath(oldHeader[2] ?? '');
	const newPath = normalizeHeaderPath(newHeader[2] ?? '');
	if (oldPath === '/dev/null' || newPath === '/dev/null') {
		throw new ProjectFilePatchError('Update patches cannot create or delete files');
	}
	if (expectedPath && (oldPath !== expectedPath || newPath !== expectedPath)) {
		throw new ProjectFilePatchError('Patch file headers do not match the requested path');
	}

	const hunks: PatchHunk[] = [];
	let row = 2;
	while (row < rows.length) {
		const match = HUNK.exec(rows[row] ?? '');
		if (!match) throw new ProjectFilePatchError('Patch contains data outside a valid hunk');
		const hunk: PatchHunk = {
			oldStart: parseCoordinate(match[1]),
			oldCount: match[2] === undefined ? 1 : parseCoordinate(match[2]),
			newStart: parseCoordinate(match[3]),
			newCount: match[4] === undefined ? 1 : parseCoordinate(match[4]),
			lines: [],
		};
		row += 1;
		let oldSeen = 0;
		let newSeen = 0;
		while (row < rows.length && !rows[row]?.startsWith('@@ ')) {
			const value = rows[row] ?? '';
			if (value === '\\ No newline at end of file') {
				const previous = hunk.lines.at(-1);
				if (!previous || !previous.line.hasNewline) {
					throw new ProjectFilePatchError('Misplaced no-newline marker');
				}
				previous.line.hasNewline = false;
				row += 1;
				continue;
			}
			const prefix = value[0];
			if (prefix !== ' ' && prefix !== '-' && prefix !== '+') {
				throw new ProjectFilePatchError('Every hunk line must have a unified-diff prefix');
			}
			const kind = prefix === ' ' ? 'context' : prefix === '-' ? 'remove' : 'add';
			hunk.lines.push({ kind, line: { value: value.slice(1), hasNewline: true } });
			if (kind !== 'add') oldSeen += 1;
			if (kind !== 'remove') newSeen += 1;
			row += 1;
		}
		if (oldSeen !== hunk.oldCount || newSeen !== hunk.newCount) {
			throw new ProjectFilePatchError('Hunk line counts do not match its header');
		}
		hunks.push(hunk);
	}
	if (hunks.length === 0) throw new ProjectFilePatchError('Patch has no hunks');

	const source = splitContentLines(original);
	const output: PatchLine[] = [];
	let sourceIndex = 0;
	let outputLine = 1;
	for (const hunk of hunks) {
		const expectedSourceIndex = hunk.oldCount === 0 ? hunk.oldStart : hunk.oldStart - 1;
		const expectedOutputLine = hunk.newCount === 0 ? hunk.newStart + 1 : hunk.newStart;
		if (expectedSourceIndex < sourceIndex || expectedSourceIndex > source.length) {
			throw new ProjectFilePatchError('Patch hunks overlap or are outside the source');
		}
		while (sourceIndex < expectedSourceIndex) {
			output.push(source[sourceIndex] as PatchLine);
			sourceIndex += 1;
			outputLine += 1;
		}
		if (outputLine !== expectedOutputLine) {
			throw new ProjectFilePatchError('Patch new-file coordinates are inconsistent');
		}
		for (const item of hunk.lines) {
			if (item.kind !== 'add') {
				const actual = source[sourceIndex];
				if (!actual || actual.value !== item.line.value || actual.hasNewline !== item.line.hasNewline) {
					throw new ProjectFilePatchError('Patch context does not match the source exactly');
				}
				sourceIndex += 1;
			}
			if (item.kind !== 'remove') {
				output.push({ ...item.line });
				outputLine += 1;
			}
		}
	}
	output.push(...source.slice(sourceIndex));
	validateNewlinePlacement(output);
	return {
		content: output.map((line) => line.value + (line.hasNewline ? '\n' : '')).join(''),
		appliedDiff: unifiedDiff,
		oldPath,
		newPath,
	};
}

function parseCoordinate(value: string | undefined): number {
	const number = Number(value);
	if (!Number.isSafeInteger(number) || number < 0) throw new ProjectFilePatchError('Invalid hunk coordinate');
	return number;
}

function normalizeHeaderPath(value: string): string {
	if (value === '/dev/null') return value;
	if (value.startsWith('a/') || value.startsWith('b/')) return value.slice(2);
	return value;
}

function splitContentLines(content: string): PatchLine[] {
	if (content === '') return [];
	const lines: PatchLine[] = [];
	let start = 0;
	for (let index = 0; index < content.length; index += 1) {
		if (content[index] !== '\n') continue;
		lines.push({ value: content.slice(start, index), hasNewline: true });
		start = index + 1;
	}
	if (start < content.length) lines.push({ value: content.slice(start), hasNewline: false });
	return lines;
}

function validateNewlinePlacement(lines: PatchLine[]): void {
	for (let index = 0; index < lines.length - 1; index += 1) {
		if (!lines[index]?.hasNewline) throw new ProjectFilePatchError('No-newline marker is only valid at end of file');
	}
}
