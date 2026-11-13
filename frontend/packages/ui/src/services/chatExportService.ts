/**
 * Chat Export Service
 * Handles exporting chat content as markdown files
 */

import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { chatMetadataCache } from "./chatMetadataCache";
import { tipTapToCanonicalMarkdown } from "../message_parsing/serializers";
import type { Chat, ChatCompressionCheckpoint, Message, PIIMapping } from "../types/chat";
import {
  extractEmbedReferences,
  loadEmbeds,
  decodeToonContent,
} from "./embedResolver";
import type { TipTapDoc } from "../message_parsing/types";
import { copyToClipboard } from "../utils/clipboardUtils";
import type * as RustChatExport from "./rustCore/transfer/rustChatExport";
import type { TransferExportEmbed } from "./rustCore/transfer/transferProtocol";

/** An embed as collected for export (decoded content, raw timestamps), before shaping. */
type ChatExportEmbedRecord = TransferExportEmbed;

/**
 * Options for controlling PII handling during export.
 * Message content from DB contains PLACEHOLDERS (e.g., "[EMAIL_1]").
 * When piiHidden is false (revealed), we restore originals for the export.
 * When piiHidden is true (default), content keeps placeholders as-is.
 */
export interface PIIExportOptions {
  /** Whether PII should be hidden in the export (placeholders instead of originals) */
  piiHidden: boolean;
  /** Cumulative PII mappings from all user messages in the chat */
  piiMappings: PIIMapping[];
}

export interface ChatExportHydrationResult {
  messages: Message[];
  checkpoints: ChatCompressionCheckpoint[];
  completeness: {
    status: "complete" | "partial";
    requested_message_count: number;
    hydrated_message_count: number;
    checkpoint_count: number;
    warnings: string[];
  };
}

export async function hydrateChatForExport(
  chat: Chat,
  renderedMessages: Message[],
): Promise<ChatExportHydrationResult> {
  const warnings: string[] = [];
  let messages = renderedMessages;
  try {
    const allLocalMessages = await chatDB.getMessagesForChat(chat.chat_id);
    if (allLocalMessages.length > renderedMessages.length) {
      messages = allLocalMessages;
    }
  } catch (error) {
    warnings.push("Could not hydrate additional local message pages before export.");
    console.warn("[ChatExportService] Failed to hydrate full local message history", error);
  }

  let checkpoints: ChatCompressionCheckpoint[] = [];
  try {
    checkpoints = await chatDB.getChatCompressionCheckpoints(chat.chat_id);
  } catch (error) {
    warnings.push("Could not hydrate compression checkpoint summaries before export.");
    console.warn("[ChatExportService] Failed to hydrate compression checkpoints", error);
  }

  const requestedMessageCount = Number.isFinite(chat.messages_v) ? chat.messages_v : messages.length;
  if (requestedMessageCount > messages.length) {
    warnings.push(`Only ${messages.length} of ${requestedMessageCount} durable messages were available locally.`);
  }
  if (checkpoints.length > 0 && checkpoints.some((checkpoint) => checkpoint.compressed_message_count > 0)) {
    const missingForgotten = checkpoints.some(
      (checkpoint) =>
        messages.filter((message) => message.created_at <= checkpoint.compressed_up_to_timestamp).length <
        checkpoint.compressed_message_count,
    );
    if (missingForgotten) {
      warnings.push("This chat has compression checkpoints; some forgotten raw messages may require server hydration before export is complete.");
    }
  }

  const sortedMessages = [...messages].sort(
    (a, b) => a.created_at - b.created_at || a.message_id.localeCompare(b.message_id),
  );
  return {
    messages: sortedMessages,
    checkpoints,
    completeness: {
      status: warnings.length === 0 ? "complete" : "partial",
      requested_message_count: requestedMessageCount,
      hydrated_message_count: sortedMessages.length,
      checkpoint_count: checkpoints.length,
      warnings,
    },
  };
}

/**
 * Downloads a chat as a YAML file
 * @param chat - The chat to download
 * @param messages - Array of messages in the chat
 */
export async function downloadChatAsYaml(
  chat: Chat,
  messages: Message[],
): Promise<void> {
  try {
    console.debug("[ChatExportService] Starting chat download:", {
      chatId: chat.chat_id,
      messageCount: messages.length,
      hasEncryptedTitle: !!chat.encrypted_title,
    });

    // Generate filename with date, time, and title
    const filename = await generateChatFilename(chat, "yaml");

    const hydrated = await hydrateChatForExport(chat, messages);
    if (hydrated.completeness.status === "partial") {
      console.warn("[ChatExportService] Export is partial:", hydrated.completeness.warnings);
    }

    // Convert chat and messages to YAML
    const yamlContent = await convertChatToYaml(chat, hydrated.messages, false, undefined, hydrated);

    // Create and download the file
    downloadYamlFile(yamlContent, filename);

    console.debug("[ChatExportService] Chat download completed successfully");
  } catch (error) {
    console.error("[ChatExportService] Error downloading chat:", error);
    throw new Error("Failed to download chat");
  }
}

