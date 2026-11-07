/**
 * Zip Export Service
 * Handles creating enhanced zip exports for chats with:
 * - YAML format of the chat
 * - Markdown format of the chat history
 * - Separate code files for each code embed (with original file paths)
 * - Separate transcript files for each video transcript embed
 * - AI-generated images (fetched from S3, decrypted, with PNG metadata)
 */

import JSZip from "jszip";
import type { Chat, Message } from "../types/chat";
import {
  convertChatToYaml,
  generateChatFilename,
  hydrateChatForExport,
  type PIIExportOptions,
} from "./chatExportService";
import {
  extractEmbedReferences,
  loadEmbeds,
  decodeToonContent,
} from "./embedResolver";
import { tipTapToCanonicalMarkdown, tipTapToReadableMarkdown } from "../message_parsing/serializers";
import { parseCodeEmbedContent } from "../components/embeds/code/codeEmbedContent";
import { restorePIIInText } from "../components/enter_message/services/piiDetectionService";
import { fetchAndDecryptImage } from "../components/embeds/images/imageEmbedCrypto";
import { hasMediaEncryptionMetadata } from "./encryption/mediaEncryption";
import {
  generateImageFilename,
  embedPngMetadata,
} from "../components/embeds/images/imageDownloadUtils";
import {
  getStaticGeneratedAudioDownload,
  type StaticGeneratedAudioDownload,
} from "./generatedAudioExport";
import {
  getEmbedFileReferences,
  extractEmbedIdsFromContent,
  type ChatFileReference,
} from "../demo_chats/exampleChatFiles";

import type * as RustChatZip from "./rustCore/transfer/rustChatZip";

/** Opt-in shared Rust core build: zip planning runs in the shared Worker `transfer` unit. */
const RUST_TRANSFER_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === "1";
/** Measurement-only opt-out (like chatExportService): `'ts'` keeps this TypeScript exporter. */
const RUST_TRANSFER_OPT_OUT_KEY = "openmates_rust_core_transfer";
let rustZipModule: Promise<typeof RustChatZip> | null = null;
function rustChatZip(): Promise<typeof RustChatZip> | null {
  if (!RUST_TRANSFER_BUILD) return null;
  if (typeof localStorage === "undefined" || localStorage.getItem(RUST_TRANSFER_OPT_OUT_KEY) === "ts") return null;
  rustZipModule ??= import("./rustCore/transfer/rustChatZip");
  return rustZipModule;
}

/** The part of JSZip (or one of its folders) the exporters write to. */
export interface ZipTarget {
  file(path: string, data: string | Blob): unknown;
}

/** Everything the page resolved for the non-text files of one chat zip. */
export interface ChatZipFiles {
  code: Awaited<ReturnType<typeof getCodeEmbedsForChat>>;
  transcripts: Awaited<ReturnType<typeof getVideoTranscriptEmbedsForChat>>;
  images: Awaited<ReturnType<typeof getImageEmbedsForChat>>;
  generatedAudio: Awaited<ReturnType<typeof getStaticGeneratedAudioFilesForChat>>;
  staticFiles: Awaited<ReturnType<typeof getStaticExampleFilesForChat>>;
  audio: Awaited<ReturnType<typeof getAudioRecordingsForChat>>;
  pdfs: Awaited<ReturnType<typeof getPDFEmbedsForChat>>;
}

type DecodedEmbedContent = Record<string, unknown>;
type ImageFileEntry = {
  s3_key?: string;
  format?: string;
  aes_nonce?: string;
  encryption?: string;
};

