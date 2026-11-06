/**
 * `transfer` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * Chat import routing, parsing and normalization run in shared Rust
 * (packages/openmates-rust/src/web_transfer*.rs, the same parsers the CLI uses).
 * The page keeps the file picker, File/JSZip reads, YAML text parsing, Fetch,
 * encryption and IndexedDB; it sends file names, entry lists, export text or
 * already-parsed YAML values and gets the parsed import back. Parse failures are
 * successful `{kind:'error', message}` answers so the user sees the web
 * service's exact text; only malformed payloads refuse with `protocol`.
 */
import type { UnitProtocol } from '../host/unitPort';
import type { AccountImportSource, ParsedAccountImport } from '../../chatImportService';

export type TransferError = { kind: 'error'; message: string };
/** `[estimatedTokens, nonBlankMessages]` per parsed chat (estimateImportCost inputs). */
export type TransferChatEstimate = [number, number];
export type TransferParsed = { kind: 'ok'; parsed: ParsedAccountImport; estimates: TransferChatEstimate[] } | TransferError;
export type TransferRoute = { kind: 'json' } | { kind: 'zip' } | TransferError;
export type TransferZipPlan =
	| { kind: 'conversations'; name: string }
	| { kind: 'openmates'; embeds: string[]; uploads: string[]; chats: string[] }
	| TransferError;
/** `[chatIndex, chunkIndex, start, end, batchId]` (buildMessageBatches). */
export type TransferBatch = [number, number, number, number, string];

export interface TransferParseMeta {
	fileName: string;
	container: 'json' | 'zip';
	selectedSource: AccountImportSource | null;
	utcOffsetMinutes: number;
}

export interface TransferUnitProtocol extends UnitProtocol {
	importRoute: { request: { fileName: string }; response: TransferRoute };
	/** `syntax`: the page rethrows its own `JSON.parse` error (browser wording). */
	parseJson: { request: { meta: TransferParseMeta; text: string }; response: TransferParsed | { kind: 'syntax' } };
	zipPlan: { request: { entries: Array<{ name: string; dir: boolean }> }; response: TransferZipPlan };
	openmatesManifest: { request: { manifest: unknown }; response: { kind: 'ok' } | TransferError };
	parseOpenMates: {
		request: {
			manifest: unknown;
			chats: Array<{ name: string; value: unknown }>;
			embeds: unknown[];
			uploads: unknown[];
			fileName: string;
			selectedSource: AccountImportSource | null;
			utcOffsetMinutes: number;
		};
		response: TransferParsed;
	};
	batchPlan: {
		request: { chats: Array<{ fingerprint: string; messageCount: number }>; maxMessages: number };
		response: { kind: 'ok'; batches: TransferBatch[] } | TransferError;
	};
}

/** Worker module exports (snake_case, JSON text) of browser_transfer.rs. */
export interface TransferBinding {
	transfer_import_route(input: string): string;
	transfer_parse_json_import(input: string, text: string): string;
	transfer_zip_plan(input: string): string;
	transfer_openmates_manifest(input: string): string;
	transfer_parse_openmates_archive(input: string): string;
	transfer_batch_plan(input: string): string;
}

const BINDING_EXPORTS: readonly (keyof TransferBinding)[] = [
	'transfer_import_route', 'transfer_parse_json_import', 'transfer_zip_plan',
	'transfer_openmates_manifest', 'transfer_parse_openmates_archive', 'transfer_batch_plan',
];

export function isTransferBinding(value: unknown): value is TransferBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return BINDING_EXPORTS.every((name) => typeof binding[name] === 'function');
}