/**
 * Generates a filename for the chat export
 * Format: YYYY-MM-DD_HH-MM-SS_[title].yaml
 * Uses the chat's creation date/time instead of current date/time
 */
export async function generateChatFilename(
  chat: Chat,
  extension: string = "yaml",
): Promise<string> {
  const { rustGenerateChatFilename } = await import("./rustCore/transfer/rustChatExport");
  const cached = await chatMetadataCache.getDecryptedMetadata(chat);
  return rustGenerateChatFilename(chat.created_at, cached?.title, chat.title, extension);
}

/**
 * Recursively loads embeds including nested child embeds
 * @param embedIds - Array of embed IDs to load
 * @param loadedEmbedIds - Set of already loaded embed IDs to avoid duplicates
 * @returns Array of embed data with decoded content
 */
async function loadEmbedsRecursively(
  embedIds: string[],
  loadedEmbedIds: Set<string> = new Set(),
): Promise<ChatExportEmbedRecord[]> {
  const embedsForExport: ChatExportEmbedRecord[] = [];

  // Filter out already loaded embeds
  const newEmbedIds = embedIds.filter((id) => !loadedEmbedIds.has(id));
  if (newEmbedIds.length === 0) {
    return embedsForExport;
  }

  // Mark these as being loaded
  newEmbedIds.forEach((id) => loadedEmbedIds.add(id));

  // Load embeds from EmbedStore
  const loadedEmbeds = await loadEmbeds(newEmbedIds);

  // Process each embed
  for (const embed of loadedEmbeds) {
    try {
      // DEBUG: Log embed structure to diagnose missing content
      console.debug("[ChatExportService] Processing embed for export:", {
        embed_id: embed.embed_id,
        type: embed.type,
        hasContent: "content" in embed,
        contentType: typeof embed.content,
        contentLength: embed.content ? String(embed.content).length : 0,
        contentPreview: embed.content
          ? String(embed.content).substring(0, 100)
          : "MISSING",
        embedKeys: Object.keys(embed),
      });

      // Check if content field exists and is a string
      if (!embed.content || typeof embed.content !== "string") {
        console.error(
          "[ChatExportService] Embed missing content field or content is not a string:",
          {
            embed_id: embed.embed_id,
            hasContent: "content" in embed,
            contentType: typeof embed.content,
            embedKeys: Object.keys(embed),
          },
        );
        // Include embed with error indicator
        embedsForExport.push({
          kind: "error",
          embed_id: embed.embed_id,
          type: embed.type,
          error: "Embed content field is missing or invalid",
        });
        continue;
      }

      // Decode TOON content to get actual embed values
      const decodedContent = await decodeToonContent(embed.content);

      // Collect embed metadata and decoded content; timestamps and the final
      // export object are shaped by Rust.
      const embedExport: ChatExportEmbedRecord = {
        kind: "ok",
        embed_id: embed.embed_id,
        type: embed.type,
        status: embed.status,
        content: decodedContent, // Decoded content (actual values, not TOON)
        createdAt: embed.createdAt,
        updatedAt: embed.updatedAt,
        text_preview: embed.text_preview,
      };

      // Handle nested embeds (composite embeds like app_skill_use)
      const childEmbedIds: string[] = [];

      // Check for embed_ids in the decoded content (for composite embeds)
      if (decodedContent && typeof decodedContent === "object") {
        const decoded = decodedContent as Record<string, unknown>;
        // Check if decoded content has embed_ids (could be array or pipe-separated string)
        if (Array.isArray(decoded.embed_ids)) {
          childEmbedIds.push(...(decoded.embed_ids as string[]));
        } else if (typeof decoded.embed_ids === "string") {
          // Handle pipe-separated string format
          childEmbedIds.push(
            ...decoded.embed_ids.split("|").filter((id: string) => id.trim()),
          );
        }
      }

      // Also check embed.embed_ids directly (from the embed metadata)
      if (embed.embed_ids && Array.isArray(embed.embed_ids)) {
        childEmbedIds.push(...embed.embed_ids);
      }

      // Remove duplicates
      const uniqueChildEmbedIds = Array.from(new Set(childEmbedIds));

      // Recursively load child embeds
      if (uniqueChildEmbedIds.length > 0) {
        console.debug(
          "[ChatExportService] Loading nested embeds for composite embed:",
          {
            parentEmbedId: embed.embed_id,
            childCount: uniqueChildEmbedIds.length,
            childIds: uniqueChildEmbedIds,
          },
        );

        const childEmbeds = await loadEmbedsRecursively(
          uniqueChildEmbedIds,
          loadedEmbedIds,
        );
        embedsForExport.push(...childEmbeds);

        // Note: embed_ids are already included in the decoded content, so we don't duplicate them here
      }

      embedsForExport.push(embedExport);
    } catch (error) {
      console.warn(
        "[ChatExportService] Error decoding embed content:",
        embed.embed_id,
        error,
      );
      // Include embed with error indicator
      embedsForExport.push({
        kind: "error",
        embed_id: embed.embed_id,
        type: embed.type,
        error: "Failed to decode embed content",
      });
    }
  }

  return embedsForExport;
}