function isRecord(value: unknown): value is DecodedEmbedContent {
  return !!value && typeof value === "object";
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function collectEmbedIdsFromMessages(messages: Message[]): string[] {
  const embedRefs = new Map<string, { type: string; embed_id: string; version?: number }>();
  for (const message of messages) {
    let markdownContent = "";
    if (typeof message.content === "string") {
      markdownContent = message.content;
    } else if (message.content && typeof message.content === "object") {
      markdownContent = tipTapToCanonicalMarkdown(message.content);
    }

    for (const ref of extractEmbedReferences(markdownContent)) {
      if (!embedRefs.has(ref.embed_id)) {
        embedRefs.set(ref.embed_id, ref);
      }
    }
  }
  return Array.from(embedRefs.keys());
}

function uniqueFilename(filename: string, usedFilenames: Set<string>): string {
  let nextFilename = filename.replace(/[/\\]/g, "_");
  if (!usedFilenames.has(nextFilename.toLowerCase())) {
    usedFilenames.add(nextFilename.toLowerCase());
    return nextFilename;
  }

  const dotIndex = nextFilename.lastIndexOf(".");
  const base = dotIndex > 0 ? nextFilename.slice(0, dotIndex) : nextFilename;
  const extension = dotIndex > 0 ? nextFilename.slice(dotIndex) : "";
  let counter = 2;
  while (usedFilenames.has(`${base}_${counter}${extension}`.toLowerCase())) {
    counter++;
  }
  nextFilename = `${base}_${counter}${extension}`;
  usedFilenames.add(nextFilename.toLowerCase());
  return nextFilename;
}

/**
 * Converts a single message to markdown format
 * @param message - The message to convert
 * @param piiOptions - Optional PII export options to control sensitive data handling
 */
async function convertMessageToMarkdown(
  message: Message,
  piiOptions?: PIIExportOptions,
): Promise<string> {
  try {
    // Handle both seconds (regular chats) and milliseconds (demo chats) timestamps
    const timestampMs =
      message.created_at < 1e12
        ? message.created_at * 1000
        : message.created_at;
    const timestamp = new Date(timestampMs).toISOString();
    const role = message.role === "assistant" ? "Assistant" : "You";

    let content = "";
    if (typeof message.content === "string") {
      // Raw markdown string — resolve embed blocks to readable text
      content = await tipTapToReadableMarkdown(message.content);
    } else if (message.content && typeof message.content === "object") {
      // TipTap doc — serialize to canonical markdown first, then resolve embeds
      content = await tipTapToReadableMarkdown(message.content);
    }

    // Apply PII handling: message content from DB has PLACEHOLDERS.
    // When PII is revealed (piiHidden=false), restore originals for export.
    // When hidden, content keeps placeholders as-is.
    if (
      piiOptions &&
      !piiOptions.piiHidden &&
      piiOptions.piiMappings.length > 0
    ) {
      content = restorePIIInText(content, piiOptions.piiMappings);
    }

    return `## ${role} - ${timestamp}\n\n${content}\n\n`;
  } catch (error) {
    console.error(
      "[ZipExportService] Error converting message to markdown:",
      error,
    );
    return "";
  }
}

/**
 * Converts chat messages to markdown format
 * @param chat - The chat to convert
 * @param messages - Array of messages
 * @param piiOptions - Optional PII export options to control sensitive data handling
 */
export async function convertChatToMarkdown(
  chat: Chat,
  messages: Message[],
  piiOptions?: PIIExportOptions,
): Promise<string> {
  try {
    let markdown = "";

    // Add title header
    if (chat.title) {
      markdown += `# ${chat.title}\n\n`;
    }

    // Add metadata
    // Handle both seconds (regular chats) and milliseconds (demo chats) timestamps
    const timestampMs =
      chat.created_at < 1e12 ? chat.created_at * 1000 : chat.created_at;
    const createdDate = new Date(timestampMs).toISOString();
    markdown += `*Created: ${createdDate}*\n\n`;
    markdown += "---\n\n";

    // Add all messages, respecting PII visibility
    for (const message of messages) {
      const messageMarkdown = await convertMessageToMarkdown(
        message,
        piiOptions,
      );
      markdown += messageMarkdown;
    }

    return markdown;
  } catch (error) {
    console.error(
      "[ZipExportService] Error converting chat to markdown:",
      error,
    );
    return "";
  }
}

/**
 * Recursively loads all embeds and finds code embeds including nested ones
 * @param embedIds - Array of embed IDs to load
 * @param loadedEmbedIds - Set of already loaded embed IDs to avoid duplicates
 * @returns Array of code embed data
 */
async function loadCodeEmbedsRecursively(
  embedIds: string[],
  loadedEmbedIds: Set<string> = new Set(),
): Promise<
  Array<{
    embed_id: string;
    language: string;
    filename?: string;
    content: string;
    file_path?: string;
  }>
> {
  const codeEmbeds: Array<{
    embed_id: string;
    language: string;
    filename?: string;
    content: string;
    file_path?: string;
  }> = [];

  // Filter out already loaded embeds
  const newEmbedIds = embedIds.filter((id) => !loadedEmbedIds.has(id));
  if (newEmbedIds.length === 0) {
    return codeEmbeds;
  }

  // Mark these as being loaded
  newEmbedIds.forEach((id) => loadedEmbedIds.add(id));

  // Load embeds from EmbedStore
  const loadedEmbeds = await loadEmbeds(newEmbedIds);

  // Process each embed
  for (const embed of loadedEmbeds) {
    try {
      if (!embed.content || typeof embed.content !== "string") {
        continue;
      }

      // Decode TOON content to get actual embed values
      const decodedContent = await decodeToonContent(embed.content);

      // If this is a code embed, process it
      if (
        (embed.type === "code" || embed.type === "code-code") &&
        decodedContent &&
        typeof decodedContent === "object"
      ) {
        const decodedRecord = decodedContent as DecodedEmbedContent;
        const rawCodeContent =
          stringValue(decodedRecord.code) || stringValue(decodedRecord.content) || "";
        const hintLanguage =
          stringValue(decodedRecord.language) || stringValue(decodedRecord.lang) || "text";
        const hintFilename = stringValue(decodedRecord.filename);

        // Parse code content to extract filename from header (e.g., "dockerfile:app/Dockerfile")
        // This also strips the header line from the code content
        const parsed = parseCodeEmbedContent(rawCodeContent, {
          language: hintLanguage,
          filename: hintFilename,
        });
        const codeContent = parsed.code;
        const language = parsed.language || hintLanguage;
        // Get filename from parsed header if not already provided
        const filename = hintFilename || parsed.filename || undefined;

        // Get file_path from embed-level field (stored in EmbedStore) OR TOON content OR parsed filename
        // Priority: embed.file_path > decodedContent.file_path > parsed.filename (if it contains path separator)
        // The filename can be a full path when specified as `language:path/to/file.ext` in markdown
        let filePath = stringValue(embed.file_path) || stringValue(decodedRecord.file_path);

        // If no explicit file_path but filename contains path separators, use filename as path
        const filenameForPath = filename || parsed.filename;
        if (
          !filePath &&
          filenameForPath &&
          (filenameForPath.includes("/") || filenameForPath.includes("\\"))
        ) {
          filePath = filenameForPath;
        }

        if (codeContent) {
          codeEmbeds.push({
            embed_id: embed.embed_id,
            language,
            filename,
            content: codeContent,
            file_path: filePath,
          });
        }
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
        console.warn(
          "[ZipExportService] Loading nested embeds for code processing:",
          {
            parentEmbedId: embed.embed_id,
            childCount: uniqueChildEmbedIds.length,
            childIds: uniqueChildEmbedIds,
          },
        );

        const childCodeEmbeds = await loadCodeEmbedsRecursively(
          uniqueChildEmbedIds,
          loadedEmbedIds,
        );
        codeEmbeds.push(...childCodeEmbeds);
      }
    } catch (error) {
      console.warn(
        "[ZipExportService] Error processing embed for code extraction:",
        embed.embed_id,
        error,
      );
    }
  }

  return codeEmbeds;
}

/**
 * Gets all code embeds from a chat including nested embeds
 */
export async function getCodeEmbedsForChat(messages: Message[]): Promise<
  Array<{
    embed_id: string;
    language: string;
    filename?: string;
    content: string;
    file_path?: string;
  }>
> {
  try {
    // Extract all embed references from messages
    const embedRefs = new Map<
      string,
      { type: string; embed_id: string; version?: number }
    >();

    for (const message of messages) {
      let markdownContent = "";
      if (typeof message.content === "string") {
        markdownContent = message.content;
      } else if (message.content && typeof message.content === "object") {
        markdownContent = tipTapToCanonicalMarkdown(message.content);
      }

      const refs = extractEmbedReferences(markdownContent);
      for (const ref of refs) {
        // Include all embed types, not just code, since nested embeds might contain code
        if (!embedRefs.has(ref.embed_id)) {
          embedRefs.set(ref.embed_id, ref);
        }
      }
    }

    if (embedRefs.size === 0) {
      return [];
    }

    // Load embeds recursively to catch nested code embeds
    const embedIds = Array.from(embedRefs.keys());
    return await loadCodeEmbedsRecursively(embedIds);
  } catch (error) {
    console.error("[ZipExportService] Error getting code embeds:", error);
    return [];
  }
}

/**
 * Recursively loads all embeds and finds video transcript embeds including nested ones
 * @param embedIds - Array of embed IDs to load
 * @param loadedEmbedIds - Set of already loaded embed IDs to avoid duplicates
 * @returns Array of video transcript embed data
 */
async function loadVideoTranscriptEmbedsRecursively(
  embedIds: string[],
  loadedEmbedIds: Set<string> = new Set(),
): Promise<
  Array<{
    embed_id: string;
    filename: string;
    content: string;
  }>
> {
  const transcriptEmbeds: Array<{
    embed_id: string;
    filename: string;
    content: string;
  }> = [];

  // Filter out already loaded embeds
  const newEmbedIds = embedIds.filter((id) => !loadedEmbedIds.has(id));
  if (newEmbedIds.length === 0) {
    return transcriptEmbeds;
  }

  // Mark these as being loaded
  newEmbedIds.forEach((id) => loadedEmbedIds.add(id));

  // Load embeds from EmbedStore
  const loadedEmbeds = await loadEmbeds(newEmbedIds);

  // Process each embed
  for (const embed of loadedEmbeds) {
    try {
      if (!embed.content || typeof embed.content !== "string") {
        continue;
      }

      // Decode TOON content to get actual embed values
      const decodedContent = await decodeToonContent(embed.content);

      // If this is a video transcript embed, process it
      if (
        embed.type === "app_skill_use" &&
        decodedContent &&
        typeof decodedContent === "object" &&
        decodedContent.app_id === "videos" &&
        (decodedContent.skill_id === "get_transcript" ||
          decodedContent.skill_id === "get-transcript")
      ) {
        // Extract results array from decoded content
        const results = decodedContent.results || decodedContent.data || [];

        if (Array.isArray(results) && results.length > 0) {
          // Format transcript as markdown
          const transcriptText = results
            .filter((r: Record<string, unknown>) => {
              return (
                r.transcript || r.formatted_transcript || r.text || r.content
              );
            })
            .map((r: Record<string, unknown>) => {
              let content = "";

              const metadata = r.metadata as
                | Record<string, unknown>
                | undefined;
              if (metadata?.title) {
                content += `# ${metadata.title}\n\n`;
              }

              if (r.url) {
                content += `Source: ${r.url}\n\n`;
              }

              if (typeof r.word_count === "number") {
                content += `Word count: ${r.word_count.toLocaleString()}\n\n`;
              }

              const transcript = String(
                r.transcript ??
                  r.formatted_transcript ??
                  r.text ??
                  r.content ??
                  "",
              );
              content += transcript;

              return content;
            })
            .join("\n\n---\n\n");

          if (transcriptText) {
            // Generate filename from first result's title or URL
            let filename = "transcript.md";
            const firstResult = results[0];
            if (firstResult?.metadata?.title) {
              filename = `${firstResult.metadata.title.replace(/[^a-z0-9]/gi, "_").toLowerCase()}_transcript.md`;
            } else if (firstResult?.url) {
              try {
                const urlObj = new URL(firstResult.url);
                const videoId =
                  urlObj.searchParams.get("v") ||
                  urlObj.pathname.split("/").pop() ||
                  "video";
                filename = `${videoId}_transcript.md`;
              } catch {
                filename = `${embed.embed_id}_transcript.md`;
              }
            } else {
              filename = `${embed.embed_id}_transcript.md`;
            }

            transcriptEmbeds.push({
              embed_id: embed.embed_id,
              filename,
              content: transcriptText,
            });
          }
        }
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
        console.warn(
          "[ZipExportService] Loading nested embeds for transcript processing:",
          {
            parentEmbedId: embed.embed_id,
            childCount: uniqueChildEmbedIds.length,
            childIds: uniqueChildEmbedIds,
          },
        );

        const childTranscriptEmbeds =
          await loadVideoTranscriptEmbedsRecursively(
            uniqueChildEmbedIds,
            loadedEmbedIds,
          );
        transcriptEmbeds.push(...childTranscriptEmbeds);
      }
    } catch (error) {
      console.warn(
        "[ZipExportService] Error processing embed for transcript extraction:",
        embed.embed_id,
        error,
      );
    }
  }

  return transcriptEmbeds;
}

/**
 * Gets all video transcript embeds from a chat including nested embeds
 * Extracts video transcript embeds (app_skill_use with app_id='videos' and skill_id='get_transcript')
 * and formats them as markdown files similar to VideoTranscriptEmbedFullscreen handleDownload
 */
export async function getVideoTranscriptEmbedsForChat(messages: Message[]): Promise<
  Array<{
    embed_id: string;
    filename: string;
    content: string;
  }>
> {
  try {
    // Extract all embed references from messages
    const embedRefs = new Map<
      string,
      { type: string; embed_id: string; version?: number }
    >();

    for (const message of messages) {
      let markdownContent = "";
      if (typeof message.content === "string") {
        markdownContent = message.content;
      } else if (message.content && typeof message.content === "object") {
        markdownContent = tipTapToCanonicalMarkdown(message.content);
      }

      const refs = extractEmbedReferences(markdownContent);
      for (const ref of refs) {
        // Include all embed types, not just app_skill_use, since nested embeds might contain transcripts
        if (!embedRefs.has(ref.embed_id)) {
          embedRefs.set(ref.embed_id, ref);
        }
      }
    }

    if (embedRefs.size === 0) {
      return [];
    }

    // Load embeds recursively to catch nested transcript embeds
    const embedIds = Array.from(embedRefs.keys());
    return await loadVideoTranscriptEmbedsRecursively(embedIds);
  } catch (error) {
    console.error(
      "[ZipExportService] Error getting video transcript embeds:",
      error,
    );
    return [];
  }
}

/**
 * Recursively loads all embeds and finds image embeds including nested ones
 * (e.g. images inside app_skill_use composite embeds)
 * @param embedIds - Array of embed IDs to load
 * @param loadedEmbedIds - Set of already loaded embed IDs to avoid duplicates
 * @returns Array of image embed data with decryption info
 */
async function loadImageEmbedsRecursively(
  embedIds: string[],
  loadedEmbedIds: Set<string> = new Set(),
): Promise<
  Array<{
    embed_id: string;
    /** Original filename for user-uploaded images (e.g. "photo.jpg") */
    filename?: string;
    /** Text prompt — only set for AI-generated images */
    prompt?: string;
    model?: string;
    generated_at?: string;
    /** Whether this is a user upload (true) or AI-generated (false/undefined) */
    is_upload?: boolean;
    data_url?: string;
    s3_base_url?: string;
    s3_key: string;
    aes_key: string;
    aes_nonce: string;
    variant: ImageFileEntry;
    format: string;
  }>
> {
  const imageEmbeds: Array<{
    embed_id: string;
    filename?: string;
    prompt?: string;
    model?: string;
    generated_at?: string;
    is_upload?: boolean;
    data_url?: string;
    s3_base_url?: string;
    s3_key: string;
    aes_key: string;
    aes_nonce: string;
    variant: ImageFileEntry;
    format: string;
  }> = [];

  // Filter out already loaded embeds
  const newEmbedIds = embedIds.filter((id) => !loadedEmbedIds.has(id));
  if (newEmbedIds.length === 0) {
    return imageEmbeds;
  }

  // Mark these as being loaded
  newEmbedIds.forEach((id) => loadedEmbedIds.add(id));

  // Load embeds from EmbedStore
  const loadedEmbeds = await loadEmbeds(newEmbedIds);

  console.warn(
    "[ZipExportService] loadImageEmbedsRecursively: loaded embeds from store:",
    {
      requestedIds: newEmbedIds.length,
      loadedCount: loadedEmbeds.length,
      embedTypes: loadedEmbeds.map((e) => ({
        id: e.embed_id,
        type: e.type,
        hasContent: !!e.content,
        contentType: typeof e.content,
      })),
    },
  );

  // Process each embed
  for (const embed of loadedEmbeds) {
    try {
      if (!embed.content || typeof embed.content !== "string") {
        console.warn(
          "[ZipExportService] Skipping embed with no/invalid content:",
          {
            embed_id: embed.embed_id,
            type: embed.type,
            contentIsNull: embed.content === null,
            contentType: typeof embed.content,
          },
        );
        continue;
      }

      // Decode TOON content to get actual embed values
      const decodedContent = await decodeToonContent(embed.content);

      console.warn("[ZipExportService] Image embed check:", {
        embed_id: embed.embed_id,
        embed_type: embed.type,
        decoded_app_id: decodedContent?.app_id,
        decoded_skill_id: decodedContent?.skill_id,
        decoded_type: decodedContent?.type,
        has_s3_base_url: !!decodedContent?.s3_base_url,
        has_aes_key: !!decodedContent?.aes_key,
        has_aes_nonce: !!decodedContent?.aes_nonce,
        has_files: !!decodedContent?.files,
        files_keys: decodedContent?.files
          ? Object.keys(decodedContent.files)
          : [],
      });

      // If this is an image embed (AI-generated OR user-uploaded), process it.
      // AI-generated images: app_id="images", skill_id="generate"/"generate_draft"
      // User-uploaded images: app_id="images", skill_id="upload" (type "images-image")
      // Imported images (from ZIP/YAML fixtures) have data_url but no aes_key/aes_nonce.
      if (
        isRecord(decodedContent) &&
        decodedContent.app_id === "images" &&
        (decodedContent.skill_id === "generate" ||
          decodedContent.skill_id === "generate_draft" ||
          decodedContent.skill_id === "upload")
      ) {
        const files = isRecord(decodedContent.files)
          ? decodedContent.files
          : undefined;
        const fileEntry =
          (files?.original as ImageFileEntry | undefined) ||
          (files?.full as ImageFileEntry | undefined) ||
          (files?.preview as ImageFileEntry | undefined);

        console.warn("[ZipExportService] Found image embed, fileEntry:", {
          embed_id: embed.embed_id,
          hasOriginal: !!files?.original,
          hasFull: !!files?.full,
          hasPreview: !!files?.preview,
          selectedKey: fileEntry?.s3_key,
          hasDataUrl: !!decodedContent.data_url,
          hasFilename: !!decodedContent.filename,
          hasAesKey: !!decodedContent.aes_key,
        });

        // Imported images embed the raw data URL directly (no S3, no encryption)
        if (decodedContent.data_url && decodedContent.filename) {
          imageEmbeds.push({
            embed_id: embed.embed_id,
            filename: stringValue(decodedContent.filename),
            is_upload: true,
            data_url: stringValue(decodedContent.data_url),
            s3_key: "",
            aes_key: "",
            aes_nonce: "",
            variant: fileEntry || {},
            format: fileEntry?.format || "png",
          });
        } else if (
          decodedContent.aes_key &&
          fileEntry?.s3_key &&
          hasMediaEncryptionMetadata(fileEntry, stringValue(decodedContent.aes_nonce))
        ) {
          const isUpload = decodedContent.skill_id === "upload";
          imageEmbeds.push({
            embed_id: embed.embed_id,
            filename: isUpload
              ? (decodedContent.filename as string | undefined)
              : undefined,
            prompt: isUpload
              ? undefined
              : stringValue(decodedContent.prompt),
            model: stringValue(decodedContent.model),
            generated_at: stringValue(decodedContent.generated_at),
            is_upload: isUpload,
            s3_base_url: stringValue(decodedContent.s3_base_url),
            s3_key: fileEntry.s3_key,
            aes_key: stringValue(decodedContent.aes_key) || "",
            aes_nonce: stringValue(decodedContent.aes_nonce) || "",
            variant: fileEntry,
            format: fileEntry.format || "png",
          });
        }
      }

      // Handle nested embeds (composite embeds like app_skill_use)
      const childEmbedIds: string[] = [];

      // Check for embed_ids in the decoded content (for composite embeds)
      if (decodedContent && typeof decodedContent === "object") {
        if (Array.isArray(decodedContent.embed_ids)) {
          childEmbedIds.push(...decodedContent.embed_ids);
        } else if (typeof decodedContent.embed_ids === "string") {
          childEmbedIds.push(
            ...decodedContent.embed_ids
              .split("|")
              .filter((id: string) => id.trim()),
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
        console.warn(
          "[ZipExportService] Loading nested embeds for image processing:",
          {
            parentEmbedId: embed.embed_id,
            childCount: uniqueChildEmbedIds.length,
            childIds: uniqueChildEmbedIds,
          },
        );

        const childImageEmbeds = await loadImageEmbedsRecursively(
          uniqueChildEmbedIds,
          loadedEmbedIds,
        );
        imageEmbeds.push(...childImageEmbeds);
      }
    } catch (error) {
      console.warn(
        "[ZipExportService] Error processing embed for image extraction:",
        embed.embed_id,
        error,
      );
    }
  }

  return imageEmbeds;
}

/**
 * Convert a local data URL from an imported chat fixture into a Blob for export.
 */
function dataUrlToBlob(dataUrl: string): Blob {
  const match = dataUrl.match(/^data:([^;,]+)?(;base64)?,(.*)$/);
  if (!match) {
    throw new Error("Invalid image data URL in imported embed");
  }

  const mimeType = match[1] || "application/octet-stream";
  const isBase64 = Boolean(match[2]);
  const payload = match[3] || "";
  const binary = isBase64 ? atob(payload) : decodeURIComponent(payload);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index++) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new Blob([bytes], { type: mimeType });
}

/**
 * Gets all image embeds from a chat including nested embeds.
 * Downloads, decrypts, and embeds PNG metadata for each image.
 * @returns Array of image data ready to be added to zip
 */
export async function getImageEmbedsForChat(messages: Message[]): Promise<
  Array<{
    filename: string;
    blob: Blob;
  }>
> {
  try {
    // Extract all embed references from messages
    const embedRefs = new Map<
      string,
      { type: string; embed_id: string; version?: number }
    >();

    for (const message of messages) {
      let markdownContent = "";
      if (typeof message.content === "string") {
        markdownContent = message.content;
      } else if (message.content && typeof message.content === "object") {
        markdownContent = tipTapToCanonicalMarkdown(message.content);
      }

      const refs = extractEmbedReferences(markdownContent);
      for (const ref of refs) {
        // Include all embed types since nested embeds might contain images
        if (!embedRefs.has(ref.embed_id)) {
          embedRefs.set(ref.embed_id, ref);
        }
      }
    }

    console.warn(
      "[ZipExportService] getImageEmbedsForChat: extracted embed references:",
      {
        messageCount: messages.length,
        totalEmbedRefs: embedRefs.size,
        refs: Array.from(embedRefs.values()).map((r) => ({
          type: r.type,
          embed_id: r.embed_id,
        })),
      },
    );

    if (embedRefs.size === 0) {
      return [];
    }

    // Load image embed metadata recursively
    const embedIds = Array.from(embedRefs.keys());
    const imageEmbedInfos = await loadImageEmbedsRecursively(embedIds);

    if (imageEmbedInfos.length === 0) {
      return [];
    }

    console.warn(
      "[ZipExportService] Found image embeds to download:",
      imageEmbedInfos.length,
    );

    // Fetch, decrypt, and prepare each image for the zip
    const imageResults: Array<{ filename: string; blob: Blob }> = [];
    const usedFilenames = new Set<string>();

    for (const imageInfo of imageEmbedInfos) {
      try {
        // Imported image embeds can already contain decrypted local data URLs.
        // Regular uploaded/generated images still go through S3 + AES decryption.
        const blob = imageInfo.data_url
          ? dataUrlToBlob(imageInfo.data_url)
          : await fetchAndDecryptImage(
              imageInfo.s3_base_url,
              imageInfo.s3_key,
              imageInfo.aes_key,
              imageInfo.aes_nonce,
              imageInfo.variant,
            );

        // For PNG images, embed metadata (prompt, model, etc.)
        let downloadBlob: Blob = blob;
        if (imageInfo.format === "png") {
          try {
            const arrayBuffer = await blob.arrayBuffer();
            const metadataBytes = embedPngMetadata(arrayBuffer, {
              prompt: imageInfo.prompt,
              model: imageInfo.model,
              software: "OpenMates",
              generatedAt: imageInfo.generated_at,
            });
            const ab = new ArrayBuffer(metadataBytes.byteLength);
            new Uint8Array(ab).set(metadataBytes);
            downloadBlob = new Blob([ab], { type: "image/png" });
          } catch (metaError) {
            console.warn(
              "[ZipExportService] Failed to embed PNG metadata, using raw image:",
              metaError,
            );
          }
        }

        // Generate filename: use original filename for uploads, prompt-based for AI-generated
        let filename: string;
        if (imageInfo.is_upload && imageInfo.filename) {
          // User-uploaded image: keep the original filename as-is
          filename = imageInfo.filename;
        } else {
          // AI-generated image: derive name from the generation prompt
          filename = generateImageFilename(
            imageInfo.prompt,
            imageInfo.format || "png",
          );
        }

        // Ensure unique filenames within the images/ folder
        if (usedFilenames.has(filename.toLowerCase())) {
          const ext = filename.lastIndexOf(".");
          if (ext > 0) {
            const baseName = filename.slice(0, ext);
            const extStr = filename.slice(ext);
            let counter = 2;
            while (
              usedFilenames.has(`${baseName}_${counter}${extStr}`.toLowerCase())
            ) {
              counter++;
            }
            filename = `${baseName}_${counter}${extStr}`;
          }
        }
        usedFilenames.add(filename.toLowerCase());

        imageResults.push({ filename, blob: downloadBlob });
      } catch (error) {
        console.warn(
          "[ZipExportService] Failed to download/decrypt image embed:",
          imageInfo.embed_id,
          error,
        );
      }
    }

    return imageResults;
  } catch (error) {
    console.error("[ZipExportService] Error getting image embeds:", error);
    return [];
  }
}

async function fetchStaticGeneratedAudio(
  download: StaticGeneratedAudioDownload,
): Promise<Blob> {
  const response = await fetch(download.url);
  if (!response.ok) {
    throw new Error(`Failed to fetch static generated audio: ${response.status}`);
  }
  const blob = await response.blob();
  return blob.type ? blob : new Blob([await blob.arrayBuffer()], { type: download.mimeType });
}

export async function getStaticGeneratedAudioFilesForChat(messages: Message[]): Promise<
  Array<{
    filename: string;
    blob: Blob;
  }>
> {
  try {
    const embedIds = collectEmbedIdsFromMessages(messages);
    if (embedIds.length === 0) return [];

    const loadedEmbeds = await loadEmbeds(embedIds);
    const audioFiles: Array<{ filename: string; blob: Blob }> = [];
    const usedFilenames = new Set<string>();

    for (const embed of loadedEmbeds) {
      try {
        if (!embed.content || typeof embed.content !== "string") continue;
        const decoded = await decodeToonContent(embed.content);
        const download = getStaticGeneratedAudioDownload(
          isRecord(decoded) ? decoded : embed.content,
        );
        if (!download) continue;

        const filename = uniqueFilename(download.filename, usedFilenames);
        const blob = await fetchStaticGeneratedAudio(download);
        audioFiles.push({ filename, blob });
      } catch (error) {
        console.warn(
          "[ZipExportService] Failed to export static generated audio:",
          embed.embed_id,
          error,
        );
      }
    }

    return audioFiles;
  } catch (error) {
    console.error("[ZipExportService] Error collecting static generated audio:", error);
    return [];
  }
}

function isSameOriginStaticFileUrl(url: string | null): url is string {
  return Boolean(url && (url.startsWith("/store-examples/") || url.startsWith("/images/") || url.startsWith("data:")));
}

function isAudioGeneratedFixture(file: ChatFileReference): boolean {
  return file.type === "audio" && file.appId === "audio" && (file.skillId === "generate" || file.skillId === "speak");
}

async function fetchStaticExampleFile(file: ChatFileReference): Promise<Blob> {
  if (!isSameOriginStaticFileUrl(file.url)) {
    throw new Error("Static example file URL is not same-origin or data URL");
  }
  const response = await fetch(file.url);
  if (!response.ok) {
    throw new Error(`Failed to fetch static example file: ${response.status}`);
  }
  const blob = await response.blob();
  return blob.type || !file.mimeType
    ? blob
    : new Blob([await blob.arrayBuffer()], { type: file.mimeType });
}

export async function getStaticExampleFilesForChat(messages: Message[]): Promise<
  Array<{
    filename: string;
    blob: Blob;
  }>
> {
  try {
    const queue = collectEmbedIdsFromMessages(messages);
    if (queue.length === 0) return [];

    const files: Array<{ filename: string; blob: Blob }> = [];
    const usedFilenames = new Set<string>();
    const visitedEmbedIds = new Set<string>();

    while (queue.length > 0) {
      const nextEmbedIds = queue.splice(0).filter((embedId) => {
        if (!embedId || visitedEmbedIds.has(embedId)) return false;
        visitedEmbedIds.add(embedId);
        return true;
      });
      if (nextEmbedIds.length === 0) continue;

      const loadedEmbeds = await loadEmbeds(nextEmbedIds);
      for (const embed of loadedEmbeds) {
        try {
          if (!embed.content || typeof embed.content !== "string") continue;
          const decoded = await decodeToonContent(embed.content);
          const content = isRecord(decoded) ? decoded : embed.content;
          const childEmbedIds = [
            ...(Array.isArray(embed.embed_ids) ? embed.embed_ids : []),
            ...extractEmbedIdsFromContent(content),
          ];
          for (const childEmbedId of childEmbedIds) {
            if (childEmbedId && !visitedEmbedIds.has(childEmbedId)) queue.push(childEmbedId);
          }

          const rows = getEmbedFileReferences({
            embedId: embed.embed_id,
            type: embed.type,
            content,
          });
          for (const file of rows) {
            if (isAudioGeneratedFixture(file) || !isSameOriginStaticFileUrl(file.url)) continue;
            const filename = uniqueFilename(file.title, usedFilenames);
            files.push({ filename, blob: await fetchStaticExampleFile(file) });
          }
        } catch (error) {
          console.warn(
            "[ZipExportService] Failed to export static example file:",
            embed.embed_id,
            error,
          );
        }
      }
    }

    return files;
  } catch (error) {
    console.error("[ZipExportService] Error collecting static example files:", error);
    return [];
  }
}

/**
 * Fetches and AES-256-GCM decrypts a binary blob from the private S3 bucket.
 * Uses the shared presigned URL service (GET /v1/embeds/presigned-url) — same
 * mechanism used by imageEmbedCrypto and audioEmbedCrypto.
 *
 * @param s3Key      - S3 object key (e.g. "user_id/hash/timestamp_original.bin")
 * @param aesKeyB64  - Base64-encoded plaintext AES-256 key (32 bytes)
 * @param nonceB64   - Base64-encoded AES-GCM nonce (12 bytes)
 * @param mimeType   - MIME type for the resulting Blob
 * @returns Decrypted Blob
 */
async function fetchAndDecryptBlob(
  s3Key: string,
  aesKeyB64: string,
  nonceB64: string,
  mimeType: string,
): Promise<Blob> {
  const { fetchWithPresignedUrl } = await import("./presignedUrlService");

  // Fetch the encrypted ciphertext via a backend-generated presigned URL
  const encryptedData = await fetchWithPresignedUrl(s3Key);

  // Decode key and nonce from base64 (handles both standard and URL-safe variants)
  function b64ToBuffer(b64: string): ArrayBuffer {
    const normalized = b64.replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(normalized);
    const buf = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) buf[i] = binary.charCodeAt(i);
    return buf.buffer;
  }

  const keyBytes = b64ToBuffer(aesKeyB64);
  const NONCE_BYTES = 12;
  const nonceBytes = nonceB64
    ? b64ToBuffer(nonceB64)
    : encryptedData.slice(0, NONCE_BYTES);
  const ciphertext = nonceB64 ? encryptedData : encryptedData.slice(NONCE_BYTES);

  // Import and apply AES-256-GCM decryption
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "AES-GCM" },
    false,
    ["decrypt"],
  );
  const decrypted = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: nonceBytes },
    cryptoKey,
    ciphertext,
  );

  return new Blob([decrypted], { type: mimeType });
}

