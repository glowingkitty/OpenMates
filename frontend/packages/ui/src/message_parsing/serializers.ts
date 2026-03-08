// Serializers for the unified message parsing architecture
// Handles conversion between different formats and clipboard operations

import { EmbedNodeAttributes, EmbedClipboardData, TipTapNode, TipTapDoc } from "./types";
import { groupHandlerRegistry } from "./groupHandlers";
import { parseMarkdownToTiptap } from "../components/enter_message/utils/markdownParser";
import { copyToClipboard } from "../utils/clipboardUtils";

/**
 * Convert TipTap document JSON to canonical markdown format for sending
 * This ensures embeds are serialized in a standard way that can be parsed consistently
 */
export function tipTapToCanonicalMarkdown(doc: TipTapDoc): string {
  if (!doc || !doc.content) {
    return "";
  }

  const lines: string[] = [];

  for (const node of doc.content) {
    switch (node.type) {
      case "paragraph":
        lines.push(serializeParagraph(node));
        break;

      case "embed":
        lines.push(serializeEmbedToMarkdown(node.attrs as EmbedNodeAttributes));
        break;

      case "heading":
        lines.push(serializeHeading(node));
        break;

      case "bulletList":
      case "orderedList":
        lines.push(serializeList(node));
        break;

      case "blockquote":
        lines.push(serializeBlockquote(node));
        break;

      case "sourceQuote":
        lines.push(serializeSourceQuote(node));
        break;

      default:
        // For unknown nodes, try to extract text content
        lines.push(extractTextContent(node));
    }
  }

  const filteredLines = lines.filter((line) => line.length > 0);
  const finalResult = filteredLines.join("\n\n");

  // Performance: Removed console.debug with .map() that allocated an array of
  // debug objects on every call. This function runs on every delimiter keystroke
  // and the allocation was measurable overhead in typing benchmarks.

  return finalResult;
}

/**
 * Convert markdown to TipTap document JSON format for display
 * This parses markdown and creates appropriate TipTap nodes including embeds
 */
export function markdownToTipTap(markdown: string): TipTapDoc {
  // Use the full markdown parser that handles headings, bold, code blocks, etc.
  // console.debug('[markdownToTipTap] Parsing markdown:', markdown.substring(0, 100));

  if (!markdown.trim()) {
    return {
      type: "doc",
      content: [],
    };
  }

  // Use the full-featured markdown parser from markdownParser.ts
  return parseMarkdownToTiptap(markdown);
}

/**
 * Create clipboard data for embed nodes.
 *
 * The payload carries enough metadata to:
 *  1. Re-insert the TipTap embed node with its contentRef so the embed resolver
 *     can decrypt and render it from IndexedDB (cross-chat works because embed keys
 *     are wrapped under the user master key, not per-chat).
 *  2. Provide lightweight inlineContent metadata (title, url, app_id, etc.) that
 *     the embed renderer can use while the full decrypt is in progress.
 *
 * The contentRef ("embed:{embed_id}") is the canonical key.  The embed data itself
 * stays in the user's IndexedDB and is never written to the clipboard — clipboard
 * only carries the reference + lightweight metadata.
 */
export function createEmbedClipboardData(
  attrs: EmbedNodeAttributes,
): EmbedClipboardData {
  return {
    version: 1,
    id: attrs.id,
    type: attrs.type,
    language: attrs.language,
    filename: attrs.filename,
    contentRef: attrs.contentRef,
    contentHash: attrs.contentHash,
    // Lightweight metadata for preview rendering while the full embed resolves.
    // Only non-sensitive fields are included — no encrypted content or AES keys.
    inlineContent: {
      app_id: attrs.app_id,
      skill_id: attrs.skill_id,
      title: attrs.title,
      url: attrs.url,
      description: attrs.description,
      favicon: attrs.favicon,
      image: attrs.image,
      query: attrs.query,
      provider: attrs.provider,
      lineCount: attrs.lineCount,
      wordCount: attrs.wordCount,
    },
  };
}

