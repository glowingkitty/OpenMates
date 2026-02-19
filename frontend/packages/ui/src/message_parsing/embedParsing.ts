// Embed node parsing functions
// Handles parsing of different embed types from markdown content
// Uses the shared CodeBlockStateMachine for reliable code fence detection

import { EmbedNodeAttributes } from "./types";
import { EMBED_PATTERNS, generateUUID, CodeBlockStateMachine } from "./utils";

/**
 * Map embed reference type from server to EmbedNodeType
 * @param embedType - Server embed type (app_skill_use, website, code, etc.)
 * @returns EmbedNodeType for TipTap
 */
function mapEmbedReferenceType(embedType: string): string {
  const typeMap: Record<string, string> = {
    app_skill_use: "app-skill-use", // New type for app skill results
    focus_mode_activation: "focus-mode-activation", // Focus mode activation indicator
    website: "web-website",
    video: "videos-video", // YouTube and other video embeds
    place: "maps-place",
    event: "maps-event",
    // User-pinned map location (sent as {"type":"location","embed_id":"..."} by the client)
    location: "maps",
    code: "code-code",
    sheet: "sheets-sheet",
    document: "docs-doc",
    file: "file",
  };

  return typeMap[embedType] || embedType;
}

/**
 * Determine embed type based on language
 * @param language - The code fence language (e.g., 'python', 'doc', 'document')
 * @returns The embed type ('code-code' or 'docs-doc')
 */
function getEmbedTypeFromLanguage(language?: string): "code-code" | "docs-doc" {
  const normalizedLang = (language || "").toLowerCase().trim();
  if (normalizedLang === "doc" || normalizedLang === "document") {
    return "docs-doc";
  }
  return "code-code";
}

/**
 * Create a preview embed node for write mode
 * These are temporary and don't create entries in EmbedStore
 */
function createPreviewEmbed(
  content: string,
  language?: string,
  filename?: string,
): EmbedNodeAttributes {
  const id = generateUUID();
  const embedType = getEmbedTypeFromLanguage(language);
  const normalizedLang = (language || "").toLowerCase().trim();

  const previewEmbed: EmbedNodeAttributes = {
    id,
    type: embedType,
    status: "finished", // Show as finished for preview
    contentRef: `preview:${embedType}:${id}`, // Special prefix for preview embeds
    // Count all lines including empty ones (matches backend: code_content.count('\n') + 1)
    lineCount:
      embedType === "code-code" ? content.split("\n").length : undefined,
    wordCount:
      embedType === "docs-doc"
        ? content.split(/\s+/).filter((w) => w.trim()).length
        : undefined,
    code: content, // Store content for preview rendering
  };

  // Add type-specific attributes
  if (embedType === "code-code") {
    previewEmbed.language = normalizedLang || undefined;
    previewEmbed.filename = filename || undefined;
  } else {
    // For doc blocks, check for title comment
    const titleMatch = content.match(EMBED_PATTERNS.TITLE_COMMENT);
    if (titleMatch) {
      previewEmbed.title = titleMatch[1];
    }
  }

  return previewEmbed;
}

/**
 * Create a read mode embed node for streamed content
 */
function createReadEmbed(
  content: string,
  language?: string,
  filename?: string,
): EmbedNodeAttributes {
  const id = generateUUID();
  const embedType = getEmbedTypeFromLanguage(language);
  const normalizedLang = (language || "").toLowerCase().trim();

  const readEmbed: EmbedNodeAttributes = {
    id,
    type: embedType,
    status: "finished",
    contentRef: `stream:${id}`,
    // Count all lines including empty ones (matches backend: code_content.count('\n') + 1)
    lineCount:
      embedType === "code-code" ? content.split("\n").length : undefined,
    wordCount:
      embedType === "docs-doc"
        ? content.split(/\s+/).filter((w) => w.trim()).length
        : undefined,
  };

  if (embedType === "code-code") {
    readEmbed.language = normalizedLang || undefined;
    readEmbed.filename = filename || undefined;
  } else {
    const titleMatch = content.match(EMBED_PATTERNS.TITLE_COMMENT);
    if (titleMatch) {
      readEmbed.title = titleMatch[1];
    }
  }

  return readEmbed;
}

/**
 * Parse embed nodes from markdown content
 * Uses the shared CodeBlockStateMachine for reliable code fence detection
 *
 * Handles:
 * - JSON embed references (```json with embed_id)
 * - json_embed blocks (legacy URL format)
 * - Regular code blocks (```python, etc.)
 * - document_html blocks
 * - Tables
 * - URLs (in read mode only)
 */