/**
 * Gets all embeds for a chat by extracting embed references from messages and loading their content
 * Includes nested embeds (child embeds from composite embeds like app_skill_use)
 * @param messages - Array of messages in the chat
 * @returns Array of embed data with decoded content
 */
async function getAllEmbedsForChat(messages: Message[]): Promise<ChatExportEmbedRecord[]> {
  try {
    console.debug("[ChatExportService] Collecting embeds for chat export");

    // Extract all embed references from all messages
    const embedRefs = new Map<
      string,
      { type: string; embed_id: string; version?: number }
    >();

    for (const message of messages) {
      // Get message content as markdown string
      let markdownContent = "";
      if (typeof message.content === "string") {
        markdownContent = message.content;
      } else if (message.content && typeof message.content === "object") {
        // Convert TipTap JSON to markdown to extract embed references
        markdownContent = tipTapToCanonicalMarkdown(message.content);
      }

      // Extract embed references from markdown content
      const refs = extractEmbedReferences(markdownContent);
      for (const ref of refs) {
        // Use embed_id as key to avoid duplicates
        embedRefs.set(ref.embed_id, ref);
      }
    }

    if (embedRefs.size === 0) {
      console.debug("[ChatExportService] No embeds found in chat messages");
      return [];
    }

    // Load all embeds recursively (including nested child embeds)
    const embedIds = Array.from(embedRefs.keys());
    console.debug("[ChatExportService] Loading embeds recursively:", {
      embedCount: embedIds.length,
      embedIds,
    });

    const embedsForExport = await loadEmbedsRecursively(embedIds);

    console.debug(
      "[ChatExportService] Successfully prepared embeds for export:",
      { count: embedsForExport.length },
    );
    return embedsForExport;
  } catch (error) {
    console.error("[ChatExportService] Error getting embeds for chat:", error);
    // Return empty array on error to not block export
    return [];
  }
}

/**
 * Converts a chat and its messages to YAML format
 * @param chat - The chat to convert
 * @param messages - Array of messages
 * @param includeLink - Whether to include the shareable link in the YAML (default: false for downloads, true for clipboard)
 * @param piiOptions - Optional PII export options to control sensitive data handling
 */
export async function convertChatToYaml(
  chat: Chat,
  messages: Message[],
  includeLink: boolean = false,
  piiOptions?: PIIExportOptions,
  hydration?: ChatExportHydrationResult,
): Promise<string> {
  const { rustConvertChatToYaml } = await import("./rustCore/transfer/rustChatExport");
  return rustConvertChatToYaml(
    { chat, messages, includeLink, piiOptions, hydration },
    chatExportPageIO,
  );
}

/**
 * Thinking text of an assistant message: the already decrypted
 * `thinking_content`, else `encrypted_thinking_content` decrypted with the chat
 * key (page IO: key manager and crypto). Failures are logged and omit the text.
 */
async function resolveThinkingText(message: Message): Promise<string | undefined> {
  // Try decrypted thinking_content first (if already decrypted)
  if (message.thinking_content) {
    console.debug(
      "[ChatExportService] Included decrypted thinking content in export",
    );
    return message.thinking_content;
  }
  // Fall back to encrypted_thinking_content and decrypt it
  if (message.encrypted_thinking_content) {
    try {
      // Get chat key for this message's chat to decrypt thinking content
      const chatKey = await chatKeyManager.getKey(message.chat_id);
      if (chatKey) {
        const { decryptWithChatKey } = await import("./cryptoService");
        const decryptedThinking = await decryptWithChatKey(
          message.encrypted_thinking_content,
          chatKey,
        );
        if (decryptedThinking) {
          console.debug(
            "[ChatExportService] Decrypted and included thinking content in export",
          );
          return decryptedThinking;
        }
      } else {
        console.warn(
          "[ChatExportService] Could not decrypt thinking content: chat key not available",
        );
      }
    } catch (decryptError) {
      console.error(
        "[ChatExportService] Error decrypting thinking content:",
        decryptError,
      );
    }
  }
  return undefined;
}