/**
 * Parse clipboard JSON data back to embed attributes.
 * Used when pasting embeds to reconstruct the TipTap node.
 *
 * The reconstructed node has status="finished" because clipboard data only
 * captures completed embeds (processing/error embeds are not copyable).
 * The contentRef ("embed:{embed_id}") allows the embed renderer to resolve
 * the full content from IndexedDB.
 */
export function parseEmbedClipboardData(
  data: EmbedClipboardData,
): EmbedNodeAttributes {
  return {
    id: data.id,
    type: data.type,
    status: "finished", // Clipboard data represents completed embeds
    contentRef: data.contentRef,
    contentHash: data.contentHash,
    language: data.language,
    filename: data.filename,
    // Restore inlineContent metadata fields so the preview renders while resolving
    ...(data.inlineContent ?? {}),
  };
}

/**
 * Encode embed JSON into an HTML string that can be stored in the text/html
 * clipboard entry.  The JSON is placed in a hidden <meta> tag so it survives
 * the round-trip through Safari's clipboard (Safari allows text/html but
 * silently drops non-allowlisted MIME types like application/x-openmates-embed).
 *
 * The paste handler reads text/html, locates the meta tag, and extracts the JSON.
 * The visible body of the HTML is the human-readable plain-text so that pasting
 * into a rich-text editor still produces readable content.
 *
 * @internal
 */
function _buildEmbedHtml(json: string, plainText: string): string {
  // Encode JSON in a data attribute to survive HTML sanitisation.
  // Base64 avoids issues with quotes/angle-brackets in the JSON value.
  const b64 =
    typeof btoa !== "undefined" ? btoa(unescape(encodeURIComponent(json))) : "";
  const escapedText = plainText
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return `<html><head><meta name="x-openmates-embed" content="${b64}"></head><body><pre>${escapedText}</pre></body></html>`;
}

/**
 * Write an embed node to the system clipboard using three MIME types:
 *   - "application/x-openmates-embed": structured JSON for in-app paste on Chromium/Firefox
 *   - "text/html": hidden JSON in a <meta> tag for in-app paste on Safari
 *   - "text/plain": human-readable fallback for pasting outside OpenMates
 *
 * When pasted inside OpenMates MessageInput, the embed reference is detected
 * (via application/x-openmates-embed on Chromium/Firefox, or text/html meta tag
 * on Safari) and re-inserted as a live embed card (resolved from IndexedDB via
 * contentRef). When pasted in an external app, only the text/plain value is used.
 *
 * **Safari clipboard gesture token compatibility:**
 * Safari requires that navigator.clipboard.write() is called synchronously within
 * a user-gesture handler. Any await before the clipboard call causes the gesture
 * token to expire. This function accepts a Promise<string> for plainText — when
 * ClipboardItem is available, it is constructed synchronously with the promise as
 * the blob value, so navigator.clipboard.write() is called immediately without
 * awaiting. Safari 13.1+ and all modern Chromium/Firefox support Promise<Blob> in
 * ClipboardItem constructors.
 *
 * Call sites should pass `Promise.resolve(text)` when the text is already known,
 * or a pending Promise<string> from an async content-resolution call that was
 * started (but not awaited) before calling this function. The caller should
 * independently await the content promise to know when the copy is complete.
 *
 * Falls back in order:
 *   1. ClipboardItem.write() with Promise<Blob> values — called synchronously,
 *      supports Safari gesture token + triple MIME (custom MIME silently dropped
 *      on Safari but text/html carries the JSON via meta tag)
 *   2. navigator.clipboard.writeText() plain text only (after promise resolves)
 *   3. document.execCommand('copy') via hidden textarea
 *
 * @param attrs          - TipTap embed node attributes
 * @param plainTextPromise - Promise resolving to human-readable text for text/plain
 *                           (e.g. code content, transcript text, video URL)
 */
