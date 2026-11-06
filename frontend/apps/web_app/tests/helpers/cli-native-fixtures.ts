/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * Fixture helpers for the cli-native-*.spec.ts differential specs.
 *
 * Each CLI creates and cleans up its own throwaway objects (projects, Tasks,
 * Teams, chats) so mutating commands can be compared with `nativeArgs`. These
 * helpers only parse CLI JSON output; they never print secrets.
 */
export {};

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

type RunResult = { code: number | null; stdout: string; stderr: string };

/** Parse CLI JSON stdout; returns null when stdout is not JSON. */
function parseJson(result: RunResult): any {
	try {
		return JSON.parse(result.stdout.trim());
	} catch {
		return null;
	}
}

/**
 * Find the first string value under one of `keys` (breadth-first, in key order),
 * so `{project: {id}}` and `{id}` both resolve. Returns '' when absent.
 */
function pickString(value: any, keys: string[]): string {
	const queue: any[] = [value];
	while (queue.length) {
		const node = queue.shift();
		if (!node || typeof node !== 'object') continue;
		if (!Array.isArray(node)) {
			for (const key of keys) {
				const found = node[key];
				if (typeof found === 'string' && found) return found;
			}
		}
		for (const child of Object.values(node)) if (child && typeof child === 'object') queue.push(child);
	}
	return '';
}

/** The first UUID found under one of `keys`, or anywhere in the output as a last resort. */
function pickId(result: RunResult, keys: string[]): string {
	const parsed = parseJson(result);
	const direct = parsed ? pickString(parsed, keys) : '';
	if (direct) return direct;
	return result.stdout.match(UUID)?.[0] ?? '';
}

/** Per-CLI fixture ids from a check record's raw results. */
function bothIds(record: { raw?: { npm: RunResult; native: RunResult } }, keys: string[]): { npm: string; native: string } {
	if (!record.raw) return { npm: '', native: '' };
	return { npm: pickId(record.raw.npm, keys), native: pickId(record.raw.native, keys) };
}

/** Messages (`{id, role}`) found anywhere in a CLI JSON output, in document order. */
function findMessages(result: RunResult): Array<{ id: string; role: string }> {
	const out: Array<{ id: string; role: string }> = [];
	const walk = (node: any): void => {
		if (Array.isArray(node)) return node.forEach(walk);
		if (!node || typeof node !== 'object') return;
		const id = node.message_id ?? node.messageId ?? node.id;
		if (typeof node.role === 'string' && typeof id === 'string') out.push({ id, role: node.role });
		Object.values(node).forEach(walk);
	};
	walk(parseJson(result));
	return out;
}

/** Assert-free summary for spec failure messages (no secrets in CLI output). */
function describeRun(label: string, result: RunResult): string {
	return `${label}: exit=${result.code}\nstdout=${result.stdout.slice(0, 800)}\nstderr=${result.stderr.slice(0, 800)}`;
}

module.exports = { bothIds, describeRun, findMessages, parseJson, pickId, pickString };
