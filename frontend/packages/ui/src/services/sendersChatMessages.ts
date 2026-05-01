/**
 * sendersChatMessages.ts — Message sending and encrypted storage operations
 *
 * Contains the most complex sender functions: sending new user messages,
 * completing AI responses, and the dual-phase encrypted storage package.
 * These functions handle the critical-op lock (acquireCriticalOp/releaseCriticalOp)
 * to prevent key cache wipes mid-flight during auth disruptions.
 *
 * Split from chatSyncServiceSenders.ts for maintainability (Phase 04, Plan 01).
 * See docs/architecture/ for the dual-phase encryption architecture.
 */
import type { ChatSynchronizationService } from "./chatSyncService";
import { chatDB } from "./db";
import { webSocketService } from "./websocketService";
import { notificationStore } from "../stores/notificationStore";
import { normalizeToUnixSeconds } from "./timestampUtils";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { encryptWithChatKey, decryptWithChatKey } from "./encryption/MessageEncryptor";
import {
	decryptChatKeyWithMasterKey,
	encryptChatKeyWithMasterKey,
	generateEmbedKey,
	deriveEmbedKeyFromChatKey,
	encryptWithEmbedKey,
	wrapEmbedKeyWithMasterKey,
	wrapEmbedKeyWithChatKey
} from "./encryption/MetadataEncryptor";
import { getTracer } from './tracing/setup';
import { injectTraceparent } from './tracing/wsSpans';
import { addCandidateKey } from "./db/chatCrudOperations";
import { encryptedChatKeyMatchesRawKey } from "./chatKeyConsistency";
import type { Chat, Message } from "../types/chat";

async function abortUnsafeKeyMismatch(
	chatId: string,
	encryptedChatKey: string,
	reason: string
): Promise<void> {
	addCandidateKey(chatDB, chatId, encryptedChatKey).catch(() => {});
	console.error(
		`[ChatSyncService:Senders] ❌ UNSAFE KEY MISMATCH for ${chatId}: ${reason}. ` +
			`Aborting send instead of uploading content encrypted with one key and encrypted_chat_key from another.`
	);
	notificationStore.error(
		"We could not safely send this message because this chat has conflicting encryption keys. Please reload and try again."
	);
}