/**
 * Message body as export Markdown: string content as is, TipTap JSON through the
 * canonical serializer, anything else empty. Page IO (the serializer stays TS).
 */
async function messageMarkdown(message: Message): Promise<string> {
  if (typeof message.content === "string") {
    return message.content;
  }
  if (message.content && typeof message.content === "object") {
    return convertTiptapToMarkdown(message.content as unknown as TipTapDoc);
  }
  return "";
}

/**
 * Converts TipTap JSON content to markdown
 * This is a simplified version - you might want to use a more robust converter
 */
async function convertTiptapToMarkdown(content: TipTapDoc): Promise<string> {
  if (!content || !content.content) {
    return "";
  }

  try {
    // Use the existing tipTapToCanonicalMarkdown function to convert TipTap to markdown
    const markdown = tipTapToCanonicalMarkdown(content);
    return markdown || "";
  } catch (error) {
    console.error(
      "[ChatExportService] Error converting TipTap to markdown:",
      error,
    );
    return "*[Error converting content]*";
  }
}

/**
 * Generates a shareable link for a chat
 * Format: {domain}/#chat-id={id}
 * @param chatId - The chat ID
 * @returns The shareable link
 */
export function generateChatLink(chatId: string): string {
  // Use window.location.origin to get current domain dynamically
  const baseUrl = window.location.origin;
  const link = `${baseUrl}/#chat-id=${chatId}`;

  console.debug("[ChatExportService] Generated chat link:", {
    chatId,
    link,
  });

  return link;
}

/**
 * Page-side inputs of the Rust export (metadata cache, crypto, serializers and
 * embed loading); the Rust unit builds everything else.
 */
const chatExportPageIO: RustChatExport.ChatExportPageIO = {
  decryptedMetadata: (chat) => chatMetadataCache.getDecryptedMetadata(chat),
  decryptDraft: async (encrypted) => {
    const { decryptWithMasterKey } = await import("./cryptoService");
    return decryptWithMasterKey(encrypted);
  },
  thinkingText: resolveThinkingText,
  messageMarkdown,
  collectEmbeds: getAllEmbedsForChat,
  chatLink: generateChatLink,
};

/**
 * Copies the chat to clipboard in YAML format wrapped in a markdown code block.
 * When pasted inside OpenMates, the embedded link is used to import the chat.
 * When pasted outside OpenMates, the full YAML is available as formatted text.
 * @param chat - The chat to copy
 * @param messages - Array of messages in the chat
 * @param piiOptions - Optional PII export options to control sensitive data handling
 */
export async function copyChatToClipboard(
  chat: Chat,
  messages: Message[],
  piiOptions?: PIIExportOptions,
): Promise<void> {
  try {
    console.debug("[ChatExportService] Copying chat to clipboard:", {
      chatId: chat.chat_id,
      messageCount: messages.length,
    });

    // Generate YAML with embedded link, respecting PII visibility
    const yamlContent = await convertChatToYaml(
      chat,
      messages,
      true,
      piiOptions,
    );

    // Wrap YAML content in a markdown code block for better formatting when pasted
    const codeBlock = `\`\`\`yaml\n${yamlContent}\n\`\`\``;

    // Copy via the unified ClipboardService (writeText → execCommand fallback chain)
    const result = await copyToClipboard(codeBlock);
    if (!result.success) {
      throw new Error(result.error || "Failed to copy to clipboard");
    }

    console.debug(
      `[ChatExportService] Chat copied to clipboard via ${result.method}`,
    );
  } catch (error) {
    // Extract error message for proper logging (Safari errors don't serialize well)
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error(
      "[ChatExportService] Error copying to clipboard. Error:",
      errorMsg,
    );
    throw new Error(`Failed to copy to clipboard: ${errorMsg}`);
  }
}

/**
 * Creates and triggers download of a YAML file
 */
function downloadYamlFile(content: string, filename: string): void {
  // Create blob with YAML content
  const blob = new Blob([content], { type: "text/yaml;charset=utf-8" });

  // Create download link
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;

  // Trigger download
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  // Clean up
  URL.revokeObjectURL(url);
}

/**
 * TODO: Future implementation for file attachments
 * This function will handle downloading files associated with the chat
 * when file upload functionality is implemented
 */
export async function downloadChatFiles(chatId: string): Promise<void> {
  // TODO: Implement file download functionality
  // This will be called when file uploads are implemented
  console.debug(
    "[ChatExportService] File download not yet implemented for chat:",
    chatId,
  );

  // Placeholder implementation:
  // 1. Get list of files associated with the chat
  // 2. Download each file
  // 3. Create a zip archive if multiple files
  // 4. Trigger download of the archive

  // Example structure:
  // const files = await getChatFiles(chatId);
  // if (files.length > 0) {
  //     await downloadFilesAsZip(files, `${chatId}_files.zip`);
  // }
}