export function parseEmbedNodes(
  markdown: string,
  mode: "write" | "read",
): EmbedNodeAttributes[] {
  const lines = markdown.split("\n");
  const embedNodes: EmbedNodeAttributes[] = [];

  // Use the shared state machine for reliable code block detection
  const stateMachine = new CodeBlockStateMachine();

  // Track pending blocks that need post-processing
  let pendingJsonContent = "";
  let pendingJsonEmbedContent = "";
  let pendingDocHtmlContent = "";
  let pendingDocHtmlTitle: string | undefined;
  let pendingDocHtmlFilename: string | undefined;
  let pendingCodeContent = "";
  let pendingCodeLanguage: string | undefined;
  let pendingCodeFilename: string | undefined;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const event = stateMachine.processLine(line, i);

    switch (event.event) {
      case "block_opened":
        // Reset pending content for the new block
        if (event.specialFence === "json") {
          pendingJsonContent = "";
        } else if (event.specialFence === "json_embed") {
          pendingJsonEmbedContent = "";
        } else if (event.specialFence === "document_html") {
          pendingDocHtmlContent = "";
          pendingDocHtmlTitle = undefined;
          pendingDocHtmlFilename = undefined;
        } else {
          // Regular code block
          pendingCodeContent = "";
          pendingCodeLanguage = event.language;
          pendingCodeFilename = event.filename;
        }
        break;

      case "content_line":
        // Accumulate content based on what type of block we're in
        if (event.specialFence === "json") {
          pendingJsonContent += line + "\n";
        } else if (event.specialFence === "json_embed") {
          pendingJsonEmbedContent += line + "\n";
        } else if (event.specialFence === "document_html") {
          pendingDocHtmlContent += line + "\n";
          // Check for title comment
          const titleMatch = line.trim().match(EMBED_PATTERNS.TITLE_COMMENT);
          if (titleMatch && !pendingDocHtmlTitle) {
            pendingDocHtmlTitle = titleMatch[1];
          }
          // Check for filename comment
          const filenameMatch = line
            .trim()
            .match(EMBED_PATTERNS.FILENAME_COMMENT);
          if (filenameMatch && !pendingDocHtmlFilename) {
            pendingDocHtmlFilename = filenameMatch[1];
          }
        } else {
          // Regular code block content
          pendingCodeContent += line + "\n";
        }
        break;

      case "block_closed":
        // Process the completed block based on its type
        if (event.specialFence === "json") {
          // Parse JSON embed reference
          const content = event.content || pendingJsonContent;
          try {
            const embedRef = JSON.parse(content.trim());
            if (embedRef.type && embedRef.embed_id) {
              const id = generateUUID();
              const embedStatus = mode === "write" ? "processing" : "finished";

              // CRITICAL: Extract app_id and skill_id from JSON reference
              // These are needed by AppSkillUseRenderer to render the correct Svelte component
              // even before the full embed data arrives from the server
              const embedAttrs: EmbedNodeAttributes = {
                id,
                type: mapEmbedReferenceType(embedRef.type),
                status: embedRef.status || embedStatus,
                contentRef: `embed:${embedRef.embed_id}`,
              };

              // Copy app_id and skill_id if present (for app_skill_use embeds)
              if (embedRef.app_id) {
                embedAttrs.app_id = embedRef.app_id;
              }
              if (embedRef.skill_id) {
                embedAttrs.skill_id = embedRef.skill_id;
              }

              // Copy query if present (for search skills)
              if (embedRef.query) {
                embedAttrs.query = embedRef.query;
              }

              // Copy provider if present (for search skills)
              if (embedRef.provider) {
                embedAttrs.provider = embedRef.provider;
              }

              // Copy focus mode metadata if present (for focus_mode_activation embeds)
              if (embedRef.focus_id) {
                embedAttrs.focus_id = embedRef.focus_id;
              }
              if (embedRef.focus_mode_name) {
                embedAttrs.focus_mode_name = embedRef.focus_mode_name;
              }

              embedNodes.push(embedAttrs);
              console.debug(
                "[parseEmbedNodes] Created embed from JSON reference:",
                {
                  type: embedRef.type,
                  embed_id: embedRef.embed_id,
                  app_id: embedRef.app_id,
                  skill_id: embedRef.skill_id,
                  query: embedRef.query,
                  provider: embedRef.provider,
                  focus_id: embedRef.focus_id,
                  focus_mode_name: embedRef.focus_mode_name,
                  status: embedAttrs.status,
                  mode,
                },
              );
            }
          } catch (error) {
            console.debug(
              "[parseEmbedNodes] JSON block is not an embed reference:",
              error,
            );
          }
          pendingJsonContent = "";
        } else if (event.specialFence === "json_embed") {
          // Parse json_embed block (legacy URL format)
          const content = event.content || pendingJsonEmbedContent;
          try {
            const embedData = JSON.parse(content.trim());
            if (embedData.type === "website" && embedData.url) {
              const id = generateUUID();
              embedNodes.push({
                id,
                type: "web-website",
                status: "finished",
                contentRef: null,
                url: embedData.url,
                title: embedData.title || null,
                description: embedData.description || null,
                favicon: embedData.favicon || null,
                image: embedData.image || null,
              });
              console.debug(
                "[parseEmbedNodes] Created web embed from json_embed:",
                {
                  url: embedData.url,
                  hasMetadata: !!(embedData.title || embedData.description),
                },
              );
            }
          } catch (error) {
            console.error(
              "[parseEmbedNodes] Error parsing json_embed block:",
              error,
            );
          }
          pendingJsonEmbedContent = "";
        } else if (event.specialFence === "document_html") {
          // Create docs-doc embed from document_html block
          const content = (event.content || pendingDocHtmlContent).replace(
            /\n$/,
            "",
          );
          const wordCount = content.split(/\s+/).filter((w) => w.trim()).length;
          const id = generateUUID();

          if (mode === "write") {
            embedNodes.push({
              id,
              type: "docs-doc",
              status: "finished",
              contentRef: `preview:docs-doc:${id}`,
              title: pendingDocHtmlTitle,
              filename: pendingDocHtmlFilename,
              wordCount,
              code: content,
            });
            console.debug("[parseEmbedNodes] Created preview docs-doc embed:", {
              id,
              wordCount,
              filename: pendingDocHtmlFilename,
            });
          } else {
            embedNodes.push({
              id,
              type: "docs-doc",
              status: "finished",
              contentRef: `stream:${id}`,
              title: pendingDocHtmlTitle,
              filename: pendingDocHtmlFilename,
              wordCount,
            });
          }
          pendingDocHtmlContent = "";
          pendingDocHtmlTitle = undefined;
          pendingDocHtmlFilename = undefined;
        } else {
          // Regular code block - create embed
          const content = (event.content || pendingCodeContent).replace(
            /\n$/,
            "",
          );
          const language = event.language || pendingCodeLanguage;
          const filename = event.filename || pendingCodeFilename;

          if (mode === "write") {
            const embed = createPreviewEmbed(content, language, filename);
            embedNodes.push(embed);
            console.debug("[parseEmbedNodes] Created preview code embed:", {
              id: embed.id,
              type: embed.type,
              language: language || "none",
              contentLength: content.length,
            });
          } else {
            const embed = createReadEmbed(content, language, filename);
            embedNodes.push(embed);
          }

          pendingCodeContent = "";
          pendingCodeLanguage = undefined;
          pendingCodeFilename = undefined;
        }
        break;

      case "outside_block":
        // Not inside any code block - check for other embed types
        // (tables and URLs are handled below)
        break;
    }
  }

  // Now handle non-code-block embeds (tables and URLs)
  // These need a separate pass since they don't use code fences
  parseNonCodeBlockEmbeds(lines, mode, embedNodes);

  return embedNodes;
}

