// Main entry point for the unified message parsing architecture
// Handles both write_mode (editing) and read_mode (display) parsing

import { ParseMessageOptions } from "./types";
import { markdownToTipTap } from "./serializers";
import { parseEmbedNodes } from "./embedParsing";
import { handleStreamingSemantics } from "./streamingSemantics";
import { enhanceDocumentWithEmbeds } from "./documentEnhancement";
import { groupConsecutiveEmbedsInDocument } from "./embedGrouping";
import { migrateEmbedNodes, needsMigration } from "./migration";

// ─── Inline embed-link conversion ─────────────────────────────────────────────
//
// The LLM may write [display text](embed:some-ref-k8D) in its response.
// markdown-it parses this as a regular TipTap text node with a `link` mark
// whose href is "embed:some-ref-k8D".
//
// `convertEmbedLinks` walks the TipTap document tree (depth-first) and rewrites
// any such text-with-link-mark into an `embedInline` atom node.
//
// Only applied in read mode — the editor (write mode) should keep them as plain
// links so the user can still edit the raw markdown.

/**
 * Walk a TipTap node tree and replace inline link marks whose href starts with
 * "embed:" with `embedInline` atom nodes.
 *
 * This is a read-mode-only transformation: in write mode the raw markdown link
 * syntax `[text](embed:ref)` remains editable.
 *
 * @param node - Any TipTap node (doc, paragraph, text, …)
 * @returns A new node (or array of nodes) with embed: links converted
 */
function convertEmbedLinksInNode(node: any): any | any[] {
  // Leaf text node — check for embed: link mark
  if (node.type === "text" && Array.isArray(node.marks)) {
    const linkMarkIndex = node.marks.findIndex(
      (m: any) =>
        m.type === "link" &&
        typeof m.attrs?.href === "string" &&
        m.attrs.href.startsWith("embed:"),
    );

    if (linkMarkIndex !== -1) {
      const linkMark = node.marks[linkMarkIndex];
      const href: string = linkMark.attrs.href as string;
      // href format: "embed:<embed_ref>"
      const embedRef = href.slice("embed:".length);
      const displayText = node.text || embedRef;

      // Return an embedInline node — the NodeView will resolve embedRef → embedId at render time
      return {
        type: "embedInline",
        attrs: {
          embedRef,
          embedId: null, // resolved lazily via embedStore.resolveByRef()
          displayText,
          appId: null, // resolved lazily via embedStore when fullscreen opens
        },
      };
    }
  }

  // Recurse into children
  if (node.content && Array.isArray(node.content)) {
    const newContent: any[] = [];
    for (const child of node.content) {
      const result = convertEmbedLinksInNode(child);
      if (Array.isArray(result)) {
        newContent.push(...result);
      } else {
        newContent.push(result);
      }
    }
    return { ...node, content: newContent };
  }

  return node;
}

/**
 * Apply embed: link → embedInline conversion to a full TipTap document.
 * Returns a new document object (does not mutate the input).
 */
function convertEmbedLinks(doc: any): any {
  if (!doc || !doc.content) return doc;
  return convertEmbedLinksInNode(doc);
}
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Unified message parser for both write and read modes
 * @param markdown - The raw markdown content to parse
 * @param mode - 'write' for editing mode, 'read' for display mode
 * @param opts - Parsing options including feature flags
 * @returns TipTap document JSON with unified embed nodes
 */
export function parse_message(
  markdown: string,
  mode: "write" | "read",
  opts: ParseMessageOptions = {},
): any {
  // If unified parsing is not enabled, fallback to existing behavior
  if (!opts.unifiedParsingEnabled) {
    const doc = markdownToTipTap(markdown);
    // Still apply embed: link conversion in read mode even on the fast path
    return mode === "read" ? convertEmbedLinks(doc) : doc;
  }

  console.debug("[parse_message] Parsing with unified architecture:", {
    mode,
    length: markdown.length,
  });

  // First, parse basic markdown structure using existing parser
  let basicDoc = markdownToTipTap(markdown);

  // Check if the content needs migration from old embed node types
  if (needsMigration(basicDoc)) {
    console.debug(
      "[parse_message] Migrating old embed node types to unified structure",
    );
    basicDoc = migrateEmbedNodes(basicDoc);
  }

  // Parse normal embed nodes
  const embedNodes = parseEmbedNodes(markdown, mode);

  // Handle streaming semantics for partial/unclosed blocks
  const streamingData = handleStreamingSemantics(markdown, mode);

  // Combine normal embeds with partial embeds for write mode
  const allEmbeds =
    mode === "write"
      ? [...embedNodes, ...streamingData.partialEmbeds]
      : embedNodes;

  // Create a new document with individual embed nodes first
  // This preserves document structure so we can accurately determine what's consecutive
  const docWithIndividualEmbeds = enhanceDocumentWithEmbeds(
    basicDoc,
    allEmbeds,
    mode,
  );

  // Group consecutive embeds of the same type at the document level where we can see actual text between them
  let unifiedDoc = groupConsecutiveEmbedsInDocument(docWithIndividualEmbeds);

  // Convert embed: link marks to embedInline atom nodes (read mode only)
  if (mode === "read") {
    unifiedDoc = convertEmbedLinks(unifiedDoc);
  }

  // Add streaming metadata for write mode highlighting
  if (mode === "write" && streamingData.unclosedBlocks.length > 0) {
    unifiedDoc._streamingData = streamingData;
  }

  console.debug("[parse_message] Created unified document with embeds:", {
    individualEmbedCount: allEmbeds.length,
    unclosedBlocks: streamingData.unclosedBlocks.length,
    mode,
  });

  return unifiedDoc;
}