export async function writeEmbedToClipboard(
  attrs: EmbedNodeAttributes,
  plainTextPromise: string | Promise<string>,
): Promise<void> {
  const clipboardData = createEmbedClipboardData(attrs);
  const json = JSON.stringify(clipboardData);

  // Normalise: wrap plain strings in a resolved promise so all paths below
  // can treat the value uniformly.
  const textPromise: Promise<string> =
    typeof plainTextPromise === "string"
      ? Promise.resolve(plainTextPromise)
      : plainTextPromise;

  // Attempt 1: ClipboardItem with all three MIME types (Chromium / Firefox).
  //
  // The ClipboardItem constructor is called synchronously (within the user
  // gesture), and navigator.clipboard.write() is also called synchronously.
  // The actual blob content resolves asynchronously, which Safari allows —
  // the gesture token is captured at the navigator.clipboard.write() call,
  // not when the blob promise resolves.
  //
  // Three MIME types are written:
  //  - text/plain:  human-readable content (all browsers)
  //  - text/html:   hidden JSON in <meta name="x-openmates-embed"> (Safari in-app paste)
  //  - application/x-openmates-embed:  raw JSON (Chromium/Firefox in-app paste)
  //
  // Safari rejects ClipboardItem entirely when a non-allowlisted MIME type is
  // present (e.g. application/x-openmates-embed), so we fall through to Attempt 2.
  if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
    const textBlobPromise = textPromise.then(
      (t) => new Blob([t], { type: "text/plain" }),
    );
    const htmlBlobPromise = textPromise.then(
      (t) => new Blob([_buildEmbedHtml(json, t)], { type: "text/html" }),
    );
    const embedBlobPromise = textPromise.then(
      () => new Blob([json], { type: "application/x-openmates-embed" }),
    );

    try {
      // navigator.clipboard.write() is called synchronously here — no await before this point.
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/plain": textBlobPromise,
          "text/html": htmlBlobPromise,
          "application/x-openmates-embed": embedBlobPromise,
        }),
      ]);
      console.debug(
        "[writeEmbedToClipboard] Copied via ClipboardItem (triple MIME, promise-based)",
      );
      return;
    } catch {
      // Attempt 1 failed — likely Safari rejecting application/x-openmates-embed.
      // Fall through to Attempt 2: Safari-safe MIMEs only (text/html carries JSON via meta tag).
    }

    // Attempt 2: text/html + text/plain only (Safari-safe).
    // The embed JSON is embedded in the text/html meta tag so the paste handler
    // can still reconstruct the embed card via Path B (meta tag extraction).
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/plain": textBlobPromise,
          "text/html": htmlBlobPromise,
        }),
      ]);
      console.debug(
        "[writeEmbedToClipboard] Copied via ClipboardItem (Safari-safe: text/html + text/plain)",
      );
      return;
    } catch (err) {
      // ClipboardItem entirely unsupported — fall through to writeText.
      console.warn(
        "[writeEmbedToClipboard] ClipboardItem.write failed (both attempts), trying writeText:",
        err,
      );
    }
  }

  // Attempts 2 + 3 require the resolved text value.
  // Falls back through writeText → execCommand via the unified ClipboardService.
  const plainText = await textPromise;
  await copyToClipboard(plainText);
}

/**
 * Write multiple embed references to the clipboard (for message-level copy
 * when a message contains one or more embeds).
 *
 * text/plain:                    the full message text (markdown, may contain embed blocks)
 * application/x-openmates-embed: JSON array of EmbedClipboardData, one per embed in the message
 *
 * When pasted inside OpenMates MessageInput, the paste handler reads the JSON array
 * and inserts each embed node before inserting the surrounding message text.
 *
 * Uses the same Promise<Blob> ClipboardItem pattern as writeEmbedToClipboard for
 * Safari gesture-token compatibility — see that function's doc for full details.
 *
 * @param embedAttrs       - Array of TipTap embed node attributes for all embeds in the message
 * @param messageTextPromise - Promise resolving to the full message text (markdown), used as text/plain
 */
