/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) Account Import V1 parsing: the page adapter
 * over the shared Rust core Worker `transfer` unit. Loaded only by the guarded
 * branches of chatImportService.ts, so default builds never bundle it.
 *
 * Rust (web_transfer*.rs, shared with the CLI importer) decides: file and ZIP
 * routing, provider detection, every export's parsing and normalization,
 * source fingerprints, newest-first order, error text, per-chat cost estimate
 * inputs and scan batch boundaries. The page keeps only browser primitives:
 * File reads, JSZip, YAML text parsing and the selected chat objects.
 * The public functions keep the TypeScript service's signatures and errors.
 */
import JSZip from 'jszip';
import { parse } from 'yaml';
import type {
	AccountImportSource, ImportCostEstimate, ImportProgressCallback, ParsedAccountImport, ParsedImportChat,
} from '../../chatImportService';
import type { TransferChatEstimate, TransferParsed } from './transferProtocol';
import { transferCall } from './transferUnitClient';

/** Large exports parse for longer than the unit port's 30 s default. */
const PARSE_TIMEOUT_MS = 10 * 60 * 1000;

/**
 * Rust-computed `[tokens, messages]` per source fingerprint of the latest parse.
 * Keyed by fingerprint (not object identity) so Svelte state proxies of the
 * same chats still resolve; equal fingerprints hash equal content.
 */
const chatEstimates = new Map<string, TransferChatEstimate>();

/** `Date.parse` of offset-less timestamps is local time on the page. */
function utcOffsetMinutes(): number {
	return -new Date().getTimezoneOffset();
}

function accept(result: TransferParsed): ParsedAccountImport {
	if (result.kind === 'error') throw new Error(result.message);
	chatEstimates.clear();
	result.parsed.chats.forEach((chat, index) => chatEstimates.set(chat.source_fingerprint, result.estimates[index]));
	return result.parsed;
}

async function parseText(
	text: string, container: 'json' | 'zip', fileName: string, selectedSource: AccountImportSource | undefined,
): Promise<ParsedAccountImport> {
	const result = await transferCall('parseJson', {
		meta: { fileName, container, selectedSource: selectedSource ?? null, utcOffsetMinutes: utcOffsetMinutes() },
		text,
	}, { timeoutMs: PARSE_TIMEOUT_MS });
	if (result.kind === 'syntax') {
		// Rethrow the browser's own SyntaxError so the message is unchanged.
		JSON.parse(text);
		throw new Error('rust_transfer_json_unsupported');
	}
	return accept(result);
}

async function readYaml(zip: JSZip, name: string): Promise<unknown> {
	return parse(await zip.files[name].async('string'));
}

export async function rustParseImportFile(
	file: File, selectedSource: AccountImportSource | undefined, onProgress: ImportProgressCallback | undefined,
): Promise<ParsedAccountImport> {
	onProgress?.('parsing', 'Reading import file...');
	const route = await transferCall('importRoute', { fileName: file.name });
	if (route.kind === 'error') throw new Error(route.message);
	if (route.kind === 'json') return parseText(await file.text(), 'json', file.name, selectedSource);

	const payload = await file.arrayBuffer();
	let zip: JSZip;
	try {
		zip = await JSZip.loadAsync(payload);
	} catch (error) {
		throw new Error(`Cannot read ZIP file: ${error instanceof Error ? error.message : String(error)}`);
	}
	const plan = await transferCall('zipPlan', { entries: Object.values(zip.files).map((entry) => ({ name: entry.name, dir: entry.dir })) });
	if (plan.kind === 'error') throw new Error(plan.message);
	if (plan.kind === 'conversations') return parseText(await zip.files[plan.name].async('string'), 'zip', file.name, selectedSource);

	// Same read order as the TypeScript parser so YAML errors surface identically.
	const manifest = await readYaml(zip, 'manifest.yml');
	const checked = await transferCall('openmatesManifest', { manifest });
	if (checked.kind === 'error') throw new Error(checked.message);
	const embeds: unknown[] = [];
	for (const name of plan.embeds) embeds.push(await readYaml(zip, name));
	const uploads: unknown[] = [];
	for (const name of plan.uploads) uploads.push(await readYaml(zip, name));
	const chats: Array<{ name: string; value: unknown }> = [];
	for (const name of plan.chats) chats.push({ name, value: await readYaml(zip, name) });
	return accept(await transferCall('parseOpenMates', {
		manifest, chats, embeds, uploads, fileName: file.name, selectedSource: selectedSource ?? null, utcOffsetMinutes: utcOffsetMinutes(),
	}, { timeoutMs: PARSE_TIMEOUT_MS }));
}

/** `estimateImportCost` over the Rust per-chat estimates of the latest parse. */
export function rustEstimateImportCost(chats: ParsedImportChat[]): ImportCostEstimate {
	let totalInputTokens = 0;
	let messageCount = 0;
	for (const chat of chats) {
		const estimate = chatEstimates.get(chat.source_fingerprint);
		if (!estimate) throw new Error('rust_transfer_unparsed_chat');
		totalInputTokens += estimate[0];
		messageCount += estimate[1];
	}
	return { totalInputTokens, estimatedCredits: chats.length, chatCount: chats.length, messageCount };
}

/** `buildMessageBatches` with Rust-decided boundaries and batch ids. */
export async function rustBuildMessageBatches(chats: ParsedImportChat[], maxMessages: number): Promise<Array<{
	chatIndex: number; chunkIndex: number; sourceFingerprint: string; batchId: string; chat: ParsedImportChat;
}>> {
	const plan = await transferCall('batchPlan', {
		chats: chats.map((chat) => ({ fingerprint: chat.source_fingerprint, messageCount: chat.messages.length })),
		maxMessages,
	});
	if (plan.kind === 'error') throw new Error(plan.message);
	return plan.batches.map(([chatIndex, chunkIndex, start, end, batchId]) => {
		const chat = chats[chatIndex];
		return { chatIndex, chunkIndex, sourceFingerprint: chat.source_fingerprint, batchId, chat: { ...chat, messages: chat.messages.slice(start, end) } };
	});
}
