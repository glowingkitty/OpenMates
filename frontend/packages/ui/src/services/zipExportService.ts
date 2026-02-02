/**
 * Zip Export Service
 * Handles creating enhanced zip exports for chats with:
 * - YAML format of the chat
 * - Markdown format of the chat history
 * - Separate code files for each code embed (with original file paths)
 * - Separate transcript files for each video transcript embed
 */

import JSZip from "jszip";
import type { Chat, Message } from "../types/chat";
import { convertChatToYaml, generateChatFilename } from "./chatExportService";
import {
  extractEmbedReferences,
  loadEmbeds,
  decodeToonContent,
} from "./embedResolver";
import { tipTapToCanonicalMarkdown } from "../message_parsing/serializers";
import { parseCodeEmbedContent } from "../components/embeds/code/codeEmbedContent";

/**
 * Converts a single message to markdown format
 */
async function convertMessageToMarkdown(message: Message): Promise<string> {
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
      content = message.content;
    } else if (message.content && typeof message.content === "object") {
      content = tipTapToCanonicalMarkdown(message.content);
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
 */
async function convertChatToMarkdown(
  chat: Chat,
  messages: Message[],
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

    // Add all messages
    for (const message of messages) {
      const messageMarkdown = await convertMessageToMarkdown(message);
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
        embed.type === "code" &&
        decodedContent &&
        typeof decodedContent === "object"
      ) {
        const rawCodeContent =
          decodedContent.code || decodedContent.content || "";
        const hintLanguage =
          decodedContent.language || decodedContent.lang || "text";
        const hintFilename = decodedContent.filename || undefined;

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
        let filePath = embed.file_path || decodedContent.file_path || undefined;

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
        console.debug(
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
async function getCodeEmbedsForChat(messages: Message[]): Promise<
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
            .filter((r: any) => {
              return (
                r.transcript || r.formatted_transcript || r.text || r.content
              );
            })
            .map((r: any) => {
              let content = "";

              if (r.metadata?.title) {
                content += `# ${r.metadata.title}\n\n`;
              }

              if (r.url) {
                content += `Source: ${r.url}\n\n`;
              }

              if (r.word_count) {
                content += `Word count: ${r.word_count.toLocaleString()}\n\n`;
              }

              const transcript =
                r.transcript ||
                r.formatted_transcript ||
                r.text ||
                r.content ||
                "";
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
              } catch (e) {
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
        console.debug(
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
async function getVideoTranscriptEmbedsForChat(messages: Message[]): Promise<
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

/**
 * Downloads a single chat as a zip with yml, markdown, and code files
 */
export async function downloadChatAsZip(
  chat: Chat,
  messages: Message[],
): Promise<void> {
  try {
    console.debug(
      "[ZipExportService] Starting zip download for chat:",
      chat.chat_id,
    );

    const zip = new JSZip();

    // Generate filename base (without extension)
    const filename = await generateChatFilename(chat, "");
    const filenameWithoutExt = filename.replace(/\.[^.]+$/, "");

    // Add YAML file
    const yamlContent = await convertChatToYaml(chat, messages, false);
    zip.file(`${filenameWithoutExt}.yml`, yamlContent);

    // Add Markdown file
    const markdownContent = await convertChatToMarkdown(chat, messages);
    zip.file(`${filenameWithoutExt}.md`, markdownContent);

    // Add code embeds as separate files
    const codeEmbeds = await getCodeEmbedsForChat(messages);
    for (const codeEmbed of codeEmbeds) {
      // Use file_path if available (reconstruct directory structure)
      // Otherwise use filename + language, or fallback to embed_id
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

    // Add video transcript embeds as separate files
    const transcriptEmbeds = await getVideoTranscriptEmbedsForChat(messages);
    for (const transcriptEmbed of transcriptEmbeds) {
      // Store transcripts in a transcripts folder
      const filePath = `transcripts/${transcriptEmbed.filename}`;
      zip.file(filePath, transcriptEmbed.content);
    }

    // Generate and download zip
    const zipBlob = await zip.generateAsync({ type: "blob" });
    const url = URL.createObjectURL(zipBlob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${filenameWithoutExt}.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    console.debug(
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
    console.debug(
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
        const filenameWithoutExt = filename.replace(/\.[^.]+$/, "");

        // Create folder for this chat
        const chatFolder = zip.folder(filenameWithoutExt);
        if (!chatFolder) {
          console.warn(
            "[ZipExportService] Failed to create folder for chat:",
            chat.chat_id,
          );
          continue;
        }

        // Add YAML file
        const yamlContent = await convertChatToYaml(chat, messages, false);
        chatFolder.file(`${filenameWithoutExt}.yml`, yamlContent);

        // Add Markdown file
        const markdownContent = await convertChatToMarkdown(chat, messages);
        chatFolder.file(`${filenameWithoutExt}.md`, markdownContent);

        // Add code embeds as separate files
        const codeEmbeds = await getCodeEmbedsForChat(messages);
        for (const codeEmbed of codeEmbeds) {
          let filePath: string;

          if (codeEmbed.file_path) {
            filePath = codeEmbed.file_path;
          } else if (codeEmbed.filename) {
            filePath = `code/${codeEmbed.filename}`;
          } else {
            const ext = getFileExtensionForLanguage(codeEmbed.language);
            filePath = `code/${codeEmbed.embed_id}.${ext}`;
          }

          chatFolder.file(filePath, codeEmbed.content);
        }

        // Add video transcript embeds as separate files
        const transcriptEmbeds =
          await getVideoTranscriptEmbedsForChat(messages);
        for (const transcriptEmbed of transcriptEmbeds) {
          // Store transcripts in a transcripts folder
          const filePath = `transcripts/${transcriptEmbed.filename}`;
          chatFolder.file(filePath, transcriptEmbed.content);
        }

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
    const url = URL.createObjectURL(zipBlob);
    const link = document.createElement("a");
    link.href = url;

    // Use current date/time for bulk download filename
    const now = new Date();
    const zipDateStr = now
      .toISOString()
      .slice(0, 19)
      .replace(/[:-]/g, "-")
      .replace("T", "_");
    link.download = `chats_${zipDateStr}.zip`;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    console.debug(
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

/**
 * Downloads multiple code files as a zip archive
 * Used for downloading all code files from a code embed group
 * Parses each code file to extract filename from language:filepath header if present
 */
export async function downloadCodeFilesAsZip(
  codeFiles: CodeFileData[],
): Promise<void> {
  try {
    console.debug("[ZipExportService] Downloading code files as zip:", {
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

    // Add each code file to the zip
    for (let i = 0; i < codeFiles.length; i++) {
      const file = codeFiles[i];

      // Parse code content to extract filename from header (e.g., "dockerfile:app/Dockerfile")
      // This also strips the header line from the code content
      const parsed = parseCodeEmbedContent(file.code, {
        language: file.language,
        filename: file.filename,
      });
      const finalCode = parsed.code;
      const finalLanguage = parsed.language || file.language;

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
    const url = URL.createObjectURL(zipBlob);
    const link = document.createElement("a");
    link.href = url;

    // Generate zip filename with timestamp
    const now = new Date();
    const zipDateStr = now
      .toISOString()
      .slice(0, 19)
      .replace(/[:-]/g, "-")
      .replace("T", "_");
    link.download = `code_files_${zipDateStr}.zip`;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    console.debug(
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
    console.debug("[ZipExportService] Downloading code file:", {
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
    let downloadFilename: string;
    if (filename) {
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

    console.debug("[ZipExportService] Resolved download filename:", {
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

    console.debug(
      "[ZipExportService] Code file download completed:",
      downloadFilename,
    );
  } catch (error) {
    console.error("[ZipExportService] Error downloading code file:", error);
    throw new Error("Failed to download code file");
  }
}