export async function writeMessageWithEmbedsToClipboard(
  embedAttrs: EmbedNodeAttributes[],
  messageTextPromise: string | Promise<string>,
): Promise<void> {
  // Normalise string → resolved promise so all paths below are uniform.
  const textPromise: Promise<string> =
    typeof messageTextPromise === "string"
      ? Promise.resolve(messageTextPromise)
      : messageTextPromise;

  if (embedAttrs.length === 0) {
    // No embeds — plain text copy via the unified ClipboardService
    // (writeText → execCommand fallback chain).
    const messageText = await textPromise;
    await copyToClipboard(messageText);
    return;
  }

  const clipboardItems = embedAttrs.map(createEmbedClipboardData);
  const json = JSON.stringify(clipboardItems);

  // Attempt 1: ClipboardItem with all three MIME types (Chromium / Firefox).
  // See writeEmbedToClipboard for full explanation of the gesture-token and
  // two-attempt Safari strategy.
  if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
    const textBlobPromise = textPromise.then(
      (t) => new Blob([t], { type: "text/plain" }),
    );
    const htmlBlobPromise = textPromise.then(
      (t) => new Blob([_buildEmbedHtml(json, t)], { type: "text/html" }),
    );
    const embedBlobPromise = textPromise.then(
      () => new Blob([json], { type: "application/x-openmates-embed" }),
    );

    try {
      // navigator.clipboard.write() called synchronously — no await before this point.
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/plain": textBlobPromise,
          "text/html": htmlBlobPromise,
          "application/x-openmates-embed": embedBlobPromise,
        }),
      ]);
      console.debug(
        "[writeMessageWithEmbedsToClipboard] Copied via ClipboardItem (triple MIME, promise-based)",
      );
      return;
    } catch {
      // Attempt 1 failed — likely Safari rejecting application/x-openmates-embed.
    }

    // Attempt 2: text/html + text/plain only (Safari-safe).
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/plain": textBlobPromise,
          "text/html": htmlBlobPromise,
        }),
      ]);
      console.debug(
        "[writeMessageWithEmbedsToClipboard] Copied via ClipboardItem (Safari-safe: text/html + text/plain)",
      );
      return;
    } catch (err) {
      console.warn(
        "[writeMessageWithEmbedsToClipboard] ClipboardItem.write failed (both attempts), falling back:",
        err,
      );
    }
  }

  // writeText → execCommand fallback via the unified ClipboardService.
  const messageText = await textPromise;
  await copyToClipboard(messageText);
}

/**
 * Serialize embed node to canonical markdown format
 *
 * For embeds with contentRef (proper embeds stored in EmbedStore), we serialize to:
 *   ```json
 *   {"type": "website", "embed_id": "..."}
 *   ```
 *
 * For legacy embeds without contentRef, we use the old json_embed format with inline data.
 */