// ---------------------------------------------------------------------------
// Audio recording extractor
// ---------------------------------------------------------------------------

/**
 * Extracts all audio recording embeds from a chat's messages.
 * For each embed, returns:
 *  - The decrypted audio blob (fetched from the private S3 bucket)
 *  - The transcript text (if available)
 *
 * Audio TOON content shape (audio-recording type):
 *   { app_id: "audio", skill_id: "transcribe", files: { original: { s3_key, size_bytes } },
 *     aes_key, aes_nonce, title, transcript, filename, mime_type, duration }
 */
export async function getAudioRecordingsForChat(messages: Message[]): Promise<
  Array<{
    /** Sanitised filename for the zip (e.g. "recording_01.webm") */
    filename: string;
    blob: Blob;
    /** Transcript text (may be empty string) */
    transcript: string;
  }>
> {
  try {
    // Collect all embed references from messages
    const embedRefs = new Map<
      string,
      { type: string; embed_id: string; version?: number }
    >();
    for (const message of messages) {
      let md = "";
      if (typeof message.content === "string") {
        md = message.content;
      } else if (message.content && typeof message.content === "object") {
        md = tipTapToCanonicalMarkdown(message.content);
      }
      for (const ref of extractEmbedReferences(md)) {
        if (!embedRefs.has(ref.embed_id)) embedRefs.set(ref.embed_id, ref);
      }
    }

    if (embedRefs.size === 0) return [];

    // Load all embeds (audio-recording embeds are top-level, not nested)
    const loadedEmbeds = await loadEmbeds(Array.from(embedRefs.keys()));
    const results: Array<{ filename: string; blob: Blob; transcript: string }> =
      [];
    const usedFilenames = new Set<string>();

    for (const embed of loadedEmbeds) {
      try {
        // Only handle audio-recording type embeds
        if (embed.type !== "audio-recording") continue;
        if (!embed.content || typeof embed.content !== "string") continue;

        const decoded = await decodeToonContent(embed.content);
        if (
          !decoded ||
          typeof decoded !== "object" ||
          decoded.app_id !== "audio"
        ) {
          continue;
        }

        // Extract S3 key — prefer "original" variant, fall back to first available
        const files = decoded.files as
          | Record<string, { s3_key: string; size_bytes: number }>
          | null
          | undefined;
        if (!files) continue;

        const originalS3Key =
          files.original?.s3_key ?? Object.values(files)[0]?.s3_key;
        const aesKey = decoded.aes_key as string | undefined;
        const aesNonce = decoded.aes_nonce as string | undefined;

        if (!originalS3Key || !aesKey || aesNonce == null) {
          console.warn(
            "[ZipExportService] Audio embed missing S3/AES fields:",
            embed.embed_id,
          );
          continue;
        }

        // Determine MIME type and file extension from stored mime_type or filename
        const storedMime =
          (decoded.mime_type as string | undefined) ?? "audio/webm";
        const storedFilename = decoded.filename as string | undefined;
        const ext =
          storedFilename?.split(".").pop() ??
          (storedMime.includes("mp4") ? "mp4" : "webm");

        // Fetch + decrypt the audio file from the private S3 bucket
        const blob = await fetchAndDecryptBlob(
          originalS3Key,
          aesKey,
          aesNonce,
          storedMime,
        );

        // Build a unique filename: prefer the stored original filename, otherwise
        // fall back to a sequential "recording_N.<ext>" pattern
        let filename = storedFilename ?? `recording.${ext}`;

        // Strip path separators (safety)
        filename = filename.replace(/[/\\]/g, "_");

        if (usedFilenames.has(filename.toLowerCase())) {
          const dotIdx = filename.lastIndexOf(".");
          const base = dotIdx > 0 ? filename.slice(0, dotIdx) : filename;
          const extStr = dotIdx > 0 ? filename.slice(dotIdx) : "";
          let counter = 2;
          while (
            usedFilenames.has(`${base}_${counter}${extStr}`.toLowerCase())
          ) {
            counter++;
          }
          filename = `${base}_${counter}${extStr}`;
        }
        usedFilenames.add(filename.toLowerCase());

        const transcript = (decoded.transcript as string | undefined) ?? "";

        results.push({ filename, blob, transcript });
        console.warn(
          "[ZipExportService] Added audio recording to zip:",
          filename,
          "size:",
          blob.size,
        );
      } catch (err) {
        console.warn(
          "[ZipExportService] Failed to export audio recording:",
          embed.embed_id,
          err,
        );
      }
    }

    return results;
  } catch (err) {
    console.error("[ZipExportService] Error collecting audio recordings:", err);
    return [];
  }
}