export async function sendNewMessageImpl(
	serviceInstance: ChatSynchronizationService,
	message: Message,
	encryptedSuggestionToDelete?: string | null
): Promise<void> {
	// Check WebSocket connection status using public getter
	const isConnected = serviceInstance.webSocketConnected_FOR_SENDERS_ONLY;

	if (!isConnected) {
		console.warn(
			"[ChatSyncService:Senders] WebSocket not connected. Message saved locally with 'waiting_for_internet' status."
		);

		// Show notification to inform user that message couldn't be sent
		notificationStore.warning(
			"Connection lost. Your message will be sent when you're back online.",
			5000, // Auto-dismiss after 5 seconds
			true // Dismissible
		);

		// Update message status to 'waiting_for_internet' if it's currently 'sending'
		// This ensures the UI shows the correct status when offline.
		// IMPORTANT: Use updateMessageStatus() NOT spread→saveMessage(). saveMessage() calls
		// encryptMessageFields() → getOrGenerateChatKey(), which silently generates a new
		// random key if the chat key is absent from the in-memory cache, re-encrypting the
		// message and causing "[Content decryption failed]" on the sender's device.
		if (message.status === "sending") {
			try {
				await chatDB.updateMessageStatus(message.message_id, "waiting_for_internet");

				// Dispatch event to update UI with new status
				serviceInstance.dispatchEvent(
					new CustomEvent("messageStatusChanged", {
						detail: {
							chatId: message.chat_id,
							messageId: message.message_id,
							status: "waiting_for_internet"
						}
					})
				);

				console.debug(
					`[ChatSyncService:Senders] Updated message ${message.message_id} status to 'waiting_for_internet'`
				);
			} catch (dbError) {
				console.error(
					`[ChatSyncService:Senders] Error updating message status to 'waiting_for_internet' for ${message.message_id}:`,
					dbError
				);
			}
		}

		return;
	}

	// OTel instrumentation: trace the entire sendNewMessageImpl pipeline
	const tracer = getTracer();
	const implSpan = tracer.startSpan('message.send.sendNewMessageImpl', {
		attributes: { 'message.chat_id': message.chat_id }
	});

	try {
	// DUAL-PHASE ARCHITECTURE - Phase 1: Send ONLY plaintext for AI processing
	// Encrypted data will be sent separately after preprocessing completes via chat_metadata_for_encryption event

	// CRITICAL: Determine if this is a NEW chat or FOLLOW-UP message
	// Check if chat has existing messages (messages_v > 1, since current message is #1 for new chats)
	// NOT just encrypted_title, because title generation might have been skipped/failed
	// Also check if this is an incognito chat
	let chat: Chat | null = null;
	let isIncognitoChat = false;

	// First check if it's an incognito chat
	const { incognitoChatService } = await import("./incognitoChatService");
	try {
		chat = await incognitoChatService.getChat(message.chat_id);
		if (chat) {
			isIncognitoChat = true;
		}
	} catch {
		// Not an incognito chat, continue to check IndexedDB
	}

	// If not found in incognito service, check IndexedDB
	if (!chat) {
		chat = await chatDB.getChat(message.chat_id);
	}

	// Use title_v to determine if the chat already has a title generated.
	// Previously used (messages_v > 1) as a proxy, but this was unreliable due to race conditions:
	// Between handleSend creating the chat (messages_v=1) and this function reading it back,
	// messages_v could be incremented by concurrent operations (AI response handler, sync service),
	// causing the backend to skip title/icon/category generation for new chats.
	// title_v starts at 0 and only increments to 1 when a title is actually stored — the correct signal.
	const chatHasTitle = (chat?.title_v ?? 0) > 0;

	console.debug(
		`[ChatSyncService:Senders] Chat has title: ${chatHasTitle} (title_v: ${chat?.title_v}, messages_v: ${chat?.messages_v}) - ${chatHasTitle ? "FOLLOW-UP" : "NEW CHAT"}, isIncognito: ${isIncognitoChat}`
	);

	// ========================================================================
	// CLIENT-SIDE CODE BLOCK EXTRACTION
	// Extract code blocks from user message BEFORE sending to server.
	// This avoids round-trips (server extract → send_embed_data → store_embed).
	// Client creates embeds locally, encrypts them, and sends everything in one request.
	// ========================================================================
	let processedContent = message.content;
	const extractedCodeEmbeds: Array<{
		embed_id: string;
		type: string;
		content: string; // TOON-encoded
		text_preview: string;
		status: string;
		language?: string;
		filename?: string;
	}> = [];

	// Only extract code blocks if content contains potential code blocks (performance optimization)
	if (processedContent && processedContent.includes("```")) {
		const { encode: toonEncode } = await import("@toon-format/toon");
		const { generateUUID } = await import("../message_parsing/utils");
		const { embedStore } = await import("./embedStore");

		// Regex to match markdown code blocks: ```language:filename\ncontent\n``` or ```language\ncontent\n```
		// Skip JSON blocks that are already embed references
		const codeBlockPattern =
			/```([a-zA-Z0-9_+\-#.]*?)(?::([^\n`]+))?\n([\s\S]*?)\n```/g;

		// Find all code blocks and replace with embed references
		let match: RegExpExecArray | null;
		const replacements: Array<{
			start: number;
			end: number;
			replacement: string;
		}> = [];

		while ((match = codeBlockPattern.exec(processedContent)) !== null) {
			const fullMatch = match[0];
			let language = (match[1] || "").trim();
			let filename = match[2]?.trim() || null;
			let codeContent = match[3];

			// FIX: If language/filename not in fence line, check first content line
			// LLMs sometimes put "python:backend/main.py" in content instead of fence line
			if ((!language || !filename) && codeContent) {
				const lines = codeContent.split("\n");
				if (lines.length > 0) {
					const firstLine = lines[0].trim();
					// Check if first line matches language:filename pattern
					if (firstLine.includes(":") && !firstLine.startsWith("#")) {
						const langFileMatch = firstLine.match(
							/^([a-zA-Z0-9_+\-#.]+):([^\s:]+)$/
						);
						if (langFileMatch) {
							if (!language) language = langFileMatch[1];
							if (!filename) filename = langFileMatch[2];
							// Remove the first line from code content since it's metadata
							codeContent = lines.slice(1).join("\n");
						}
					}
				}
			}

			// Skip JSON blocks that are already embed references
			if (language.toLowerCase() === "json" || language.toLowerCase() === "json_embed") {
				try {
					const jsonData = JSON.parse(codeContent.trim());
					if ("embed_id" in jsonData || "embed_ids" in jsonData) {
						console.debug(
							"[ChatSyncService:Senders] Skipping existing embed reference JSON block"
						);
						continue; // Keep as-is
					}
				} catch {
					// Not valid JSON, treat as code block
				}
			}

			// Generate embed ID
			const embedId = generateUUID();

			// Create embed content structure
			const embedContent = {
				type: "code",
				language: language || "text",
				code: codeContent,
				filename: filename,
				status: "finished",
				line_count: codeContent ? codeContent.split("\n").length : 0
			};

			// Encode to TOON format for storage efficiency
			let toonContent: string;
			try {
				toonContent = toonEncode(embedContent);
			} catch {
				// Fallback to JSON if TOON encoding fails
				toonContent = JSON.stringify(embedContent);
			}

			// Create text preview (first line of code or language)
			const textPreview = filename
				? `${filename}${language ? ` (${language})` : ""}`
				: language
					? `${language} code block`
					: "Code block";

			// Store embed locally in EmbedStore (will be encrypted with master key)
			const now = Date.now();
			const embedData = {
				embed_id: embedId,
				type: "code-code", // Frontend embed type for code
				status: "finished",
				content: toonContent,
				text_preview: textPreview,
				createdAt: now,
				updatedAt: now
			};

			try {
				await embedStore.put(`embed:${embedId}`, embedData, "code-code");
				console.debug(
					`[ChatSyncService:Senders] Stored code embed ${embedId} locally`
				);
			} catch (storeError) {
				console.error(
					`[ChatSyncService:Senders] Failed to store code embed ${embedId}:`,
					storeError
				);
				continue; // Skip this code block if storage fails
			}

			// Add to extracted embeds list (for sending to server)
			extractedCodeEmbeds.push({
				embed_id: embedId,
				type: "code", // Server type (will be converted to 'code-code' on client)
				content: toonContent,
				text_preview: textPreview,
				status: "finished",
				language: language || undefined,
				filename: filename || undefined
			});

			// Create embed reference JSON block to replace the code block
			const embedReference = `\`\`\`json\n{"type": "code", "embed_id": "${embedId}"}\n\`\`\``;

			replacements.push({
				start: match.index,
				end: match.index + fullMatch.length,
				replacement: embedReference
			});
		}

		// Apply replacements in reverse order to maintain correct indices
		if (replacements.length > 0) {
			replacements.sort((a, b) => b.start - a.start);
			for (const { start, end, replacement } of replacements) {
				processedContent =
					processedContent.slice(0, start) + replacement + processedContent.slice(end);
			}
			console.info(
				`[ChatSyncService:Senders] Extracted ${extractedCodeEmbeds.length} code blocks from user message, replaced with embed references`
			);
		}
	}

	// ========================================================================
	// CLIENT-SIDE TABLE EXTRACTION
	// Extract markdown tables from user message BEFORE sending to server.
	// Similar to code block extraction - avoids round-trips.
	// ========================================================================
	const extractedTableEmbeds: Array<{
		embed_id: string;
		type: string;
		content: string; // TOON-encoded
		text_preview: string;
		status: string;
		rows?: number;
		cols?: number;
		title?: string;
	}> = [];

	// Only extract tables if content contains potential tables (lines starting with |)
	if (processedContent && processedContent.includes("|")) {
		const { encode: toonEncode } = await import("@toon-format/toon");
		const { generateUUID } = await import("../message_parsing/utils");
		const { embedStore } = await import("./embedStore");

		// Pattern to match markdown table rows (lines starting and ending with |)
		const tableRowPattern = /^\|.*\|$/;
		const lines = processedContent.split("\n");

		// Find consecutive table rows
		let tableStart = -1;
		let tableLines: string[] = [];
		const tableReplacements: Array<{
			start: number;
			end: number;
			replacement: string;
		}> = [];

		// Track character positions
		let charPos = 0;

		for (let i = 0; i < lines.length; i++) {
			const line = lines[i];
			const trimmedLine = line.trim();

			if (tableRowPattern.test(trimmedLine)) {
				// This is a table row
				if (tableStart === -1) {
					tableStart = charPos;
				}
				tableLines.push(line);
			} else {
				// Not a table row - check if we have a complete table
				if (tableLines.length >= 2) {
					// Need at least header + separator (or data)
					// Extract table content
					const tableContent = tableLines.join("\n");

					// Count rows and columns
					const rows = tableLines.length - 2; // Subtract header and separator
					const headerLine = tableLines[0].trim();
					const cols = (headerLine.match(/\|/g) || []).length - 1;

					if (rows >= 0 && cols > 0) {
						// Valid table
						const embedId = generateUUID();

						// Check for title comment before table
						let title: string | undefined;
						if (i > tableLines.length && lines[i - tableLines.length - 1]) {
							const prevLine = lines[i - tableLines.length - 1].trim();
							const titleMatch = prevLine.match(/<!--\s*title:\s*"([^"]+)"\s*-->/);
							if (titleMatch) {
								title = titleMatch[1];
							}
						}

						// Create embed content structure
						const embedContent = {
							type: "sheet",
							code: tableContent,
							title: title,
							rows: rows,
							cols: cols,
							status: "finished"
						};

						// Encode to TOON format
						let toonContent: string;
						try {
							toonContent = toonEncode(embedContent);
						} catch {
							toonContent = JSON.stringify(embedContent);
						}

						// Create text preview
						const textPreview = title || `${rows} rows × ${cols} columns`;

						// Store embed locally
						const now = Date.now();
						const embedData = {
							embed_id: embedId,
							type: "sheets-sheet",
							status: "finished",
							content: toonContent,
							text_preview: textPreview,
							createdAt: now,
							updatedAt: now
						};

						try {
							await embedStore.put(`embed:${embedId}`, embedData, "sheets-sheet");
							console.debug(
								`[ChatSyncService:Senders] Stored table embed ${embedId} locally`
							);

							// Add to extracted embeds list
							extractedTableEmbeds.push({
								embed_id: embedId,
								type: "sheet",
								content: toonContent,
								text_preview: textPreview,
								status: "finished",
								rows: rows,
								cols: cols,
								title: title
							});

							// Create embed reference
							const embedReference = `\`\`\`json\n{"type": "sheet", "embed_id": "${embedId}"}\n\`\`\``;
							const tableEnd = charPos; // End is at current position (before non-table line)

							tableReplacements.push({
								start: tableStart,
								end: tableEnd,
								replacement: embedReference
							});
						} catch (storeError) {
							console.error(
								`[ChatSyncService:Senders] Failed to store table embed:`,
								storeError
							);
						}
					}
				}
				// Reset table tracking
				tableStart = -1;
				tableLines = [];
			}

			// Update character position (add line length + newline)
			charPos += line.length + 1;
		}

		// Check for table at end of content
		if (tableLines.length >= 2) {
			const tableContent = tableLines.join("\n");
			const rows = tableLines.length - 2;
			const headerLine = tableLines[0].trim();
			const cols = (headerLine.match(/\|/g) || []).length - 1;

			if (rows >= 0 && cols > 0) {
				const embedId = generateUUID();

				const embedContent = {
					type: "sheet",
					code: tableContent,
					rows: rows,
					cols: cols,
					status: "finished"
				};

				let toonContent: string;
				try {
					const { encode: toonEncode2 } = await import("@toon-format/toon");
					toonContent = toonEncode2(embedContent);
				} catch {
					toonContent = JSON.stringify(embedContent);
				}

				const textPreview = `${rows} rows × ${cols} columns`;
				const now = Date.now();

				try {
					await embedStore.put(
						`embed:${embedId}`,
						{
							embed_id: embedId,
							type: "sheets-sheet",
							status: "finished",
							content: toonContent,
							text_preview: textPreview,
							createdAt: now,
							updatedAt: now
						},
						"sheets-sheet"
					);

					extractedTableEmbeds.push({
						embed_id: embedId,
						type: "sheet",
						content: toonContent,
						text_preview: textPreview,
						status: "finished",
						rows: rows,
						cols: cols
					});

					const embedReference = `\`\`\`json\n{"type": "sheet", "embed_id": "${embedId}"}\n\`\`\``;
					tableReplacements.push({
						start: tableStart,
						end: charPos - 1, // -1 because charPos includes trailing newline
						replacement: embedReference
					});
				} catch (storeError) {
					console.error(
						`[ChatSyncService:Senders] Failed to store table embed:`,
						storeError
					);
				}
			}
		}

		// Apply table replacements in reverse order
		if (tableReplacements.length > 0) {
			tableReplacements.sort((a, b) => b.start - a.start);
			for (const { start, end, replacement } of tableReplacements) {
				processedContent =
					processedContent.slice(0, start) + replacement + processedContent.slice(end);
			}
			console.info(
				`[ChatSyncService:Senders] Extracted ${extractedTableEmbeds.length} tables from user message, replaced with embed references`
			);
		}
	}

	// Use processed content (with code blocks and tables replaced by embed references)
	const contentForServer = processedContent;

	// Extract embed references from message content (now includes the newly created code embeds)
	// Embeds are referenced as JSON code blocks: ```json\n{"type": "app_skill_use", "embed_id": "..."}\n```
	const { extractEmbedReferences, loadEmbeds } = await import("./embedResolver");
	const embedRefs = extractEmbedReferences(contentForServer);

	// Load embeds from EmbedStore (decrypted, ready to send as cleartext)
	interface EmbedForServer {
		embed_id: string;
		type: string;
		status?: string;
		content: string;
		text_preview?: string;
		embed_ids?: string[];
		createdAt?: number;
		updatedAt?: number;
	}
	const embeds: EmbedForServer[] = [];
	if (embedRefs.length > 0) {
		const embedIds = embedRefs.map((ref) => ref.embed_id);
		const loadedEmbeds = await loadEmbeds(embedIds);

		// CRITICAL VALIDATION: Ensure all embed references have corresponding embed data
		// If any embeds are missing, this indicates data corruption and should prevent message sending
		const loadedEmbedIds = new Set(loadedEmbeds.map((e) => e.embed_id));
		const missingEmbedIds = embedIds.filter((id) => !loadedEmbedIds.has(id));

		if (missingEmbedIds.length > 0) {
			const errorMessage = `Sorry, we can't send this message right now. Something went wrong while processing the embeds in your message. Please use the "Report Issue" button to let us know about this problem so we can help fix it.`;
			console.error(
				"[ChatSyncService:Senders] ❌ BLOCKED message send due to missing embeds:",
				missingEmbedIds
			);
			throw new Error(errorMessage);
		}

		// Convert embeds to format expected by server (cleartext, will be encrypted server-side)
		for (const embed of loadedEmbeds) {
			// Skip sending content for server-authoritative embeds (e.g. deduplicated
			// PDF uploads). The server already has the full version with OCR text —
			// sending our minimal client-side version would overwrite it in the cache
			// and break AI PDF reading. The embed reference in the message markdown
			// is enough for the server to resolve the embed from its own storage.
			const isServerAuthoritative =
				typeof embed.content === "string" &&
				embed.content.includes("_server_authoritative");
			if (isServerAuthoritative) {
				console.debug(
					`[ChatSyncService:Senders] Skipping server-authoritative embed ${embed.embed_id} — server already has full content`
				);
				continue;
			}
			embeds.push({
				embed_id: embed.embed_id,
				type: embed.type, // Decrypted type (client-side only)
				status: embed.status,
				content: embed.content, // TOON-encoded string (cleartext for server)
				text_preview: embed.text_preview,
				embed_ids: embed.embed_ids, // For composite embeds
				createdAt: embed.createdAt,
				updatedAt: embed.updatedAt
			});
		}

		console.debug("[ChatSyncService:Senders] Extracted and loaded embeds:", {
			embedRefCount: embedRefs.length,
			loadedCount: embeds.length,
			embedIds: embedIds
		});
	}

	// For incognito chats, load full message history (no server-side caching)
	let messageHistory: Message[] = [];
	if (isIncognitoChat) {
		try {
			messageHistory = await incognitoChatService.getMessagesForChat(message.chat_id);
			console.debug(
				`[ChatSyncService:Senders] Loaded ${messageHistory.length} messages from incognito chat history`
			);
		} catch (error) {
			console.error(
				`[ChatSyncService:Senders] Error loading incognito chat message history:`,
				error
			);
		}
	}

	// Load app settings/memories metadata keys (format: "app_id-item_type")
	// This tells the server what app settings/memories exist on this device WITHOUT sending content
	// The server's preprocessor uses this to decide which settings/memories to request
	let appSettingsMemoriesMetadataKeys: string[] = [];
	if (!isIncognitoChat) {
		try {
			appSettingsMemoriesMetadataKeys =
				await chatDB.getAppSettingsMemoriesMetadataKeys();
			if (appSettingsMemoriesMetadataKeys.length > 0) {
				console.debug(
					`[ChatSyncService:Senders] Loaded ${appSettingsMemoriesMetadataKeys.length} app settings/memories metadata keys`
				);
			}
		} catch (error) {
			console.error(
				`[ChatSyncService:Senders] Error loading app settings/memories metadata:`,
				error
			);
			// Continue without metadata - don't fail the message send
		}
	}

	// OTel: key management span — fetching encrypted chat key for device sync
	const keyMgmtSpan = tracer.startSpan('message.send.key_management', {
		attributes: { 'key.source': isIncognitoChat ? 'incognito-skip' : 'idb-lookup' }
	});
	// Fetch encrypted_chat_key for server storage (zero-knowledge architecture)
	// This is critical for device sync - other devices need the chat key to decrypt messages
	let encryptedChatKey: string | null = null;
	if (!isIncognitoChat) {
		encryptedChatKey = await chatDB.getEncryptedChatKey(message.chat_id);
	}
	keyMgmtSpan.end();

	// Phase 1 payload: ONLY fields needed for AI processing
	interface SendMessagePayload {
		chat_id: string;
		message: {
			message_id: string;
			role: string;
			content: string;
			created_at: number;
			sender_name?: string;
			category?: string;
			model_name?: string;
			chat_has_title?: boolean;
			current_chat_title?: string | null; // OPE-265: Decrypted title for post-processing title update evaluation
		};
		encrypted_chat_key?: string | null; // CRITICAL: Include key for device sync broadcast
		is_incognito?: boolean;
		embeds?: EmbedForServer[];
		message_history?: Message[];
		encrypted_suggestion_to_delete?: string | null;
		app_settings_memories_metadata?: string[]; // Format: ["code-preferred_technologies", "travel-trips", ...]
		mentioned_settings_memories_cleartext?: Record<string, unknown[]>; // Cleartext for @memory/@memory-entry mentions so backend does not re-request
		active_focus_id?: string | null; // Plaintext focus mode ID for AI processing (decrypted from E2E encrypted field)
	}
	const payload: SendMessagePayload = {
		chat_id: message.chat_id,
		message: {
			message_id: message.message_id,
			role: message.role,
			// Use processed content (code blocks replaced with embed references)
			// This allows server to build AI context with embed references
			content: contentForServer,
			created_at: message.created_at,
			sender_name: message.sender_name, // Include for cache but not critical for AI
			chat_has_title: chatHasTitle // ZERO-KNOWLEDGE: Send true if chat already has a title (title_v > 0), false if new
			// NO category or encrypted fields - those go to Phase 2
			// NO message_history - server will request if cache is stale (unless incognito)
		},
		encrypted_chat_key: encryptedChatKey, // Include the key for device sync broadcast
		is_incognito: isIncognitoChat // Flag for backend to skip persistence
	};

	// Include app settings/memories metadata (keys only, no content)
	// Server preprocessor uses this to know what data exists and decide what to request
	if (appSettingsMemoriesMetadataKeys.length > 0) {
		payload.app_settings_memories_metadata = appSettingsMemoriesMetadataKeys;
		console.debug(
			"[ChatSyncService:Senders] Including app settings/memories metadata:",
			appSettingsMemoriesMetadataKeys
		);
	}

	// When user mentioned @memory or @memory-entry in the message, send cleartext so the backend
	// can use it and not request that category again during this request
	if (!isIncognitoChat && contentForServer) {
		try {
			const { extractMentionedSettingsMemoriesCleartext } = await import(
				"./mentionedSettingsMemoriesCleartext"
			);
			const mentionedCleartext =
				await extractMentionedSettingsMemoriesCleartext(contentForServer);
			const keys = Object.keys(mentionedCleartext);
			if (keys.length > 0) {
				payload.mentioned_settings_memories_cleartext = mentionedCleartext;
				console.debug(
					"[ChatSyncService:Senders] Including mentioned settings/memories cleartext for keys:",
					keys
				);
			}
		} catch (err) {
			console.warn(
				"[ChatSyncService:Senders] Failed to extract mentioned settings/memories cleartext (non-fatal):",
				err
			);
		}
	}

	// Include active focus mode ID for AI processing (if focus mode is active)
	// The client is the only entity that can decrypt encrypted_active_focus_id (E2E encrypted),
	// so we decrypt it here and send the plaintext focus_id to the server for AI context.
	if (!isIncognitoChat && chat?.encrypted_active_focus_id) {
		try {
			const chatKey = await chatKeyManager.getKey(message.chat_id);
			if (chatKey) {
				const activeFocusId = await decryptWithChatKey(
					chat.encrypted_active_focus_id,
					chatKey
				);
				if (activeFocusId) {
					payload.active_focus_id = activeFocusId;
					console.debug(
						"[ChatSyncService:Senders] Including active_focus_id for AI processing:",
						activeFocusId
					);
				}
			}
		} catch (e) {
			console.warn(
				"[ChatSyncService:Senders] Failed to decrypt active_focus_id, AI will use default focus:",
				e
			);
		}
	}

	// OPE-265: Send the current decrypted chat title to the backend so post-processing
	// can evaluate whether the title still fits the conversation after topic drift.
	if (!isIncognitoChat && chatHasTitle && chat?.encrypted_title) {
		try {
			const chatKey = await chatKeyManager.getKey(message.chat_id);
			if (chatKey) {
				const currentTitle = await decryptWithChatKey(
					chat.encrypted_title,
					chatKey
				);
				if (currentTitle) {
					payload.message.current_chat_title = currentTitle;
				}
			}
		} catch (e) {
			console.warn(
				"[ChatSyncService:Senders] Failed to decrypt chat title for post-processing title evaluation:",
				e
			);
		}
	}

	// For incognito chats, include full message history (no server-side caching)
	if (isIncognitoChat && messageHistory.length > 0) {
		payload.message_history = messageHistory.map(
			(msg) =>
				({
					message_id: msg.message_id,
					role: msg.role,
					content:
						typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content),
					created_at: msg.created_at,
					sender_name: msg.sender_name
				}) as Message
		);
		console.debug(
			`[ChatSyncService:Senders] Including full message history for incognito chat: ${messageHistory.length} messages`
		);
	}

	// For duplicated demo chats or new chats with history, include full message history
	// This allows the server to persist history for a brand-new chat ID in one go.
	// The server will use the cleartext 'content' for AI context and 'encrypted_content' for DB storage.
	if (!isIncognitoChat && !chatHasTitle && messageHistory.length > 0) {
		payload.message_history = messageHistory.map(
			(msg) =>
				({
					message_id: msg.message_id,
					chat_id: message.chat_id,
					role: msg.role,
					content:
						typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content),
					encrypted_content: msg.encrypted_content,
					encrypted_sender_name: msg.encrypted_sender_name,
					encrypted_category: msg.encrypted_category,
					encrypted_model_name: msg.encrypted_model_name,
					encrypted_pii_mappings: msg.encrypted_pii_mappings,
					created_at: msg.created_at,
					sender_name: msg.sender_name
				}) as Message
		);

		console.info(
			`[ChatSyncService:Senders] Including full history for new chat ${message.chat_id} (duplication flow): ${messageHistory.length} messages`
		);
	}

	// Include embeds if any were found in the message
	if (embeds.length > 0) {
		payload.embeds = embeds; // Send embeds as cleartext (server will encrypt for cache)
		console.debug(
			"[ChatSyncService:Senders] Including embeds with message:",
			embeds.length
		);

		// OTel: encrypt span — client-side embed encryption for Directus storage
		const encryptSpan = tracer.startSpan('message.send.encrypt', {
			attributes: { 'encrypt.embed_count': String(embeds.length) }
		});
		// ARCHITECTURE FIX: Also include client-encrypted embeds for direct Directus storage
		// This avoids round-trip WebSocket calls (send_embed_data → store_embed).
		// The client already has the embed data and encryption keys, so we encrypt before sending.
		// Server stores the encrypted embeds directly in Directus without decrypting.
		// Skip for incognito chats (no persistence).
		if (!isIncognitoChat) {
			try {
				const { computeSHA256 } = await import("../message_parsing/utils");
				const { embedStore } = await import("./embedStore");

				// Hash IDs for zero-knowledge storage
				const hashedChatId = await computeSHA256(message.chat_id);
				const hashedMessageId = await computeSHA256(message.message_id);

				// Get user_id from the chat object if available (may be empty for new chats)
				// Server will fill in hashed_user_id if client doesn't provide it
				const userId = chat?.user_id || "";
				const hashedUserId = userId ? await computeSHA256(userId) : "";

				// Get chat key for wrapping embed keys — must be available by the time we send
				const chatKey =
					chatKeyManager.getKeySync(message.chat_id) ||
					(await chatKeyManager.getKey(message.chat_id));
				if (!chatKey) {
					console.error(
						`[ChatSyncService:Senders] No chat key available for embed key wrapping (chat ${message.chat_id}). Embeds will not be encrypted.`
					);
				}

				// Only proceed if we have a chat key (user_id is optional - server fills it in)
				if (chatKey) {
					// Prepare encrypted embeds for Directus storage
					// IMPORTANT: Use snake_case for Directus fields (created_at, updated_at)
					// and Unix timestamps in SECONDS (not milliseconds)
					interface EncryptedEmbedForDirectus {
						embed_id: string;
						encrypted_type: string;
						encrypted_content: string;
						encrypted_text_preview?: string;
						status: string;
						hashed_chat_id: string;
						hashed_message_id: string;
						hashed_user_id: string;
						embed_ids?: string[];
						created_at: number; // Unix timestamp in SECONDS (snake_case for Directus)
						updated_at: number; // Unix timestamp in SECONDS (snake_case for Directus)
						embed_keys?: Array<{
							hashed_embed_id: string;
							key_type: "master" | "chat";
							hashed_chat_id: string | null;
							encrypted_embed_key: string;
							hashed_user_id: string;
							created_at: number;
						}>;
					}
					const encryptedEmbeds: EncryptedEmbedForDirectus[] = [];

					for (const embed of embeds) {
						try {
							// CRITICAL LOGGING: Track embed_keys generation for debugging
							console.info(
								`[ChatSyncService:Senders] Processing embed for Directus storage:`,
								{
									embed_id: embed.embed_id,
									type: embed.type,
									hasContent: !!embed.content,
									contentLength: embed.content?.length || 0
								}
							);

							// Validate embed has required fields
							if (!embed.embed_id) {
								console.error(
									`[ChatSyncService:Senders] Embed missing embed_id, skipping:`,
									embed
								);
								continue;
							}
							if (!embed.content) {
								console.error(
									`[ChatSyncService:Senders] Embed missing content, skipping:`,
									embed.embed_id
								);
								continue;
							}

							// Derive embed key deterministically from chat key — all tabs produce the same result.
							// This prevents multi-tab race conditions where different tabs generate different
							// random keys for the same embed (causing permanent key/content mismatch on reload).
							let embedKey: Uint8Array;
							if (chatKey) {
								embedKey = await deriveEmbedKeyFromChatKey(chatKey, embed.embed_id);
							} else {
								// Fallback to random (should not happen — chatKey is validated above)
								embedKey = generateEmbedKey();
								console.warn(
									`[ChatSyncService:Senders] ⚠️ Chat key unavailable for HKDF, using random key for embed ${embed.embed_id}`
								);
							}
							const hashedEmbedId = await computeSHA256(embed.embed_id);

							// Encrypt embed data with the embed key
							const encryptedContent = await encryptWithEmbedKey(
								embed.content,
								embedKey
							);
							const encryptedType = await encryptWithEmbedKey(embed.type, embedKey);
							let encryptedTextPreview: string | undefined;
							if (embed.text_preview) {
								encryptedTextPreview = await encryptWithEmbedKey(
									embed.text_preview,
									embedKey
								);
							}

							// Wrap embed key for storage (master + chat wrapped versions)
							// Master: AES(embed_key, master_key) - for owner's cross-chat access
							// Chat: AES(embed_key, chat_key) - for shared chat access
							const wrappedWithMaster = await wrapEmbedKeyWithMasterKey(embedKey);
							const wrappedWithChat = await wrapEmbedKeyWithChatKey(
								embedKey,
								chatKey
							);

							if (!wrappedWithMaster || !wrappedWithChat) {
								console.error(
									`[ChatSyncService:Senders] ❌ CRITICAL: Failed to wrap embed key for ${embed.embed_id}, skipping Directus storage`,
									{
										wrappedWithMaster: !!wrappedWithMaster,
										wrappedWithChat: !!wrappedWithChat,
										hasChatKey: !!chatKey
									}
								);
								continue;
							}

							console.info(
								`[ChatSyncService:Senders] ✅ Successfully wrapped embed key for ${embed.embed_id}:`,
								{
									hashedEmbedId: hashedEmbedId.substring(0, 16) + "...",
									masterKeyLength: wrappedWithMaster?.length || 0,
									chatKeyLength: wrappedWithChat?.length || 0
								}
							);

							// CRITICAL FIX: Use Unix timestamp in SECONDS (not milliseconds!)
							// The database field is an INTEGER which can't hold milliseconds (13 digits)
							// Milliseconds would cause "VALUE_OUT_OF_RANGE" error in Directus
							const nowSeconds = Math.floor(Date.now() / 1000);

							// Prepare embed keys for storage
							const embedKeys: EncryptedEmbedForDirectus["embed_keys"] = [
								{
									hashed_embed_id: hashedEmbedId,
									key_type: "master",
									hashed_chat_id: null, // Master key wrapper has no chat association
									encrypted_embed_key: wrappedWithMaster,
									hashed_user_id: hashedUserId,
									created_at: nowSeconds // Unix timestamp in seconds
								},
								{
									hashed_embed_id: hashedEmbedId,
									key_type: "chat",
									hashed_chat_id: hashedChatId,
									encrypted_embed_key: wrappedWithChat,
									hashed_user_id: hashedUserId,
									created_at: nowSeconds // Unix timestamp in seconds
								}
							];

							// Cache the embed key locally for future use
							embedStore.setEmbedKeyInCache(embed.embed_id, embedKey, hashedChatId);
							embedStore.setEmbedKeyInCache(
								embed.embed_id,
								embedKey,
								undefined
							); // Master fallback

							// Log embed_keys that will be stored
							console.info(
								`[ChatSyncService:Senders] 🔑 Created ${embedKeys.length} embed_keys for ${embed.embed_id}:`,
								{
									hashedEmbedId: hashedEmbedId.substring(0, 16) + "...",
									keyTypes: embedKeys.map((k) => k.key_type),
									hashedChatId: hashedChatId.substring(0, 16) + "..."
								}
							);

							encryptedEmbeds.push({
								embed_id: embed.embed_id,
								encrypted_type: encryptedType,
								encrypted_content: encryptedContent,
								encrypted_text_preview: encryptedTextPreview,
								status: embed.status || "finished",
								hashed_chat_id: hashedChatId,
								hashed_message_id: hashedMessageId,
								hashed_user_id: hashedUserId,
								embed_ids: embed.embed_ids,
								// CRITICAL: Use snake_case for Directus fields and normalized Unix seconds
								created_at: embed.createdAt
									? normalizeToUnixSeconds(embed.createdAt, nowSeconds)
									: nowSeconds,
								updated_at: embed.updatedAt
									? normalizeToUnixSeconds(embed.updatedAt, nowSeconds)
									: nowSeconds,
								embed_keys: embedKeys
							});

							console.info(
								`[ChatSyncService:Senders] ✅ Encrypted embed ${embed.embed_id} for Directus storage with ${embedKeys.length} keys`
							);
						} catch (embedError) {
							console.error(
								`[ChatSyncService:Senders] Error encrypting embed ${embed.embed_id}:`,
								embedError
							);
							// Continue with other embeds
						}
					}

					// Add encrypted embeds to payload for direct Directus storage
					if (encryptedEmbeds.length > 0) {
						(
							payload as SendMessagePayload & {
								encrypted_embeds?: EncryptedEmbedForDirectus[];
							}
						).encrypted_embeds = encryptedEmbeds;
						console.info(
							`[ChatSyncService:Senders] Including ${encryptedEmbeds.length} client-encrypted embeds for direct Directus storage`
						);
					}
				}
			} catch (encryptError) {
				console.error(
					"[ChatSyncService:Senders] Error preparing encrypted embeds:",
					encryptError
				);
				// Non-fatal: embeds will still be cached server-side for AI, just not stored in Directus
			}
		}
		encryptSpan.end();
	}

	// Include encrypted suggestion for deletion if user clicked a new chat suggestion
	if (encryptedSuggestionToDelete) {
		payload.encrypted_suggestion_to_delete = encryptedSuggestionToDelete;
		console.debug(
			"[ChatSyncService:Senders] Including encrypted suggestion for server deletion"
		);
	}

	console.debug(
		"[ChatSyncService:Senders] Phase 1: Sending plaintext-only message for AI processing:",
		{
			messageId: message.message_id,
			chatId: message.chat_id,
			hasPlaintextContent: !!message.content,
			chatHasTitle: chatHasTitle,
			titleV: chat?.title_v,
			messagesV: chat?.messages_v
		}
	);

	// OTel: WebSocket dispatch span — the actual send over the wire
	const wsDispatchSpan = tracer.startSpan('message.send.websocket_dispatch');
	// Inject W3C traceparent into WS payload for backend trace correlation
	injectTraceparent(payload as unknown as Record<string, unknown>);
	try {
		await webSocketService.sendMessage("chat_message_added", payload);
	} catch (error) {
		console.error(
			`[ChatSyncService:Senders] Error sending 'chat_message_added' for message_id: ${message.message_id}:`,
			error
		);
		try {
			// IMPORTANT: Use updateMessageStatus() NOT getMessage()→spread→saveMessage().
			// saveMessage() calls encryptMessageFields() → getOrGenerateChatKey(), which
			// silently generates a new random key if the chat key is absent from the in-memory
			// cache, re-encrypting the message and causing "[Content decryption failed]" on
			// the sender's device. updateMessageStatus() patches only the status field in-place
			// via a raw IndexedDB transaction with no encryption involved.
			//
			// The chat_id mismatch guard is preserved via a getMessage() preflight check,
			// but the actual status write always goes through updateMessageStatus().
			const existingMessage = await chatDB.getMessage(message.message_id);

			if (existingMessage && existingMessage.chat_id !== message.chat_id) {
				console.warn(
					`[ChatSyncService:Senders] Message ${message.message_id} found in DB but with different chat_id (${existingMessage.chat_id}) than expected (${message.chat_id}). Skipping status update to avoid corrupting wrong chat.`
				);
			} else {
				// Message found with correct chat_id, or not found yet (updateMessageStatus
				// is a no-op when the message doesn't exist, which is safe here).
				await chatDB.updateMessageStatus(message.message_id, "failed");
				serviceInstance.dispatchEvent(
					new CustomEvent("messageStatusChanged", {
						detail: {
							chatId: message.chat_id,
							messageId: message.message_id,
							status: "failed"
						}
					})
				);
			}
		} catch (dbError) {
			console.error(
				`[ChatSyncService:Senders] Error updating message status to 'failed' in DB for ${message.message_id}:`,
				dbError
			);
		}
	} finally {
		wsDispatchSpan.end();
	}
	} finally {
		implSpan.end();
	}
}