function serializeEmbedToMarkdown(attrs: EmbedNodeAttributes): string {
  switch (attrs.type) {
    case "web-website":
      // Check if this is a proper embed with embed_id (stored in EmbedStore)
      if (attrs.contentRef?.startsWith("embed:")) {
        // Serialize to proper embed reference format
        const embed_id = attrs.contentRef.replace("embed:", "");
        const embedRef = JSON.stringify({ type: "website", embed_id }, null, 2);
        return `\`\`\`json\n${embedRef}\n\`\`\``;
      }

      // Legacy: Serialize website embeds to json_embed blocks with inline metadata
      const websiteData: Record<string, string | undefined> = {
        type: "website",
        url: attrs.url,
      };

      // Add optional metadata if available
      if (attrs.title) websiteData.title = attrs.title;
      if (attrs.description) websiteData.description = attrs.description;
      if (attrs.favicon) websiteData.favicon = attrs.favicon;
      if (attrs.image) websiteData.image = attrs.image;

      const jsonContent = JSON.stringify(websiteData, null, 2);
      return `\`\`\`json_embed\n${jsonContent}\n\`\`\``;

    case "videos-video":
      // Check if this is a proper embed with embed_id (stored in EmbedStore)
      if (attrs.contentRef?.startsWith("embed:")) {
        // Serialize to proper embed reference format
        const embed_id = attrs.contentRef.replace("embed:", "");
        const embedRef = JSON.stringify({ type: "video", embed_id }, null, 2);
        return `\`\`\`json\n${embedRef}\n\`\`\``;
      }
      // Legacy: return URL
      return attrs.url || "";

    case "code-code":
      // Check if this is a proper embed with embed_id (stored in EmbedStore)
      if (attrs.contentRef?.startsWith("embed:")) {
        // Serialize to proper embed reference format - this allows drafts to restore the embed
        const embed_id = attrs.contentRef.replace("embed:", "");
        const embedRef = JSON.stringify({ type: "code", embed_id }, null, 2);
        return `\`\`\`json\n${embedRef}\n\`\`\``;
      }

      // Legacy/preview mode: Serialize code blocks with inline content
      const languagePrefix = attrs.language ? `${attrs.language}` : "";
      const pathSuffix = attrs.filename ? `:${attrs.filename}` : "";
      // Include the actual code content if available (stored in attrs.code for preview embeds)
      const codeContent = attrs.code || "";
      return `\`\`\`${languagePrefix}${pathSuffix}\n${codeContent}\n\`\`\``;

    case "docs-doc":
      // Check if this is a proper embed with embed_id (stored in EmbedStore)
      if (attrs.contentRef?.startsWith("embed:")) {
        const embed_id = attrs.contentRef.replace("embed:", "");
        const embedRef = JSON.stringify(
          { type: "docs-doc", embed_id },
          null,
          2,
        );
        return `\`\`\`json\n${embedRef}\n\`\`\``;
      }
      // Legacy/preview mode: Serialize as document_html block
      let docResult = "```document_html\n";
      if (attrs.title) {
        docResult += `<!-- title: "${attrs.title}" -->\n`;
      }
      docResult += "```";
      return docResult;

    case "sheets-sheet":
      let tableResult = "";
      if (attrs.title) {
        tableResult += `<!-- title: "${attrs.title}" -->\n\n`;
      }
      // Create a simple table placeholder
      tableResult += "| Column 1 | Column 2 |\n";
      tableResult += "|----------|----------|\n";
      tableResult += "| Data     | Data     |";
      return tableResult;

    case "image":
      // User-uploaded images: serialized as embed references when contentRef is set
      // (contentRef is set by handleSend after storing TOON content in EmbedStore)
      if (attrs.contentRef?.startsWith("embed:")) {
        const embed_id = attrs.contentRef.replace("embed:", "");
        const embedRef = JSON.stringify({ type: "image", embed_id }, null, 2);
        return `\`\`\`json\n${embedRef}\n\`\`\``;
      }
      // No contentRef yet (e.g. still uploading, or legacy static image) — omit
      return "";

    case "maps":
      // Map location embeds: serialized as embed references pointing to EmbedStore.
      // The TOON content (lat/lon/address/etc.) was stored by insertMap() in embedHandlers.ts.
      // The backend parses this block to inject location context into the LLM prompt.
      if (attrs.contentRef?.startsWith("embed:")) {
        const embed_id = attrs.contentRef.replace("embed:", "");
        const embedRef = JSON.stringify(
          { type: "location", embed_id },
          null,
          2,
        );
        return `\`\`\`json\n${embedRef}\n\`\`\``;
      }
      // No contentRef — embed was not stored (e.g. storage failed). Omit silently.
      return "";

    case "recording":
      // Audio recording embeds: serialized as embed references pointing to EmbedStore.
      // The TOON content (S3 keys, AES key, transcript) was stored by handleSend()
      // in sendHandlers.ts after the recording was uploaded and transcribed.
      // The backend uses the transcript for LLM context and the S3 reference for
      // future audio skill processing.
      if (attrs.contentRef?.startsWith("embed:")) {
        const embed_id = attrs.contentRef.replace("embed:", "");
        const embedRef = JSON.stringify(
          { type: "audio-recording", embed_id },
          null,
          2,
        );
        return `\`\`\`json\n${embedRef}\n\`\`\``;
      }
      // No contentRef — either still uploading/transcribing (should not happen at
      // send time as handleSend blocks on uploading embeds) or demo mode (no upload).
      return "";

    case "pdf":
      // PDF embeds: serialized as embed references when a contentRef is set.
      // contentRef is set by insertPdf() / embedHandlers.ts once the server-side
      // OCR pipeline completes and the backend sends a WebSocket embed_update event.
      // The backend parses this block to inject the extracted PDF text as LLM context.
      // When status is 'processing' (OCR in flight), we still emit a reference —
      // the backend will provide the content once OCR finishes.
      if (attrs.contentRef?.startsWith("embed:")) {
        const embed_id = attrs.contentRef.replace("embed:", "");
        const embedRef = JSON.stringify({ type: "pdf", embed_id }, null, 2);
        return `\`\`\`json\n${embedRef}\n\`\`\``;
      }
      // No contentRef yet (OCR not done). Emit a placeholder reference using the
      // uploadEmbedId so the backend can still reference the PDF in the message.
      if (attrs.uploadEmbedId) {
        const embedRef = JSON.stringify(
          { type: "pdf", embed_id: attrs.uploadEmbedId },
          null,
          2,
        );
        return `\`\`\`json\n${embedRef}\n\`\`\``;
      }
      return "";

    default:
      // Check if this is a group type that can be handled by a group handler
      if (attrs.type.endsWith("-group")) {
        const groupMarkdown = groupHandlerRegistry.groupToMarkdown(attrs);
        if (groupMarkdown) {
          return groupMarkdown;
        }
      }

      return "";
  }
}