// ---------------------------------------------------------------------------
// PDF embed extractor (page screenshots)
// ---------------------------------------------------------------------------

/**
 * Extracts all PDF embeds from a chat's messages.
 * PDFs are stored encrypted on S3 as page screenshots after server-side OCR.
 * The TOON content for finished PDF embeds contains:
 *   { type: "pdf", filename, page_count, screenshot_s3_keys: { "1": s3_key, ... },
 *     aes_key, aes_nonce, s3_base_url }
 *
 * We export each page as an individual PNG inside a per-document sub-folder:
 *   uploads/pdfs/<document-name>/page_01.png, page_02.png, ...
 *
 * The original encrypted PDF binary is NOT re-exported (the plaintext PDF
 * itself is never stored on the client — only the page screenshots are).
 */
export async function getPDFEmbedsForChat(messages: Message[]): Promise<
  Array<{
    /** Sub-folder name derived from the PDF filename (e.g. "report") */
    folderName: string;
    /** Original filename of the uploaded PDF */
    pdfFilename: string;
    pages: Array<{ filename: string; blob: Blob }>;
  }>
> {
  try {
    // Collect all embed references from messages
    const embedRefs = new Map<
      string,
      { type: string; embed_id: string; version?: number }
    >();
    for (const message of messages) {
      let md = "";
      if (typeof message.content === "string") {
        md = message.content;
      } else if (message.content && typeof message.content === "object") {
        md = tipTapToCanonicalMarkdown(message.content);
      }
      for (const ref of extractEmbedReferences(md)) {
        if (!embedRefs.has(ref.embed_id)) embedRefs.set(ref.embed_id, ref);
      }
    }

    if (embedRefs.size === 0) return [];

    const loadedEmbeds = await loadEmbeds(Array.from(embedRefs.keys()));
    const results: Array<{
      folderName: string;
      pdfFilename: string;
      pages: Array<{ filename: string; blob: Blob }>;
    }> = [];

    for (const embed of loadedEmbeds) {
      try {
        // PDF embeds are stored under the "app_skill_use" type in IndexedDB
        // (as sent by the backend process_task.py via send_embed_data).
        // The decoded TOON content has type="pdf".
        if (!embed.content || typeof embed.content !== "string") continue;

        const decoded = await decodeToonContent(embed.content);
        if (!decoded || typeof decoded !== "object" || decoded.type !== "pdf") {
          continue;
        }

        const screenshotKeys = decoded.screenshot_s3_keys as
          | Record<string, string>
          | null
          | undefined;
        const aesKey = decoded.aes_key as string | undefined;
        const aesNonce = decoded.aes_nonce as string | undefined;
        const pdfFilename =
          (decoded.filename as string | undefined) ?? "document.pdf";

        // No screenshots means the OCR hasn't finished yet — skip gracefully
        if (!screenshotKeys || Object.keys(screenshotKeys).length === 0) {
          console.warn(
            "[ZipExportService] PDF embed has no screenshot_s3_keys (OCR pending?), skipping:",
            embed.embed_id,
          );
          continue;
        }

        if (!aesKey || !aesNonce) {
          console.warn(
            "[ZipExportService] PDF embed missing AES fields:",
            embed.embed_id,
          );
          continue;
        }

        // Derive a safe folder name from the PDF filename
        const baseWithoutExt = pdfFilename
          .replace(/\.pdf$/i, "")
          .replace(/[/\\]/g, "_");
        const folderName =
          baseWithoutExt.replace(/[^a-zA-Z0-9_\-. ]/g, "_").trim() ||
          "document";

        // Sort page numbers numerically
        const pageNums = Object.keys(screenshotKeys)
          .map(Number)
          .sort((a, b) => a - b);

        const pages: Array<{ filename: string; blob: Blob }> = [];
        const totalPages = pageNums.length;
        const padWidth = String(totalPages).length;

        for (const pageNum of pageNums) {
          const s3Key = screenshotKeys[String(pageNum)];
          if (!s3Key) continue;

          try {
            // Screenshots are PNG images encrypted with AES-256-GCM
            const blob = await fetchAndDecryptBlob(
              s3Key,
              aesKey,
              aesNonce,
              "image/png",
            );
            const pageFilename = `page_${String(pageNum).padStart(padWidth, "0")}.png`;
            pages.push({ filename: pageFilename, blob });
          } catch (pageErr) {
            console.warn(
              `[ZipExportService] Failed to fetch PDF page ${pageNum} for embed ${embed.embed_id}:`,
              pageErr,
            );
          }
        }

        if (pages.length > 0) {
          results.push({ folderName, pdfFilename, pages });
          console.warn(
            "[ZipExportService] Added PDF to zip:",
            pdfFilename,
            `(${pages.length}/${totalPages} pages)`,
          );
        }
      } catch (err) {
        console.warn(
          "[ZipExportService] Failed to export PDF embed:",
          embed.embed_id,
          err,
        );
      }
    }

    return results;
  } catch (err) {
    console.error("[ZipExportService] Error collecting PDF embeds:", err);
    return [];
  }
}