export async function sendCompletedAIResponseImpl(
	serviceInstance: ChatSynchronizationService,
	aiMessage: Message
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		// Queue for replay on reconnect instead of silently dropping — a dropped
		// ai_response_completed leaves messages_v permanently stale on the server,
		// making the AI reply invisible even after logout+login (no version gap detected).
		const { addPendingAIResponse } = await import("./pendingAIResponses");
		addPendingAIResponse(aiMessage.message_id, aiMessage.chat_id);
		console.warn(
			`[ChatSyncService:Senders] WebSocket not connected. Queued AI response ${aiMessage.message_id} for reconnect.`
		);
		return;
	}

	// CRITICAL: Prevent duplicate sends for the same message ID
	if (serviceInstance.isMessageSyncing(aiMessage.message_id)) {
		console.info(
			`[ChatSyncService:Senders] AI response ${aiMessage.message_id} is already being synced, skipping duplicate send.`
		);
		return;
	}

	// Mark as syncing
	serviceInstance.markMessageSyncing(aiMessage.message_id);

	try {
		// For completed AI responses, we send encrypted content + updated messages_v for Directus storage
		// The server should NOT process this as a new message or trigger AI processing

		// Get the chat to access the chat key for encryption and to increment messages_v
		const chat = await chatDB.getChat(aiMessage.chat_id);
		if (!chat) {
			console.error(
				`[ChatSyncService:Senders] Chat ${aiMessage.chat_id} not found for AI response encryption`
			);
			serviceInstance.unmarkMessageSyncing(aiMessage.message_id);
			return;
		}

		// MESSAGES_V HANDLING: For assistant responses, the server already incremented
		// messages_v in the cache and sent the new version via `chat_message_added`.
		// The `handleChatMessageReceivedImpl` handler is the SOLE authority for
		// writing the server's messages_v to IndexedDB.
		// DO NOT write the chat back here — the previous addChat() call created a
		// race condition: if `chat_message_added` updated messages_v between our
		// getChat() read above and the addChat() write, we would CLOBBER the
		// correct value with a stale one, causing permanent client/server drift.
		const newMessagesV = chat.messages_v || 1;
		const newLastEdited = aiMessage.created_at;

		console.debug(
			`[ChatSyncService:Senders] Using current messages_v for chat ${chat.chat_id}: ${newMessagesV} (not writing back to IDB — version owned by chat_message_added handler)`
		);

		// Encrypt the completed AI response for storage
		// CRITICAL FIX: await getEncryptedFields since it's now async to prevent storing Promises
		const encryptedFields = await chatDB.getEncryptedFields(
			aiMessage,
			aiMessage.chat_id
		);

		// Create payload with encrypted content AND version info (like user messages)
		const payload = {
			chat_id: aiMessage.chat_id,
			message: {
				message_id: aiMessage.message_id,
				chat_id: aiMessage.chat_id,
				role: aiMessage.role, // 'assistant' or 'system' (for rejection messages like insufficient credits)
				created_at: aiMessage.created_at,
				status: aiMessage.status,
				user_message_id: aiMessage.user_message_id,
				// ONLY encrypted fields - no plaintext content
				encrypted_content: encryptedFields.encrypted_content,
				encrypted_category: encryptedFields.encrypted_category,
				encrypted_model_name: encryptedFields.encrypted_model_name,
				// Thinking content is also encrypted client-side for zero-knowledge sync
				encrypted_thinking_content: encryptedFields.encrypted_thinking_content,
				encrypted_thinking_signature:
					encryptedFields.encrypted_thinking_signature,
				// PII mappings (encrypted) - typically only on user messages, included for completeness
				encrypted_pii_mappings: encryptedFields.encrypted_pii_mappings,
				// Non-encrypted metadata for UI/cost tracking (safe to store as plain integers/booleans)
				has_thinking: aiMessage.has_thinking,
				thinking_token_count: aiMessage.thinking_token_count
			},
			// Version info for chat update (matches user message pattern)
			versions: {
				messages_v: newMessagesV,
				last_edited_overall_timestamp: newLastEdited
			}
		};

		console.debug(
			"[ChatSyncService:Senders] Sending completed AI response for Directus storage:",
			{
				messageId: aiMessage.message_id,
				chatId: aiMessage.chat_id,
				hasEncryptedContent: !!encryptedFields.encrypted_content,
				role: aiMessage.role,
				newMessagesV: newMessagesV,
				hasThinking: !!aiMessage.has_thinking,
				thinkingTokenCount: aiMessage.thinking_token_count || 0
			}
		);

		// Route system messages (e.g., insufficient credits rejections) through the
		// system message handler, since ai_response_completed only accepts role='assistant'.
		if (aiMessage.role === "system") {
			console.debug(
				"[ChatSyncService:Senders] Routing system message through chat_system_message_added:",
				{ messageId: aiMessage.message_id, chatId: aiMessage.chat_id }
			);
			await webSocketService.sendMessage("chat_system_message_added", {
				chat_id: aiMessage.chat_id,
				message: {
					message_id: aiMessage.message_id,
					role: "system",
					encrypted_content: encryptedFields.encrypted_content,
					created_at: aiMessage.created_at,
					// Include user_message_id so other devices can link the rejection to its
					// triggering user message (enables sidebar "Credits needed..." + user preview)
					user_message_id: aiMessage.user_message_id,
					// Preserve status so other devices store the correct state (e.g., "waiting_for_user")
					status: aiMessage.status
				}
			});
		} else {
			// Use a different event type to avoid triggering AI processing
			await webSocketService.sendMessage("ai_response_completed", payload);
		}

		// Dispatch event so UI knows chat was updated
		serviceInstance.dispatchEvent(
			new CustomEvent("chatUpdated", {
				detail: { chat_id: chat.chat_id, chat }
			})
		);
	} catch (error) {
		console.error(
			`[ChatSyncService:Senders] Error sending completed AI response for message_id: ${aiMessage.message_id}:`,
			error
		);
		// Ensure we unmark on error so it can be retried if needed
		serviceInstance.unmarkMessageSyncing(aiMessage.message_id);
	}
}

