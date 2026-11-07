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
 *
 * Chat export (web_transfer_export.rs, port of chatExportService.ts) builds the
 * download filename and the chat YAML from values the page resolved (decrypted
 * titles, Markdown message bodies, decrypted thinking, collected embeds).
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

/** An embed as collected by the page for export; Rust shapes timestamps and key order. */
export type TransferExportEmbed =
	| {
		kind: 'ok'; embed_id: string; type: string; status: unknown; content: unknown;
		createdAt: number | undefined; updatedAt: number | undefined; text_preview: string | undefined;
	}
	| { kind: 'error'; embed_id: string; type: string; error: string };
export interface TransferExportMessage {
	role: string;
	createdAt: number | undefined;
	category: string | undefined;
	assistantCategory: string | undefined;
	/** Markdown body (TipTap already serialized by the page). */
	content: string;
	/** Decrypted thinking text, or null. */
	thinking: string | null;
	hasThinking: boolean;
	thinkingTokenCount: number | undefined;
}
export interface TransferExportYamlRequest {
	exportedAt: string;
	link: string | null;
	titles: { decrypted: string | null; plain: string | null };
	summaries: { decrypted: string | null; plain: string | null };
	draft: string | null;
	/** `hydration.completeness`, or null for the complete default. */
	completeness: unknown;
	checkpoints: Array<{
		id: string; created_at: number; compressed_up_to_timestamp: number; compressed_message_count: number;
		summary_token_estimate: number | undefined; summary: string | undefined;
	}>;
	messages: TransferExportMessage[];
	embeds: TransferExportEmbed[];
	pii: { hidden: boolean; mappings: Array<{ placeholder: string; original: string }> } | null;
}

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
	/** `generateChatFilename`; `error` is the `RangeError` the TypeScript service throws. */
	exportFilename: {
		request: { createdAt: number | undefined; titleDecrypted: string | null; titlePlain: string | null; extension: string };
		response: { kind: 'ok'; filename: string } | TransferError;
	};
	/** Whether a stored draft is cleartext (no decryption needed). */
	exportDraftKind: { request: { draft: string }; response: { kind: 'ok'; cleartext: boolean } };
	exportYaml: { request: TransferExportYamlRequest; response: { kind: 'ok'; yaml: string } };
}

/** Worker module exports (snake_case, JSON text) of browser_transfer.rs. */
export interface TransferBinding {
	transfer_import_route(input: string): string;
	transfer_parse_json_import(input: string, text: string): string;
	transfer_zip_plan(input: string): string;
	transfer_openmates_manifest(input: string): string;
	transfer_parse_openmates_archive(input: string): string;
	transfer_batch_plan(input: string): string;
	transfer_export_filename(input: string): string;
	transfer_export_draft_kind(input: string): string;
	transfer_export_yaml(input: string): string;
}

const BINDING_EXPORTS: readonly (keyof TransferBinding)[] = [
	'transfer_import_route', 'transfer_parse_json_import', 'transfer_zip_plan',
	'transfer_openmates_manifest', 'transfer_parse_openmates_archive', 'transfer_batch_plan',
	'transfer_export_filename', 'transfer_export_draft_kind', 'transfer_export_yaml',
];

export function isTransferBinding(value: unknown): value is TransferBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return BINDING_EXPORTS.every((name) => typeof binding[name] === 'function');
}