/**
 * Determines the file extension for a code language
 */
function getFileExtensionForLanguage(language: string): string {
  const extensions: Record<string, string> = {
    javascript: "js",
    typescript: "ts",
    python: "py",
    java: "java",
    cpp: "cpp",
    c: "c",
    rust: "rs",
    go: "go",
    ruby: "rb",
    php: "php",
    swift: "swift",
    kotlin: "kt",
    yaml: "yml",
    xml: "xml",
    markdown: "md",
    bash: "sh",
    shell: "sh",
    sql: "sql",
    json: "json",
    css: "css",
    html: "html",
    dockerfile: "Dockerfile",
  };

  return extensions[language.toLowerCase()] || language.toLowerCase();
}

/** Loads every embed-backed file of a chat in the order the zip lists them. */
export async function collectChatZipFiles(messages: Message[]): Promise<ChatZipFiles> {
  const code = await getCodeEmbedsForChat(messages);
  const transcripts = await getVideoTranscriptEmbedsForChat(messages);
  const images = await getImageEmbedsForChat(messages);
  const generatedAudio = await getStaticGeneratedAudioFilesForChat(messages);
  const staticFiles = await getStaticExampleFilesForChat(messages);
  const audio = await getAudioRecordingsForChat(messages);
  const pdfs = await getPDFEmbedsForChat(messages);
  return { code, transcripts, images, generatedAudio, staticFiles, audio, pdfs };
}

