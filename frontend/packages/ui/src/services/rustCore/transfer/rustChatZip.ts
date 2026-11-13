/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) ZIP export: the page adapter over the shared
 * Rust core Worker `transfer` unit. Loaded only by the guarded branches of
 * zipExportService.ts and accountExportService.ts, so default builds never bundle it.
 *
 * Rust (web_transfer_zip.rs, web_transfer_account_export.rs) plans the archive:
 * entry paths and folder layout, the chat Markdown document, code/application
 * download names, dated zip names and the Account Export V1 documents with their
 * secret guards. The page keeps what needs browser data and keys: embed loading,
 * blob fetching and decryption, TipTap serialization, the JSZip byte writing and
 * the download. A failed unit call rejects; there is no TypeScript fallback.
 */
import type { Chat, Message } from '../../../types/chat';
import type { PIIExportOptions } from '../../chatExportService';
import type { AccountExportBundle } from '../../accountExportService';
import type { ChatZipFiles, ZipTarget } from '../../zipExportService';
import type { TransferAccountExportRequest, TransferZipChatRequest, TransferZipEntry } from './transferProtocol';
import { transferCall } from './transferUnitClient';

export interface ChatZipInput {
	/** `generateChatFilename(chat, "")`. */
	filename: string;
	/** `JSON.stringify(completeness, null, 2)` for single downloads; null for bulk folders. */
	completenessJson: string | null;
	chat: Chat;
	messages: Message[];
	piiOptions: PIIExportOptions | undefined;
	files: ChatZipFiles;
	/** The chat YAML (already built, by Rust or TypeScript). */
	yaml: string;
}

export interface ChatZipPlan {
	base: string;
	zipName: string;
	entries: TransferZipEntry[];
}

/**
 * Page-side Markdown body of one message: the readable serialization, `''` when
 * the message has no content, `null` when serialization failed (the zip then
 * carries an empty section, like the TypeScript exporter).
 */
export async function readableBody(
	message: Message, serialize: (content: unknown) => Promise<string>,
): Promise<string | null> {
	try {
		if (typeof message.content === 'string' || (message.content && typeof message.content === 'object')) {
			return await serialize(message.content);
		}
		return '';
	} catch (error) {
		console.error('[ZipExportService] Error converting message to markdown:', error);
		return null;
	}
}

/** Builds the `zipChatPlan` request; exported for the parity vectors. */
export async function buildChatZipRequest(
	input: ChatZipInput, serialize: (content: unknown) => Promise<string>,
): Promise<TransferZipChatRequest> {
	const { chat, files, piiOptions } = input;
	const messages: TransferZipChatRequest['messages'] = [];
	for (const message of input.messages) {
		messages.push({ role: message.role, createdAt: message.created_at, content: await readableBody(message, serialize) });
	}
	return {
		filename: input.filename,
		completenessJson: input.completenessJson,
		chat: { title: chat.title ?? null, createdAt: chat.created_at },
		messages,
		pii: piiOptions
			? { hidden: Boolean(piiOptions.piiHidden), mappings: piiOptions.piiMappings.map((m) => ({ placeholder: m.placeholder, original: m.original })) }
			: null,
		code: files.code.map((code) => ({
			filePath: code.file_path ?? null, filename: code.filename ?? null, language: code.language, embedId: code.embed_id,
		})),
		transcripts: files.transcripts.map((file) => file.filename),
		images: files.images.map((file) => file.filename),
		generatedAudio: files.generatedAudio.map((file) => file.filename),
		staticFiles: files.staticFiles.map((file) => file.filename),
		audio: files.audio.map((file) => file.filename),
		pdfs: files.pdfs.map((pdf) => ({ folderName: pdf.folderName, pages: pdf.pages.map((page) => page.filename) })),
	};
}

/** Asks Rust for the entry layout of a chat zip. */
export async function rustPlanChatZip(
	input: ChatZipInput, serialize: (content: unknown) => Promise<string>,
): Promise<ChatZipPlan> {
	const result = await transferCall('zipChatPlan', await buildChatZipRequest(input, serialize));
	return { base: result.base, zipName: result.zipName, entries: result.entries };
}

/** Resolves a `src` reference of the plan to the page data it names. */
export function resolveZipSource(src: [string, number, number?], input: ChatZipInput): string | Blob {
	const [group, index, page] = src;
	const { files } = input;
	switch (group) {
		case 'yaml': return input.yaml;
		case 'code': return files.code[index].content;
		case 'transcript': return files.transcripts[index].content;
		case 'image': return files.images[index].blob;
		case 'generatedAudio': return files.generatedAudio[index].blob;
		case 'staticFile': return files.staticFiles[index].blob;
		case 'audio': return files.audio[index].blob;
		case 'audioTranscript': return files.audio[index].transcript;
		case 'pdf': return files.pdfs[index].pages[page ?? 0].blob;
		default: throw new Error(`Unknown zip source group ${group}`);
	}
}

/** Writes the planned entries (Rust text or resolved page data) into the zip or folder. */
export function applyChatZipPlan(target: ZipTarget, plan: ChatZipPlan, input: ChatZipInput): void {
	for (const entry of plan.entries) {
		target.file(entry.path, 'text' in entry ? entry.text : resolveZipSource(entry.src, input));
	}
}

/** `downloadCodeFilesAsZip` / `downloadCodeFile` names. */
export async function rustCodeFileNames(
	files: Array<{ filename: string | null; headerFilename: string | null; language: string }>, nowIso: string,
): Promise<{ zipName: string; names: string[] }> {
	const result = await transferCall('zipCodeFiles', { nowIso, files });
	return { zipName: result.zipName, names: result.names };
}

/** Application project zip name and sanitized entry paths. */
export async function rustApplicationZip(
	appName: string, paths: string[],
): Promise<{ zipName: string; paths: string[] }> {
	const result = await transferCall('zipApplication', { appName, paths });
	return { zipName: result.zipName, paths: result.paths };
}

/** Bulk chat zip file name from the page clock. */
export async function rustBulkZipName(nowIso: string): Promise<string> {
	return (await transferCall('zipBulkName', { nowIso })).zipName;
}

/** The `accountExportArchive` request for a bundle; exported for the parity vectors. */
export function buildAccountExportRequest(bundle: AccountExportBundle, exportedAt: string): TransferAccountExportRequest {
	return {
		export: { export_id: bundle.export.export_id, status: bundle.export.status },
		manifest: bundle.manifest,
		chunks: bundle.chunks.map((chunk) => ({
			chunk_id: chunk.chunk_id, domain: chunk.domain, sequence: chunk.sequence, status: chunk.status, payload: chunk.payload,
		})),
		exportedAt,
	};
}

/**
 * Account Export V1 archive entries. A secret-guard refusal throws the same
 * `Error` message the TypeScript service throws.
 */
export async function rustAccountExportEntries(
	bundle: AccountExportBundle, exportedAt: string,
): Promise<Array<{ path: string; content: string }>> {
	const result = await transferCall('accountExportArchive', buildAccountExportRequest(bundle, exportedAt));
	if (result.kind === 'error') throw new Error(result.message);
	return result.entries;
}