/**
 * Serialize paragraph node to markdown
 *
 * IMPORTANT: Embeds that produce block-level markdown (like code fences) need to be
 * separated from surrounding text with double newlines. Otherwise the markdown parser
 * won't recognize the code fence properly.
 */
function serializeParagraph(node: TipTapNode): string {
  if (!node.content) return "";

  // First pass: serialize all children and track which are block-level embeds
  const serializedParts: { content: string; isBlockEmbed: boolean }[] = [];

  for (const child of node.content) {
    if (child.type === "text") {
      let text = child.text || "";

      // Apply marks
      if (child.marks) {
        for (const mark of child.marks) {
          switch (mark.type) {
            case "bold":
              text = `**${text}**`;
              break;
            case "italic":
              text = `*${text}*`;
              break;
            case "code":
              text = `\`${text}\``;
              break;
            case "link":
              // If the link text is the same as the href (plain URL), output just the URL
              // This preserves user input without adding unnecessary markdown link syntax
              const href = String(mark.attrs?.href || "");
              if (text === href || text.trim() === href.trim()) {
                // Plain URL - output as-is without markdown link syntax
                text = href;
              } else {
                // Actual markdown link with different text - use markdown syntax
                text = `[${text}](${href})`;
              }
              break;
          }
        }
      }

      serializedParts.push({ content: text, isBlockEmbed: false });
    } else if (child.type === "embed") {
      // Handle inline unified embed nodes
      // For all embed types, use the standard serialization logic
      const embedMarkdown = serializeEmbedToMarkdown((child.attrs || {}) as EmbedNodeAttributes);
      // Check if this embed produces block-level markdown (contains code fences)
      const isBlockEmbed = embedMarkdown.includes("```");
      serializedParts.push({ content: embedMarkdown, isBlockEmbed });
    } else if (child.type === "hardBreak") {
      // Handle hard breaks to ensure proper line separation
      serializedParts.push({ content: "\n", isBlockEmbed: false });
    } else if (child.type === "webEmbed" || child.type === "videoEmbed") {
      // Legacy support for old embed node types (if any still exist)
      serializedParts.push({
        content: child.attrs?.url || "",
        isBlockEmbed: false,
      });
    } else if (child.type === "bestModelMention") {
      // Handle best-model alias mention nodes - serialize to backend format
      // @best-model:best or @best-model:fast
      serializedParts.push({
        content: `@best-model:${child.attrs?.category || "best"}`,
        isBlockEmbed: false,
      });
    } else if (child.type === "aiModelMention") {
      // Handle AI model mention nodes - serialize to backend format
      console.info(
        "[Serializer] Found aiModelMention node, modelId:",
        child.attrs?.modelId,
      );
      serializedParts.push({
        content: `@ai-model:${child.attrs?.modelId || ""}`,
        isBlockEmbed: false,
      });
    } else if (child.type === "mate") {
      // Handle mate mention nodes - serialize to backend format
      serializedParts.push({
        content: `@mate:${child.attrs?.name || ""}`,
        isBlockEmbed: false,
      });
    } else if (child.type === "genericMention") {
      // Handle generic mention nodes (skills, focus modes, settings/memories) - serialize to backend format
      serializedParts.push({
        content: child.attrs?.mentionSyntax || "",
        isBlockEmbed: false,
      });
    }
  }

  // Second pass: join parts with proper separation
  // Block-level embeds need double newlines before and after them
  let result = "";
  for (let i = 0; i < serializedParts.length; i++) {
    const part = serializedParts[i];
    const prevPart = i > 0 ? serializedParts[i - 1] : null;

    if (part.content === "") continue;

    // Add separator if needed
    if (result.length > 0) {
      if (part.isBlockEmbed || (prevPart && prevPart.isBlockEmbed)) {
        // Block embeds need double newline separation
        result += "\n\n";
      }
      // Otherwise no separator (inline content)
    }

    result += part.content;
  }

  return result;
}

