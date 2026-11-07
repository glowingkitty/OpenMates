/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) chat export: the page adapter over the
 * shared Rust core Worker `transfer` unit. Loaded only by the guarded branches of
 * chatExportService.ts, so default builds never bundle it.
 *
 * Rust (web_transfer_export.rs) owns the pure logic of the former TypeScript
 * exporter: filename and timestamp helpers, the YAML emitter and its quoting,
 * message/checkpoint/embed objects and PII restore. The page keeps what needs
 * browser data and keys: message hydration, the metadata cache, draft and
 * thinking decryption, TipTap serialization and embed loading; it sends the
 * resolved values. The public functions keep the TypeScript service's contracts.
 */
import type { Chat, Message, PIIMapping } from '../../../types/chat';
import type { ChatExportHydrationResult, PIIExportOptions } from '../../chatExportService';
import type { TransferExportEmbed, TransferExportYamlRequest } from './transferProtocol';
import { transferCall } from './transferUnitClient';

/** Page-side inputs of an export: everything that needs keys, stores or the DOM. */
export interface ChatExportPageIO {
	decryptedMetadata(chat: Chat): Promise<{ title?: string; summary?: string } | null>;
	decryptDraft(encrypted: string): Promise<string | null>;
	thinkingText(message: Message): Promise<string | undefined>;
	messageMarkdown(message: Message): Promise<string>;
	collectEmbeds(messages: Message[]): Promise<TransferExportEmbed[]>;
	chatLink(chatId: string): string;
}

export interface ChatYamlSource {
	chat: Chat;
	messages: Message[];
	includeLink: boolean;
	piiOptions: PIIExportOptions | undefined;
	hydration: ChatExportHydrationResult | undefined;
}

/**
 * Resolves the page-side values of `convertChatToYaml` into the Rust request.
 * Exported for the parity vectors, which replay exactly this request in Rust.
 */
export async function buildChatYamlRequest(
	source: ChatYamlSource, io: ChatExportPageIO, exportedAt: string = new Date().toISOString(),
): Promise<TransferExportYamlRequest> {
	const { chat, messages, hydration, piiOptions } = source;
	const link = source.includeLink ? io.chatLink(chat.chat_id) : null;
	const metadata = await io.decryptedMetadata(chat);

	let draft: string | null = null;
	if (chat.encrypted_draft_md) {
		// Draft kind is Rust policy; only decryption of a stored ciphertext is page IO.
		const kind = await transferCall('exportDraftKind', { draft: chat.encrypted_draft_md });
		if (kind.cleartext) {
			draft = chat.encrypted_draft_md;
		} else {
			try {
				draft = (await io.decryptDraft(chat.encrypted_draft_md)) || null;
			} catch (error) {
				console.error('[ChatExportService] Error processing draft:', error);
			}
		}
	}

	// Embeds load in parallel with message resolution, like the TypeScript exporter.
	const embedsPromise = io.collectEmbeds(messages);
	const exportMessages: TransferExportYamlRequest['messages'] = [];
	for (const message of messages) {
		exportMessages.push({
			role: message.role,
			createdAt: message.created_at,
			category: message.category,
			assistantCategory: (message as unknown as Record<string, string | undefined>).assistant_category,
			content: await io.messageMarkdown(message),
			thinking: message.role === 'assistant' ? ((await io.thinkingText(message)) ?? null) : null,
			hasThinking: Boolean(message.has_thinking),
			thinkingTokenCount: message.thinking_token_count,
		});
	}

	return {
		exportedAt,
		link,
		titles: { decrypted: metadata?.title ?? null, plain: chat.title ?? null },
		summaries: { decrypted: metadata?.summary ?? null, plain: chat.chat_summary ?? null },
		draft,
		completeness: hydration?.completeness ?? null,
		checkpoints: (hydration?.checkpoints ?? []).map((checkpoint) => ({
			id: checkpoint.id,
			created_at: checkpoint.created_at,
			compressed_up_to_timestamp: checkpoint.compressed_up_to_timestamp,
			compressed_message_count: checkpoint.compressed_message_count,
			summary_token_estimate: checkpoint.summary_token_estimate,
			summary: checkpoint.summary,
		})),
		messages: exportMessages,
		embeds: await embedsPromise,
		pii: piiOptions
			? {
				hidden: Boolean(piiOptions.piiHidden),
				mappings: piiOptions.piiMappings.map((mapping: PIIMapping) => ({ placeholder: mapping.placeholder, original: mapping.original })),
			}
			: null,
	};
}

/** `convertChatToYaml` on the shared Rust core. */
export async function rustConvertChatToYaml(source: ChatYamlSource, io: ChatExportPageIO): Promise<string> {
	const result = await transferCall('exportYaml', await buildChatYamlRequest(source, io));
	return result.yaml;
}

/** `generateChatFilename` on the shared Rust core; an invalid creation time throws like `toISOString`. */
export async function rustGenerateChatFilename(
	createdAt: number, decryptedTitle: string | undefined, plainTitle: string | undefined, extension: string,
): Promise<string> {
	const result = await transferCall('exportFilename', {
		createdAt, titleDecrypted: decryptedTitle ?? null, titlePlain: plainTitle ?? null, extension,
	});
	if (result.kind === 'error') throw new RangeError(result.message);
	return result.filename;
}