/** TypeScript zip layout of the embed-backed files (flag-off path). */
export function addChatZipFilesTs(zip: ZipTarget, files: ChatZipFiles): void {
  // Code embeds: use file_path if available (reconstruct directory structure),
  // otherwise filename + language, or fall back to the embed id.
  for (const codeEmbed of files.code) {
    let filePath: string;
    if (codeEmbed.file_path) {
      filePath = codeEmbed.file_path;
    } else if (codeEmbed.filename) {
      filePath = `code/${codeEmbed.filename}`;
    } else {
      const ext = getFileExtensionForLanguage(codeEmbed.language);
      filePath = `code/${codeEmbed.embed_id}.${ext}`;
    }
    zip.file(filePath, codeEmbed.content);
  }
  for (const transcriptEmbed of files.transcripts) {
    zip.file(`transcripts/${transcriptEmbed.filename}`, transcriptEmbed.content);
  }
  for (const imageEmbed of files.images) {
    zip.file(`images/${imageEmbed.filename}`, imageEmbed.blob);
  }
  for (const audioFile of files.generatedAudio) {
    zip.file(`generated-audio/${audioFile.filename}`, audioFile.blob);
  }
  for (const file of files.staticFiles) {
    zip.file(`static-files/${file.filename}`, file.blob);
  }
  for (const recording of files.audio) {
    zip.file(`uploads/audio/${recording.filename}`, recording.blob);
    // Always write a transcript sidecar - empty file if no transcript yet.
    const transcriptFilename =
      recording.filename.replace(/\.[^.]+$/, "") + "_transcript.txt";
    zip.file(`uploads/audio/${transcriptFilename}`, recording.transcript);
  }
  // PDFs are page screenshots (the encrypted PDF binary is never stored client-side).
  for (const pdfEmbed of files.pdfs) {
    for (const page of pdfEmbed.pages) {
      zip.file(`uploads/pdfs/${pdfEmbed.folderName}/${page.filename}`, page.blob);
    }
  }
}