/**
 * Serialize heading node to markdown
 */
function serializeHeading(node: TipTapNode): string {
  const level = node.attrs?.level || 1;
  const prefix = "#".repeat(Math.min(level, 6));
  const text = extractTextContent(node);
  return `${prefix} ${text}`;
}

/**
 * Serialize list node to markdown
 */
function serializeList(node: TipTapNode): string {
  if (!node.content) return "";

  const isOrdered = node.type === "orderedList";
  const lines: string[] = [];

  node.content.forEach((item: TipTapNode, index: number) => {
    const prefix = isOrdered ? `${index + 1}. ` : "- ";
    const text = extractTextContent(item);
    lines.push(`${prefix}${text}`);
  });

  return lines.join("\n");
}

/**
 * Serialize blockquote node to markdown
 */
function serializeBlockquote(node: TipTapNode): string {
  const text = extractTextContent(node);
  return text
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n");
}

/**
 * Serialize sourceQuote node back to the original markdown syntax:
 *   > [quoted text](embed:embed_ref)
 *
 * This round-trips correctly: the markdown parser will produce a blockquote
 * containing a link with href="embed:ref", which convertEmbedLinks converts
 * to embedInline, which convertSourceQuotes then converts back to sourceQuote.
 */
function serializeSourceQuote(node: TipTapNode): string {
  const quoteText = node.attrs?.quoteText || "";
  const embedRef = node.attrs?.embedRef || "";
  return `> [${quoteText}](embed:${embedRef})`;
}

/**
 * Extract text content from a node recursively
 */
function extractTextContent(node: TipTapNode): string {
  if (!node) return "";

  if (node.type === "text") {
    return node.text || "";
  }

  if (node.content) {
    return node.content.map(extractTextContent).join("");
  }

  return "";
}