/**
 * Send encrypted storage package - Dual-Phase Architecture Phase 2
 * Encrypts user data (user message, title, category) and sends to server for storage
 * AI responses are handled separately via ai_response_completed event
 */
export async function sendEncryptedStoragePackage(
	serviceInstance: ChatSynchronizationService,
	data: {
		chat_id: string;
		plaintext_title?: string;
		plaintext_category?: string;
		plaintext_icon?: string;
		user_message: Message;
		task_id?: string;
		updated_chat?: Chat; // Optional pre-fetched chat with updated versions
	}
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] Cannot send encrypted storage package, WebSocket not connected."
		);
		return;
	}

	// CRITICAL: Prevent duplicate sends for the same user message ID.
	// This guards against ai_typing_started firing twice (e.g. on WebSocket reconnect)
	// which would generate a new chat key the second time (if encrypted_chat_key isn't
	// yet persisted to DB), corrupting the chat for all devices on reload.
	const messageId = data.user_message.message_id;
	if (serviceInstance.isMessageSyncing(messageId)) {
		console.info(
			`[ChatSyncService:Senders] User message ${messageId} is already being synced (encrypted storage package in-flight), skipping duplicate send.`
		);
		return;
	}
	serviceInstance.markMessageSyncing(messageId);

	// CRITICAL FIX: Acquire critical operation lock to prevent clearAll() from wiping
	// the key cache mid-flight. Without this lock, an auth disruption (e.g. token expiry
	// triggering WebSocket "Authentication failed") calls clearAll() which wipes keys.
	// This function then falls through to CASE 2 (new key generation), creating key K2
	// while the user message in IDB was encrypted with K1 — permanent decryption failure.
	chatKeyManager.acquireCriticalOp();

	try {
		const {
			chat_id,
			plaintext_title,
			plaintext_category,
			plaintext_icon,
			user_message,
			task_id,
			updated_chat
		} = data;

		// Get chat object for version info - use provided chat or fetch from DB
		const chat = updated_chat || (await chatDB.getChat(chat_id));
		if (!chat) {
			console.error(
				`[ChatSyncService:Senders] Chat ${chat_id} not found for encrypted storage`
			);
			return;
		}

		console.debug(
			`[ChatSyncService:Senders] Using chat with title_v: ${chat.title_v}, messages_v: ${chat.messages_v}`
		);

		// CRITICAL FIX: Get chat key properly to ensure consistency across devices
		// 1. First try to get encrypted_chat_key from database
		// 2. If it exists, DECRYPT it to get the original key (ensures same key as other devices)
		// 3. If it doesn't exist (new chat), generate a new key
		//
		// This fixes the sync/encryption issue where a new key was generated if the key
		// wasn't in cache, causing messages to be encrypted with a different key than
		// what's stored in encrypted_chat_key and synced to other devices.
		console.log(
			`[ChatSyncService:Senders] Getting chat key for ${chat_id} (with encryption consistency fix)`
		);

		let encryptedChatKey = await chatDB.getEncryptedChatKey(chat_id);
		// Prefer any cached chat key first (covers hidden chats already unlocked).
		let chatKey: Uint8Array | null = await chatKeyManager.getKey(chat_id);

		if (chatKey && encryptedChatKey) {
			const keyMatches = await encryptedChatKeyMatchesRawKey(
				encryptedChatKey,
				chatKey,
				decryptChatKeyWithMasterKey
			);
			if (keyMatches === false) {
				await abortUnsafeKeyMismatch(
					chat_id,
					encryptedChatKey,
					"cached raw key differs from persisted encrypted_chat_key"
				);
				return;
			}
		}

		if (!chatKey && encryptedChatKey) {
			// CASE 1: encrypted_chat_key exists - MUST decrypt it to get the original key
			// This ensures we use the SAME key that was stored when the chat was created
			console.log(
				`[ChatSyncService:Senders] encrypted_chat_key found for ${chat_id}, decrypting to ensure key consistency...`
			);
			const decryptedKey = await decryptChatKeyWithMasterKey(encryptedChatKey);

			if (decryptedKey) {
				const accepted = chatDB.setChatKey(chat_id, decryptedKey);
				if (!accepted) {
					await abortUnsafeKeyMismatch(
						chat_id,
						encryptedChatKey,
						"decrypted persisted key was rejected by ChatKeyManager"
					);
					return;
				}
				chatKey = decryptedKey;
				console.log(
					`[ChatSyncService:Senders] ✅ Decrypted and cached chat key for ${chat_id}, length: ${chatKey.length}`
				);
			} else {
				// Decryption failed - this is a critical error for regular chats
				// or a hidden chat that is currently locked.
				console.error(
					`[ChatSyncService:Senders] ❌ CRITICAL: Failed to decrypt encrypted_chat_key for ${chat_id}. ` +
						`This indicates master key mismatch, locked hidden chat, or data corruption.`
				);

				// Attempt hidden chat decryption path (if unlocked).
				try {
					const { hiddenChatService } = await import("./hiddenChatService");
					const hiddenResult =
						await hiddenChatService.tryDecryptChatKey(encryptedChatKey);
					if (hiddenResult.chatKey) {
						const accepted = chatDB.setChatKey(chat_id, hiddenResult.chatKey);
						if (!accepted) {
							await abortUnsafeKeyMismatch(
								chat_id,
								encryptedChatKey,
								"hidden-chat decrypted key was rejected by ChatKeyManager"
							);
							return;
						}
						chatKey = hiddenResult.chatKey;
						console.info(
							`[ChatSyncService:Senders] ✅ Decrypted chat key via hidden chat path for ${chat_id}`
						);
					}
				} catch (hiddenError) {
					console.error(
						`[ChatSyncService:Senders] Hidden chat decryption path failed for ${chat_id}:`,
						hiddenError
					);
				}

				if (!chatKey) {
					// IMPORTANT: Do NOT generate a new key for an existing chat.
					// That would corrupt the chat for all devices.
					try {
						const { notificationStore } = await import("../stores/notificationStore");
						notificationStore.error(
							"We could not safely store this message due to an encryption key mismatch. " +
								"Please unlock hidden chats or log in again on this device."
						);
					} catch {
						// If notification import fails, still abort safely.
					}
					return;
				}
			}
		}

		if (!encryptedChatKey) {
			// CASE 2: No encrypted_chat_key - this is a new chat, generate and save key
			// SAFETY: Re-read IDB before generating a new key. Another tab or a deferred
			// write from this tab might have stored encrypted_chat_key since our first read.
			const freshChat = await chatDB.getChat(chat_id);
			const freshEncKey = freshChat?.encrypted_chat_key;
			if (freshEncKey) {
				console.info(
					`[ChatSyncService:Senders] encrypted_chat_key appeared on re-read for ${chat_id} — using existing key instead of generating`
				);
				encryptedChatKey = freshEncKey;
				if (!chatKey) {
					chatKey = await decryptChatKeyWithMasterKey(freshEncKey);
					if (chatKey) {
						const accepted = chatDB.setChatKey(chat_id, chatKey);
						if (!accepted) {
							await abortUnsafeKeyMismatch(
								chat_id,
								freshEncKey,
								"freshly re-read encrypted_chat_key was rejected by ChatKeyManager"
							);
							return;
						}
					}
				}
			}
		}

		if (!encryptedChatKey) {
			console.warn(
				`[ChatSyncService:Senders] ⚠️ encrypted_chat_key missing for ${chat_id}, generating new key (new chat)`
			);
			// New chat on originating device — use atomic createAndPersistKey to ensure
			// the key is persisted to IDB before any data is encrypted with it.
			// This prevents the race where key K1 is in memory but not in IDB, a
			// disruption wipes memory, and a new key K2 is generated.
			if (!chatKey) {
				chatKey = chatKeyManager.getKeySync(chat_id);
			}

			if (!chatKey) {
				try {
					const result = await chatKeyManager.createAndPersistKey(chat_id);
					chatKey = result.chatKey;
					encryptedChatKey = result.encryptedChatKey;
					chat.encrypted_chat_key = encryptedChatKey;
					console.log(
						`[ChatSyncService:Senders] ✅ Atomically created and persisted key for ${chat_id}: ${encryptedChatKey.substring(0, 20)}...`
					);
				} catch (error) {
					console.error(
						`[ChatSyncService:Senders] ❌ Failed to create/persist chat key for ${chat_id}:`,
						error
					);
				}
			} else {
				// Key found in memory but not persisted — encrypt and save
				encryptedChatKey = await encryptChatKeyWithMasterKey(chatKey);
				if (encryptedChatKey) {
					chat.encrypted_chat_key = encryptedChatKey;
					await chatDB.updateChat(chat);
					console.log(
						`[ChatSyncService:Senders] ✅ Persisted existing key for ${chat_id}: ${encryptedChatKey.substring(0, 20)}...`
					);
				} else {
					console.error(
						`[ChatSyncService:Senders] ❌ Failed to encrypt chat key for ${chat_id} - master key may be missing`
					);
				}
			}
		}

		if (!chatKey) {
			console.error(
				`[ChatSyncService:Senders] ❌ CRITICAL: No chat key available for ${chat_id}. Aborting encrypted storage.`
			);
			return;
		}

		console.log(
			`[ChatSyncService:Senders] Chat key obtained for ${chat_id}, length: ${chatKey.length}`
		);

		// Import encryption functions
		// CRITICAL FIX: Ensure user message has content before encrypting
		// If content is missing, try to get it from encrypted_content (shouldn't happen, but defensive)
		if (!user_message.content && user_message.encrypted_content) {
			console.warn(
				`[ChatSyncService:Senders] User message ${user_message.message_id} missing content field, attempting to decrypt from encrypted_content`
			);
			try {
				const decrypted = await decryptWithChatKey(
					user_message.encrypted_content,
					chatKey
				);
				if (decrypted) {
					user_message.content = decrypted;
					console.info(
						`[ChatSyncService:Senders] Successfully decrypted content for message ${user_message.message_id}`
					);
				}
			} catch (decryptError) {
				console.error(
					`[ChatSyncService:Senders] Failed to decrypt content for message ${user_message.message_id}:`,
					decryptError
				);
			}
		}

		// CRITICAL FIX: encryptWithChatKey is async - must await it!
		// Encrypt user message content
		const encryptedUserContent = user_message.content
			? typeof user_message.content === "string"
				? await encryptWithChatKey(user_message.content, chatKey)
				: await encryptWithChatKey(JSON.stringify(user_message.content), chatKey)
			: null;

		// CRITICAL: Validate that we have encrypted content before sending
		if (!encryptedUserContent) {
			console.error(
				`[ChatSyncService:Senders] ❌ CRITICAL: Cannot send encrypted user message ${user_message.message_id} - no content available to encrypt!`,
				{
					hasContent: !!user_message.content,
					hasEncryptedContent: !!user_message.encrypted_content,
					messageId: user_message.message_id,
					chatId: chat_id
				}
			);
			// Don't send if we can't encrypt the user message - this is a critical error
			return;
		}

		// CRITICAL FIX: encryptWithChatKey is async - must await all encryption operations!
		// Encrypt user message metadata
		const encryptedUserSenderName = user_message.sender_name
			? await encryptWithChatKey(user_message.sender_name, chatKey)
			: null;
		const encryptedUserCategory = plaintext_category
			? await encryptWithChatKey(plaintext_category, chatKey)
			: null;

		// NOTE: encrypted_model_name is NOT sent with user messages - it should only be stored on assistant messages
		// The model_name indicates which AI model generated the assistant's response, not which model will respond
		// The model_name will be sent when the assistant message is completed

		// AI response is handled separately - not part of immediate storage

		// Encrypt title with chat-specific key (for chat-level metadata)
		const encryptedTitle = plaintext_title
			? await encryptWithChatKey(plaintext_title, chatKey)
			: null;

		// Encrypt icon with chat-specific key (for chat-level metadata)
		const encryptedIcon = plaintext_icon
			? await encryptWithChatKey(plaintext_icon, chatKey)
			: null;

		// Encrypt category with chat-specific key (for chat-level metadata)
		const encryptedCategory = plaintext_category
			? await encryptWithChatKey(plaintext_category, chatKey)
			: null;

		// Encrypt PII mappings if the user message has any (for cross-device sync).
		// PII mappings map placeholders like [EMAIL_1] back to original values.
		let encryptedPIIMappings: string | null = null;
		if (user_message.pii_mappings && user_message.pii_mappings.length > 0) {
			try {
				const piiMappingsJson = JSON.stringify(user_message.pii_mappings);
				encryptedPIIMappings = await encryptWithChatKey(piiMappingsJson, chatKey);
				console.debug(
					`[ChatSyncService:Senders] Encrypted PII mappings for message ${user_message.message_id}: ${user_message.pii_mappings.length} mappings`
				);
			} catch (piiEncryptError) {
				console.error(
					`[ChatSyncService:Senders] Failed to encrypt PII mappings for message ${user_message.message_id}:`,
					piiEncryptError
				);
			}
		}

		// Create encrypted metadata payload for new handler
		// CRITICAL: Only include metadata fields if they're actually set (not null)
		// For follow-up messages, metadata fields should be undefined/null and NOT included
		interface MetadataPayload {
			chat_id: string;
			message_id: string;
			encrypted_content: string;
			encrypted_sender_name?: string;
			encrypted_category?: string;
			encrypted_pii_mappings?: string;
			encrypted_title?: string;
			encrypted_chat_category?: string;
			encrypted_icon?: string;
			encrypted_chat_summary?: string;
			encrypted_chat_tags?: string;
			encrypted_follow_up_suggestions?: string;
			encrypted_new_chat_suggestions?: string;
			encrypted_top_recommended_apps_for_chat?: string;
			created_at: number;
			encrypted_chat_key?: string;
			versions: {
				messages_v: number;
				title_v: number;
				last_edited_overall_timestamp: number;
			};
			task_id?: string;
		}
		const metadataPayload: MetadataPayload = {
			chat_id,
			// User message fields (ALWAYS included)
			message_id: user_message.message_id,
			encrypted_content: encryptedUserContent,
			encrypted_sender_name: encryptedUserSenderName,
			encrypted_category: encryptedUserCategory, // User message category
			// NOTE: encrypted_model_name is NOT included for user messages - only for assistant messages
			created_at: user_message.created_at,
			// Chat key (ALWAYS included for new chats, may be undefined for follow-ups if already stored)
			encrypted_chat_key: encryptedChatKey,
			// Version info - use actual values from chat object
			versions: {
				messages_v: chat.messages_v || 0,
				title_v: chat.title_v || 0, // Use title_v from updated chat (should be incremented)
				last_edited_overall_timestamp: user_message.created_at
			},
			task_id
		};

		// ONLY include chat metadata fields if they're set (NEW CHATS ONLY)
		// For follow-ups, these will be null and should NOT be sent to avoid overwriting existing metadata
		if (encryptedTitle) {
			metadataPayload.encrypted_title = encryptedTitle;
		}
		if (encryptedIcon) {
			metadataPayload.encrypted_icon = encryptedIcon;
		}
		if (encryptedCategory) {
			metadataPayload.encrypted_chat_category = encryptedCategory;
		}
		// Include encrypted PII mappings on the user message (for cross-device PII restoration)
		if (encryptedPIIMappings) {
			metadataPayload.encrypted_pii_mappings = encryptedPIIMappings;
		}

		console.info("[ChatSyncService:Senders] Sending encrypted chat metadata:", {
			chatId: chat_id,
			messageId: metadataPayload.message_id,
			hasEncryptedTitle: !!encryptedTitle,
			hasEncryptedIcon: !!encryptedIcon,
			hasEncryptedCategory: !!encryptedCategory,
			hasEncryptedUserMessage: !!encryptedUserContent,
			hasEncryptedUserContent: !!metadataPayload.encrypted_content,
			encryptedContentLength: encryptedUserContent?.length || 0,
			titleVersion: metadataPayload.versions.title_v,
			messagesVersion: metadataPayload.versions.messages_v,
			payloadKeys: Object.keys(metadataPayload).join(", ")
		});

		// CRITICAL: Ensure encrypted_content is always included if we have it
		if (!metadataPayload.encrypted_content && encryptedUserContent) {
			console.error(
				`[ChatSyncService:Senders] ❌ CRITICAL BUG: encryptedUserContent exists but not in payload!`,
				{
					encryptedUserContent: encryptedUserContent.substring(0, 50) + "...",
					payloadHasEncryptedContent: !!metadataPayload.encrypted_content
				}
			);
			// Force it into the payload
			metadataPayload.encrypted_content = encryptedUserContent;
		}

		// Send to server via new encrypted_chat_metadata handler
		await webSocketService.sendMessage("encrypted_chat_metadata", metadataPayload);

		// Unmark after successful send so subsequent retries (e.g. from reconnect) are allowed
		// once the in-flight send is confirmed. The guard above prevents concurrent duplicates.
		serviceInstance.unmarkMessageSyncing(messageId);
	} catch (error) {
		console.error(
			"[ChatSyncService:Senders] Error sending encrypted storage package:",
			error
		);
		// Unmark on error so a legitimate retry can proceed
		serviceInstance.unmarkMessageSyncing(messageId);
	} finally {
		// CRITICAL: Always release the lock so deferred clearAll() can proceed.
		chatKeyManager.releaseCriticalOp();
	}
}