/** `filename` without its extension (a trailing dot stays, like the original regex). */
export function chatZipBase(filename: string): string {
  return filename.replace(/\.[^.]+$/, "");
}

/** TypeScript zip layout of one chat (flag-off path); returns the download file name. */
export async function writeChatZipTs(
  zip: ZipTarget,
  input: {
    filename: string;
    completenessJson: string | null;
    chat: Chat;
    messages: Message[];
    piiOptions: PIIExportOptions | undefined;
    files: ChatZipFiles;
    yaml: string;
  },
): Promise<string> {
  const filenameWithoutExt = chatZipBase(input.filename);
  if (input.completenessJson !== null) zip.file("export-metadata.json", input.completenessJson);
  zip.file(`${filenameWithoutExt}.yml`, input.yaml);
  // Add Markdown file, respecting PII visibility
  zip.file(
    `${filenameWithoutExt}.md`,
    await convertChatToMarkdown(input.chat, input.messages, input.piiOptions),
  );
  addChatZipFilesTs(zip, input.files);
  return `${filenameWithoutExt}.zip`;
}

/** Triggers the browser download of a generated zip blob. */
function saveZipBlob(zipBlob: Blob, downloadName: string): void {
  const url = URL.createObjectURL(zipBlob);
  const link = document.createElement("a");
  link.href = url;
  link.download = downloadName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Downloads a single chat as a zip with yml, markdown, and code files
 * @param chat - The chat to download
 * @param messages - Array of messages in the chat
 * @param piiOptions - Optional PII export options to control sensitive data handling
 */
export async function downloadChatAsZip(
  chat: Chat,
  messages: Message[],
  piiOptions?: PIIExportOptions,
): Promise<void> {
  try {
    console.warn(
      "[ZipExportService] Starting zip download for chat:",
      chat.chat_id,
    );

    const zip = new JSZip();

    // Generate filename base (without extension)
    const filename = await generateChatFilename(chat, "");

    const hydrated = await hydrateChatForExport(chat, messages);
    messages = hydrated.messages;
    if (hydrated.completeness.status === "partial") {
      console.warn("[ZipExportService] Export is partial:", hydrated.completeness.warnings);
    }
    const completenessJson = JSON.stringify(hydrated.completeness, null, 2);

    // Add YAML file, respecting PII visibility
    const yamlContent = await convertChatToYaml(
      chat,
      messages,
      false,
      piiOptions,
      hydrated,
    );

    const files = await collectChatZipFiles(messages);
    const rust = rustChatZip();
    let zipName: string;
    if (rust) {
      const { rustPlanChatZip, applyChatZipPlan } = await rust;
      const input = { filename, completenessJson, chat, messages, piiOptions, files, yaml: yamlContent };
      const plan = await rustPlanChatZip(input, (content) => tipTapToReadableMarkdown(content as never));
      applyChatZipPlan(zip, plan, input);
      zipName = plan.zipName;
    } else {
      zipName = await writeChatZipTs(zip, {
        filename, completenessJson, chat, messages, piiOptions, files, yaml: yamlContent,
      });
    }

    // Generate and download zip
    const zipBlob = await zip.generateAsync({ type: "blob" });
    saveZipBlob(zipBlob, zipName);

    console.warn(
      "[ZipExportService] Zip download completed for chat:",
      chat.chat_id,
    );
  } catch (error) {
    console.error("[ZipExportService] Error downloading chat as zip:", error);
    throw new Error("Failed to download chat as zip");
  }
}

/**
 * Downloads multiple chats as a zip with folders for each chat
 */
export async function downloadChatsAsZip(
  chats: Chat[],
  messagesMap: Map<string, Message[]>,
): Promise<void> {
  try {
    console.warn(
      "[ZipExportService] Starting bulk zip download for",
      chats.length,
      "chats",
    );

    const zip = new JSZip();
    let successCount = 0;

    // Process each chat
    for (const chat of chats) {
      try {
        const messages = messagesMap.get(chat.chat_id) || [];

        // Generate filename base (without extension)
        const filename = await generateChatFilename(chat, "");
        const rust = rustChatZip();

        if (rust) {
          const { rustPlanChatZip, applyChatZipPlan } = await rust;
          const yamlContent = await convertChatToYaml(chat, messages, false);
          const files = await collectChatZipFiles(messages);
          const input = { filename, completenessJson: null, chat, messages, piiOptions: undefined, files, yaml: yamlContent };
          const plan = await rustPlanChatZip(input, (content) => tipTapToReadableMarkdown(content as never));
          const chatFolder = zip.folder(plan.base);
          if (!chatFolder) {
            console.warn(
              "[ZipExportService] Failed to create folder for chat:",
              chat.chat_id,
            );
            continue;
          }
          applyChatZipPlan(chatFolder, plan, input);
          successCount++;
          continue;
        }

        // Create folder for this chat
        const chatFolder = zip.folder(chatZipBase(filename));
        if (!chatFolder) {
          console.warn(
            "[ZipExportService] Failed to create folder for chat:",
            chat.chat_id,
          );
          continue;
        }

        const yamlContent = await convertChatToYaml(chat, messages, false);
        await writeChatZipTs(chatFolder, {
          filename, completenessJson: null, chat, messages, piiOptions: undefined,
          files: await collectChatZipFiles(messages), yaml: yamlContent,
        });

        successCount++;
      } catch (error) {
        console.warn(
          "[ZipExportService] Error processing chat for bulk download:",
          chat.chat_id,
          error,
        );
      }
    }

    if (successCount === 0) {
      throw new Error("No chats could be downloaded");
    }

    // Generate and download zip
    const zipBlob = await zip.generateAsync({ type: "blob" });
    const now = new Date();
    const rustBulk = rustChatZip();
    if (rustBulk) {
      saveZipBlob(zipBlob, await (await rustBulk).rustBulkZipName(now.toISOString()));
    } else {
      // Use current date/time for bulk download filename
      const zipDateStr = now
        .toISOString()
        .slice(0, 19)
        .replace(/[:-]/g, "-")
        .replace("T", "_");
      saveZipBlob(zipBlob, `chats_${zipDateStr}.zip`);
    }

    console.warn(
      "[ZipExportService] Bulk zip download completed:",
      successCount,
      "chats",
    );
  } catch (error) {
    console.error("[ZipExportService] Error in bulk zip download:", error);
    throw error;
  }
}

/**
 * Interface for code file data used in group downloads
 */
export interface CodeFileData {
  code: string;
  language: string;
  filename?: string;
}

export interface ApplicationProjectFileRef {
  path?: string;
  embed_id?: string;
}

export interface ApplicationProjectZipOptions {
  appName: string;
  fileRefs: ApplicationProjectFileRef[];
}

/**
 * Downloads all source files referenced by an application embed as a project ZIP.
 * The application manifest path is authoritative so generated projects preserve
 * their directory structure instead of flattening child code embed filenames.
 */
export async function downloadApplicationProjectZip({
  appName,
  fileRefs,
}: ApplicationProjectZipOptions): Promise<void> {
  try {
    const refs = fileRefs.filter((ref) => ref.embed_id && ref.path);
    if (refs.length === 0) {
      throw new Error("Application project has no downloadable files");
    }

    const embeds = await loadEmbeds(refs.map((ref) => String(ref.embed_id)));
    const embedsById = new Map(embeds.map((embed) => [embed.embed_id, embed]));
    const zip = new JSZip();
    const projectFiles: Array<{ path: string; code: string }> = [];

    for (const ref of refs) {
      const embedId = String(ref.embed_id);
      const embed = embedsById.get(embedId);
      if (!embed?.content) {
        throw new Error(`Application file is not available: ${ref.path}`);
      }
      const decoded = await decodeToonContent(embed.content);
      if (!isRecord(decoded)) {
        throw new Error(`Application file could not be decoded: ${ref.path}`);
      }
      const rawCode = stringValue(decoded.code) || stringValue(decoded.content) || "";
      if (!rawCode) {
        throw new Error(`Application file is empty: ${ref.path}`);
      }
      const parsed = parseCodeEmbedContent(rawCode, {
        language: stringValue(decoded.language) || stringValue(decoded.lang) || "text",
        filename: stringValue(decoded.filename),
      });
      projectFiles.push({ path: String(ref.path), code: parsed.code });
    }

    const rust = rustChatZip();
    let zipName: string;
    if (rust) {
      const planned = await (await rust).rustApplicationZip(appName, projectFiles.map((file) => file.path));
      planned.paths.forEach((path, index) => zip.file(path, projectFiles[index].code));
      zipName = planned.zipName;
    } else {
      for (const file of projectFiles) zip.file(safeApplicationZipPath(file.path), file.code);
      zipName = `${safeDownloadName(appName || "application")}.zip`;
    }

    const zipBlob = await zip.generateAsync({ type: "blob" });
    saveZipBlob(zipBlob, zipName);
  } catch (error) {
    console.error("[ZipExportService] Error downloading application project zip:", error);
    throw new Error("Failed to download application project zip");
  }
}

function safeApplicationZipPath(path: string): string {
  const parts = path
    .replace(/\\/g, "/")
    .split("/")
    .map((part) => part.trim())
    .filter((part) => part && part !== "." && part !== "..");
  return parts.join("/") || "application-file.txt";
}

function safeDownloadName(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "application";
}

/**
 * Downloads multiple code files as a zip archive
 * Used for downloading all code files from a code embed group
 * Parses each code file to extract filename from language:filepath header if present
 */
export async function downloadCodeFilesAsZip(
  codeFiles: CodeFileData[],
): Promise<void> {
  try {
    console.warn("[ZipExportService] Downloading code files as zip:", {
      fileCount: codeFiles.length,
    });

    if (codeFiles.length === 0) {
      throw new Error("No code files to download");
    }

    // If only one file, download it directly without zip
    if (codeFiles.length === 1) {
      const file = codeFiles[0];
      await downloadCodeFile(file.code, file.language, file.filename);
      return;
    }

    const zip = new JSZip();
    const usedFilenames = new Set<string>();
    const rust = rustChatZip();

    // Parse code content to extract filename from header (e.g., "dockerfile:app/Dockerfile")
    // This also strips the header line from the code content
    const parsedFiles = codeFiles.map((file) => ({
      file,
      parsed: parseCodeEmbedContent(file.code, {
        language: file.language,
        filename: file.filename,
      }),
    }));
    const now = new Date();
    const planned = rust
      ? await (await rust).rustCodeFileNames(
          parsedFiles.map(({ file, parsed }) => ({
            filename: file.filename ?? null,
            headerFilename: parsed.filename ?? null,
            language: parsed.language || file.language,
          })),
          now.toISOString(),
        )
      : null;

    // Add each code file to the zip
    for (let i = 0; i < parsedFiles.length; i++) {
      const { file, parsed } = parsedFiles[i];
      const finalCode = parsed.code;
      const finalLanguage = parsed.language || file.language;
      if (planned) {
        zip.file(planned.names[i], finalCode);
        continue;
      }

      // Determine filename - use provided filename or extract from parsed header
      let downloadFilename: string;
      if (file.filename) {
        // Extract just the filename from any path
        const pathParts = file.filename.split(/[/\\]/);
        downloadFilename = pathParts[pathParts.length - 1];
      } else if (parsed.filename) {
        // Use filename extracted from header (extract basename)
        const pathParts = parsed.filename.split(/[/\\]/);
        downloadFilename = pathParts[pathParts.length - 1];
      } else {
        const ext = getFileExtensionForLanguage(finalLanguage);
        downloadFilename = `code_snippet.${ext}`;
      }

      // Ensure unique filenames by appending index if needed
      let finalFilename = downloadFilename;
      if (usedFilenames.has(downloadFilename.toLowerCase())) {
        const ext = downloadFilename.lastIndexOf(".");
        if (ext > 0) {
          finalFilename = `${downloadFilename.slice(0, ext)}_${i + 1}${downloadFilename.slice(ext)}`;
        } else {
          finalFilename = `${downloadFilename}_${i + 1}`;
        }
      }
      usedFilenames.add(finalFilename.toLowerCase());

      // Add the parsed (header-stripped) code to the zip
      zip.file(finalFilename, finalCode);
    }

    // Generate and download zip
    const zipBlob = await zip.generateAsync({ type: "blob" });
    if (planned) {
      saveZipBlob(zipBlob, planned.zipName);
    } else {
      // Generate zip filename with timestamp
      const zipDateStr = now
        .toISOString()
        .slice(0, 19)
        .replace(/[:-]/g, "-")
        .replace("T", "_");
      saveZipBlob(zipBlob, `code_files_${zipDateStr}.zip`);
    }

    console.warn(
      "[ZipExportService] Code files zip download completed:",
      codeFiles.length,
      "files",
    );
  } catch (error) {
    console.error(
      "[ZipExportService] Error downloading code files as zip:",
      error,
    );
    throw new Error("Failed to download code files");
  }
}

/**
 * Downloads a code file with appropriate naming
 * Parses the code content to extract filename from language:filepath header if present
 */
export async function downloadCodeFile(
  codeContent: string,
  language: string,
  filename?: string,
): Promise<void> {
  try {
    console.warn("[ZipExportService] Downloading code file:", {
      language,
      filename,
    });

    // Parse code content to extract filename from header (e.g., "dockerfile:app/Dockerfile")
    // This also strips the header line from the code content
    const parsed = parseCodeEmbedContent(codeContent, { language, filename });

    // Use parsed values - the parser extracts filename from header if not already provided
    const finalCode = parsed.code;
    const finalLanguage = parsed.language || language;
    // For download, extract just the filename from the full path
    const rust = rustChatZip();
    let downloadFilename: string;
    if (rust) {
      const planned = await (await rust).rustCodeFileNames(
        [{ filename: filename ?? null, headerFilename: parsed.filename ?? null, language: finalLanguage }],
        new Date().toISOString(),
      );
      downloadFilename = planned.names[0];
    } else if (filename) {
      // Use explicitly provided filename (extract basename if it's a path)
      const pathParts = filename.split(/[/\\]/);
      downloadFilename = pathParts[pathParts.length - 1];
    } else if (parsed.filename) {
      // Use filename extracted from header (extract basename if it's a path)
      const pathParts = parsed.filename.split(/[/\\]/);
      downloadFilename = pathParts[pathParts.length - 1];
    } else {
      // Fallback to generic name with language-appropriate extension
      const ext = getFileExtensionForLanguage(finalLanguage);
      downloadFilename = `code_snippet.${ext}`;
    }

    console.warn("[ZipExportService] Resolved download filename:", {
      originalFilename: filename,
      parsedFilename: parsed.filename,
      downloadFilename,
    });

    // Create blob and download with the parsed (header-stripped) code
    const blob = new Blob([finalCode], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = downloadFilename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    console.warn(
      "[ZipExportService] Code file download completed:",
      downloadFilename,
    );
  } catch (error) {
    console.error("[ZipExportService] Error downloading code file:", error);
    throw new Error("Failed to download code file");
  }
}
