/**
 * Chat Export Service
 * Handles exporting chat content as markdown files
 */

import { chatDB } from "./db";
import { chatMetadataCache } from "./chatMetadataCache";
import { tipTapToCanonicalMarkdown } from "../message_parsing/serializers";
import type { Chat, Message } from "../types/chat";
import {
  extractEmbedReferences,
  loadEmbeds,
  decodeToonContent,
} from "./embedResolver";

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

    // Convert chat and messages to YAML
    const yamlContent = await convertChatToYaml(chat, messages);

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
  // Use chat's creation timestamp instead of current time
  // Handle both seconds (regular chats) and milliseconds (demo chats) timestamps
  // Timestamps in seconds are typically < 1e12 (before year ~2001 in ms)
  const timestampMs =
    chat.created_at < 1e12 ? chat.created_at * 1000 : chat.created_at;
  const chatDate = new Date(timestampMs);
  const dateStr = chatDate
    .toISOString()
    .slice(0, 19)
    .replace(/[:-]/g, "-")
    .replace("T", "_");

  let title = "Untitled Chat";

  // Try to get decrypted title from cache (handles both chat-key and master-key decryption)
  const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
  if (metadata?.title) {
    // Sanitize title for filename (remove invalid characters)
    title = metadata.title
      .replace(/[<>:"/\\|?*]/g, "") // Remove invalid filename characters
      .substring(0, 50) // Limit length
      .trim();
    console.debug(
      "[ChatExportService] Using decrypted title from cache:",
      title,
    );
  } else if (chat.title) {
    // Fallback for demo/public chats which use plaintext title field
    // Demo chats don't have encrypted_title - they have cleartext title
    title = chat.title
      .replace(/[<>:"/\\|?*]/g, "") // Remove invalid filename characters
      .substring(0, 50) // Limit length
      .trim();
    console.debug(
      "[ChatExportService] Using plaintext title (demo/public chat):",
      title,
    );
  } else {
    console.warn("[ChatExportService] Could not decrypt title, using default");
  }

  return `${dateStr}_${title}.${extension}`;
}

/**
 * Converts a timestamp to ISO string, handling both seconds and milliseconds
 * @param timestamp - Unix timestamp (in seconds or milliseconds)
 * @returns ISO string or null if invalid
 */
function formatTimestamp(timestamp: number | undefined | null): string | null {
  if (!timestamp) {
    return null;
  }

  // Determine if timestamp is in seconds or milliseconds
  // Timestamps in seconds are typically < 1e12 (year 2001)
  // Timestamps in milliseconds are typically > 1e12
  const timestampMs = timestamp < 1e12 ? timestamp * 1000 : timestamp;

  try {
    return new Date(timestampMs).toISOString();
  } catch (error) {
    console.warn(
      "[ChatExportService] Error formatting timestamp:",
      timestamp,
      error,
    );
    return null;
  }
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
): Promise<any[]> {
  const embedsForExport: any[] = [];

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
          embed_id: embed.embed_id,
          type: embed.type,
          status: "error",
          content: null,
          error: "Embed content field is missing or invalid",
        });
        continue;
      }

      // Decode TOON content to get actual embed values
      const decodedContent = await decodeToonContent(embed.content);

      // Create export object with embed metadata and decoded content
      const embedExport: any = {
        embed_id: embed.embed_id,
        type: embed.type,
        status: embed.status,
        content: decodedContent, // Decoded content (actual values, not TOON)
        createdAt: formatTimestamp(embed.createdAt),
        updatedAt: formatTimestamp(embed.updatedAt),
      };

      // Add optional fields if present
      if (embed.text_preview) {
        embedExport.text_preview = embed.text_preview;
      }

      // Handle nested embeds (composite embeds like app_skill_use)
      const childEmbedIds: string[] = [];

      // Check for embed_ids in the decoded content (for composite embeds)
      if (decodedContent && typeof decodedContent === "object") {
        // Check if decoded content has embed_ids (could be array or pipe-separated string)
        if (Array.isArray(decodedContent.embed_ids)) {
          childEmbedIds.push(...decodedContent.embed_ids);
        } else if (typeof decodedContent.embed_ids === "string") {
          // Handle pipe-separated string format
          childEmbedIds.push(
            ...decodedContent.embed_ids.split("|").filter((id) => id.trim()),
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
        embed_id: embed.embed_id,
        type: embed.type,
        status: "error",
        content: null,
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
async function getAllEmbedsForChat(messages: Message[]): Promise<any[]> {
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
 */
export async function convertChatToYaml(
  chat: Chat,
  messages: Message[],
  includeLink: boolean = false,
): Promise<string> {
  const yamlData: any = {
    chat: {
      title: null,
      exported_at: new Date().toISOString(),
      message_count: messages.length,
      draft: null,
      summary: null,
    },
    messages: [],
    embeds: [], // Separate field for embeds with decoded content
  };

  // Add chat link at the top if requested (for clipboard copy)
  if (includeLink) {
    yamlData.chat.link = generateChatLink(chat.chat_id);
    console.debug(
      "[ChatExportService] Including chat link in YAML:",
      yamlData.chat.link,
    );
  }

  // Try to get decrypted title and summary from cache
  const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
  if (metadata?.title) {
    yamlData.chat.title = metadata.title;
    console.debug("[ChatExportService] Using decrypted title:", metadata.title);
  } else if (chat.title) {
    // Fallback for demo chats which use plaintext title
    yamlData.chat.title = chat.title;
    console.debug(
      "[ChatExportService] Using plaintext title (demo chat):",
      chat.title,
    );
  } else {
    console.warn("[ChatExportService] Could not decrypt title for YAML export");
  }

  if (metadata?.summary) {
    yamlData.chat.summary = metadata.summary;
    console.debug(
      "[ChatExportService] Using decrypted summary:",
      metadata.summary.substring(0, 50),
    );
  } else if ((chat as any).summary) {
    // Fallback for demo chats which use plaintext summary
    yamlData.chat.summary = (chat as any).summary;
    console.debug(
      "[ChatExportService] Using plaintext summary (demo chat):",
      (chat as any).summary.substring(0, 50),
    );
  }

  // Add draft if present
  // CRITICAL: Handle both encrypted drafts (authenticated users) and cleartext drafts (non-authenticated sessionStorage)
  if (chat.encrypted_draft_md) {
    try {
      // Check if this is a cleartext draft from sessionStorage (non-authenticated users)
      // Cleartext drafts don't start with encryption markers and are shorter
      // For sessionStorage drafts, encrypted_draft_md actually contains cleartext markdown
      const isCleartextDraft =
        !chat.encrypted_draft_md.includes("encrypted:") &&
        !chat.encrypted_draft_md.startsWith("v1:") &&
        chat.encrypted_draft_md.length < 1000; // Rough heuristic

      if (isCleartextDraft) {
        // This is a cleartext draft from sessionStorage - use it directly
        yamlData.chat.draft = chat.encrypted_draft_md;
        console.debug(
          "[ChatExportService] Included cleartext draft from sessionStorage in export",
        );
      } else {
        // This is an encrypted draft - decrypt it
        const { decryptWithMasterKey } = await import("./cryptoService");
        const decryptedDraft = await decryptWithMasterKey(
          chat.encrypted_draft_md,
        );
        if (decryptedDraft) {
          yamlData.chat.draft = decryptedDraft;
          console.debug(
            "[ChatExportService] Successfully included encrypted draft in export",
          );
        } else {
          console.warn(
            "[ChatExportService] Could not decrypt draft for YAML export",
          );
        }
      }
    } catch (error) {
      console.error("[ChatExportService] Error processing draft:", error);
    }
  }

  // Get all embeds for the chat (with decoded content)
  // This runs in parallel with message processing for better performance
  const embedsPromise = getAllEmbedsForChat(messages);

  // Add messages (embed placeholders remain unchanged in message content)
  for (const message of messages) {
    const messageData = await convertMessageToYaml(message);
    yamlData.messages.push(messageData);
  }

  // Add embeds with decoded content (separate field)
  yamlData.embeds = await embedsPromise;

  return convertToYamlString(yamlData);
}

/**
 * Safely converts a timestamp to ISO string
 * Handles undefined, null, NaN, and both seconds and milliseconds timestamps
 * @param timestamp - The timestamp to convert (may be seconds or milliseconds)
 * @returns ISO string or null if timestamp is invalid
 */
function safeTimestampToISO(
  timestamp: number | undefined | null,
): string | null {
  if (timestamp === undefined || timestamp === null || isNaN(timestamp)) {
    return null;
  }
  // Timestamps in seconds are typically < 1e12 (before year ~2001 in ms)
  const timestampMs = timestamp < 1e12 ? timestamp * 1000 : timestamp;
  try {
    return new Date(timestampMs).toISOString();
  } catch {
    return null;
  }
}

/**
 * Converts a single message to YAML format
 *
 * Includes thinking content for thinking models (Gemini, Anthropic Claude, etc.)
 * when available. Thinking content is decrypted from encrypted_thinking_content
 * if needed and included as a separate field in the exported message.
 */
async function convertMessageToYaml(message: Message): Promise<any> {
  try {
    const messageData: any = {
      role: message.role,
      completed_at:
        safeTimestampToISO(message.created_at) ?? new Date().toISOString(), // Fallback to now if timestamp is invalid
    };

    // Add assistant category if available
    if (message.role === "assistant") {
      const category = message.category || (message as any).assistant_category;
      if (category) {
        messageData.assistant_category = category;
      }
    }

    // Process message content
    if (typeof message.content === "string") {
      // Simple text content
      messageData.content = message.content;
    } else if (message.content && typeof message.content === "object") {
      // TipTap JSON content - convert to markdown for YAML
      const markdown = await convertTiptapToMarkdown(message.content);
      messageData.content = markdown;
    } else {
      messageData.content = "";
    }

    // Include thinking content for thinking models (Gemini, Anthropic Claude, etc.)
    // Thinking content is the model's internal reasoning process
    if (message.role === "assistant") {
      // Try decrypted thinking_content first (if already decrypted)
      if (message.thinking_content) {
        messageData.thinking = message.thinking_content;
        console.debug(
          "[ChatExportService] Included decrypted thinking content in export",
        );
      }
      // Fall back to encrypted_thinking_content and decrypt it
      else if (message.encrypted_thinking_content) {
        try {
          // Get chat key for this message's chat to decrypt thinking content
          const chatKey = chatDB.getChatKey(message.chat_id);
          if (chatKey) {
            const { decryptWithChatKey } = await import("./cryptoService");
            const decryptedThinking = await decryptWithChatKey(
              message.encrypted_thinking_content,
              chatKey,
            );
            if (decryptedThinking) {
              messageData.thinking = decryptedThinking;
              console.debug(
                "[ChatExportService] Decrypted and included thinking content in export",
              );
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
      // Also include thinking metadata if available
      if (message.has_thinking) {
        messageData.has_thinking = true;
      }
      if (message.thinking_token_count) {
        messageData.thinking_tokens = message.thinking_token_count;
      }
    }

    return messageData;
  } catch (error) {
    console.error("[ChatExportService] Error processing message:", error);
    return {
      role: message.role,
      completed_at:
        safeTimestampToISO(message.created_at) ?? new Date().toISOString(),
      content: "[Error processing message]",
    };
  }
}

/**
 * Converts TipTap JSON content to markdown
 * This is a simplified version - you might want to use a more robust converter
 */
async function convertTiptapToMarkdown(content: any): Promise<string> {
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
 * Escapes a string for YAML double-quoted strings, handling special characters
 * @param str - String to escape
 * @returns Escaped string safe for YAML double quotes
 */
function escapeYamlString(str: string): string {
  // Escape backslashes first (must be first)
  str = str.replace(/\\/g, "\\\\");
  // Escape double quotes
  str = str.replace(/"/g, '\\"');
  // Escape newlines
  str = str.replace(/\n/g, "\\n");
  // Escape carriage returns
  str = str.replace(/\r/g, "\\r");
  // Escape tabs
  str = str.replace(/\t/g, "\\t");
  return str;
}

/**
 * Checks if a string needs to be quoted in YAML
 * For safety, we quote strings that contain any potentially problematic characters
 * @param str - String to check
 * @returns true if string needs quoting
 */
function needsQuoting(str: string): boolean {
  // Always quote empty strings
  if (str === "") {
    return true;
  }

  // Quote YAML keywords that could be confused with boolean/null
  if (
    str === "null" ||
    str === "true" ||
    str === "false" ||
    str === "yes" ||
    str === "no" ||
    str === "on" ||
    str === "off"
  ) {
    return true;
  }

  // Quote if contains special YAML characters that could cause parsing issues
  // This includes: : # @ ` | > & * ! ? % { [ ] } , ' " \
  const specialChars = /[:#@`|>&*!?%{}\[\]\\,"']/;
  if (specialChars.test(str)) {
    return true;
  }

  // Quote if starts with special characters that could be confused with YAML syntax
  if (/^[:\-+.#@`|>&*!?%{}\[\]\\]/.test(str)) {
    return true;
  }

  // Quote if looks like a number but might need to be a string (starts with digit or sign)
  // But only if it's actually a valid number representation
  if (/^[\d\-+.]/.test(str)) {
    // Check if it's a valid number
    const num = Number(str);
    if (!isNaN(num) && isFinite(num) && str.trim() === String(num)) {
      // It's a valid number, but we'll quote it anyway if it starts with + or has leading zeros
      if (str.startsWith("+") || /^0\d/.test(str)) {
        return true;
      }
      // For other numbers, don't quote (let YAML handle it)
      return false;
    }
  }

  // Quote if contains control characters (except newline which we handle separately)
  if (/[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]/.test(str)) {
    return true;
  }

  // Quote if contains HTML entities (like &#x27; or &amp;)
  if (/&#?\w+;/.test(str)) {
    return true;
  }

  // Quote if contains URLs (http:// or https://)
  if (/https?:\/\//.test(str)) {
    return true;
  }

  return false;
}

/**
 * Converts JavaScript object to YAML string
 */
function convertToYamlString(data: any): string {
  // Simple YAML conversion - in production you might want to use a proper YAML library
  const yamlLines: string[] = [];

  function convertValue(key: string, value: any, indent: number = 0): void {
    const spaces = "  ".repeat(indent);

    if (value === null || value === undefined) {
      yamlLines.push(`${spaces}${key}: null`);
    } else if (typeof value === "string") {
      // Handle multiline strings - use block scalar
      if (value.includes("\n")) {
        yamlLines.push(`${spaces}${key}: |`);
        const lines = value.split("\n");
        for (const line of lines) {
          // Escape special characters in each line for block scalars
          const escapedLine = line.replace(/\\/g, "\\\\").replace(/\$/g, "\\$");
          yamlLines.push(`${spaces}  ${escapedLine}`);
        }
      } else {
        // Single-line string - check if it needs quoting
        if (needsQuoting(value)) {
          const escaped = escapeYamlString(value);
          yamlLines.push(`${spaces}${key}: "${escaped}"`);
        } else {
          // Safe to use unquoted
          yamlLines.push(`${spaces}${key}: ${value}`);
        }
      }
    } else if (typeof value === "number" || typeof value === "boolean") {
      yamlLines.push(`${spaces}${key}: ${value}`);
    } else if (Array.isArray(value)) {
      yamlLines.push(`${spaces}${key}:`);
      for (const item of value) {
        if (typeof item === "object" && item !== null) {
          yamlLines.push(`${spaces}  -`);
          for (const [itemKey, itemValue] of Object.entries(item)) {
            convertValue(itemKey, itemValue, indent + 2);
          }
        } else if (typeof item === "string") {
          // Handle string items in arrays
          if (needsQuoting(item)) {
            const escaped = escapeYamlString(item);
            yamlLines.push(`${spaces}  - "${escaped}"`);
          } else {
            yamlLines.push(`${spaces}  - ${item}`);
          }
        } else {
          yamlLines.push(`${spaces}  - ${item}`);
        }
      }
    } else if (typeof value === "object") {
      yamlLines.push(`${spaces}${key}:`);
      for (const [objKey, objValue] of Object.entries(value)) {
        convertValue(objKey, objValue, indent + 1);
      }
    }
  }

  for (const [key, value] of Object.entries(data)) {
    convertValue(key, value);
  }

  return yamlLines.join("\n");
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
 * Copies chat to clipboard as YAML with embedded link wrapped in a markdown code block
 * When pasted inside OpenMates, only the link is used
 * When pasted outside, the full YAML is available in a formatted code block
 * @param chat - The chat to copy
 * @param messages - Array of messages in the chat
 */
export async function copyChatToClipboard(
  chat: Chat,
  messages: Message[],
): Promise<void> {
  try {
    console.debug("[ChatExportService] Copying chat to clipboard:", {
      chatId: chat.chat_id,
      messageCount: messages.length,
    });

    // Generate YAML with embedded link
    const yamlContent = await convertChatToYaml(chat, messages, true);

    // Wrap YAML content in a markdown code block for better formatting when pasted
    const codeBlock = `\`\`\`yaml\n${yamlContent}\n\`\`\``;

    // Try modern clipboard API first (works on most browsers)
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(codeBlock);
        console.debug(
          "[ChatExportService] Chat copied to clipboard successfully using modern API",
        );
        return;
      } catch (clipboardError) {
        console.warn(
          "[ChatExportService] Modern clipboard API failed, trying fallback:",
          clipboardError,
        );
      }
    }

    // Fallback for iOS Safari and older browsers
    await fallbackCopyToClipboard(codeBlock);

    console.debug(
      "[ChatExportService] Chat copied to clipboard successfully using fallback method",
    );
  } catch (error) {
    console.error("[ChatExportService] Error copying to clipboard:", error);
    throw new Error("Failed to copy to clipboard");
  }
}

/**
 * Fallback clipboard method for iOS Safari and older browsers
 * Uses the deprecated but more compatible execCommand approach
 * @param text - Text to copy to clipboard
 */
async function fallbackCopyToClipboard(text: string): Promise<void> {
  return new Promise((resolve, reject) => {
    // Create a temporary textarea element
    const textArea = document.createElement("textarea");
    textArea.value = text;

    // Make it invisible but still focusable
    textArea.style.position = "fixed";
    textArea.style.left = "-999999px";
    textArea.style.top = "-999999px";
    textArea.style.opacity = "0";
    textArea.style.pointerEvents = "none";
    textArea.setAttribute("readonly", "");

    // Add to DOM, select, and copy
    document.body.appendChild(textArea);

    try {
      // For iOS Safari, we need to focus and select the text
      textArea.focus();
      textArea.select();
      textArea.setSelectionRange(0, text.length);

      // Execute copy command
      const successful = document.execCommand("copy");

      if (successful) {
        console.debug("[ChatExportService] Fallback copy successful");
        resolve();
      } else {
        throw new Error("execCommand copy failed");
      }
    } catch (error) {
      console.error("[ChatExportService] Fallback copy failed:", error);
      reject(error);
    } finally {
      // Clean up
      document.body.removeChild(textArea);
    }
  });
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