/**
 * Parse non-code-block embeds (tables and URLs)
 * These are handled separately since they don't use code fences
 */
function parseNonCodeBlockEmbeds(
  lines: string[],
  mode: "write" | "read",
  embedNodes: EmbedNodeAttributes[],
): void {
  // Use a fresh state machine to track code blocks (to skip content inside them)
  const stateMachine = new CodeBlockStateMachine();

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const event = stateMachine.processLine(line, i);

    // Skip lines inside code blocks
    if (event.event === "content_line" || event.event === "block_opened") {
      i++;
      continue;
    }

    // NOTE: Table/sheet embeds are NO LONGER detected here.
    // Tables are now converted to sheet embeds by the backend (stream_consumer.py),
    // which replaces raw markdown tables with JSON embed references:
    //   ```json\n{"type":"sheet","embed_id":"<uuid>"}\n```
    // These are picked up by the JSON embed reference parsing in the code-block
    // state machine above (case "block_closed" → embedRef.type === "sheet").

    // Parse URLs only in read mode (write mode URLs are handled by streamingSemantics)
    if (mode === "read" && event.event === "outside_block") {
      const originalLine = lines[i];

      // Build protected ranges for URLs inside markdown links [text](url)
      const protectedRanges: Array<{ start: number; end: number }> = [];
      const linkRegex = /\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/g;
      let linkMatch: RegExpExecArray | null;
      while ((linkMatch = linkRegex.exec(originalLine)) !== null) {
        const full = linkMatch[0];
        const url = linkMatch[1];
        const urlStartInFull = full.indexOf("(") + 1;
        const absStart = (linkMatch.index ?? 0) + urlStartInFull;
        protectedRanges.push({ start: absStart, end: absStart + url.length });
      }

      // Find standalone URLs using shared pattern which supports optional protocol
      const urlRegex = EMBED_PATTERNS.URL;
      let urlMatch: RegExpExecArray | null;
      while ((urlMatch = urlRegex.exec(originalLine)) !== null) {
        let url = urlMatch[0];
        const startIdx = urlMatch.index ?? 0;

        // Skip URLs inside markdown links
        const isProtected = protectedRanges.some(
          (r) => startIdx >= r.start && startIdx < r.end,
        );
        if (isProtected) {
          continue;
        }

        // Normalize URL by adding https:// if protocol is missing
        if (!/^https?:\/\//i.test(url)) {
          url = `https://${url}`;
        }

        const id = generateUUID();
        let type = "web-website";

        // Check if it's a YouTube URL
        if (EMBED_PATTERNS.YOUTUBE_URL.test(url)) {
          type = "videos-video";
        }

        embedNodes.push({
          id,
          type,
          status: "finished",
          contentRef: `stream:${id}`,
          url,
        });
      }
    }

    i++;
  }
}
