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
//
// TWO-PASS APPROACH for appId resolution:
//
// Pass 1 — collect appId from sibling `embed` nodes already in the document.
//   `embed` nodes (type "app-skill-use") carry `app_id` directly from the JSON
//   fenced block in the markdown — it is always available synchronously, on the
//   very first parse, even on page reload. We collect all app_ids present in the
//   document to use as a fallback when the in-memory ref index is empty.
//
// Pass 2 — convert embed: link marks to embedInline nodes.
//   Primary:  resolveAppIdByRef() — works during live streaming once the ref has
//             been registered via chatSyncServiceHandlersAI.
//   Fallback: app_id collected from sibling embed nodes (Pass 1) — always available,
//             gives instant correct colour/icon on page reload without any async wait.
//
// This means inline badges render with the correct gradient on the SAME render pass
// as the embed preview card, with zero additional async work.

// Lazy singleton reference to embedStore (populated on first call).
// Used only for the secondary resolveAppIdByRef() lookup (live-streaming path).
let _embedStoreRef: import("../services/embedStore").EmbedStore | null = null;
async function _ensureEmbedStore(): Promise<void> {
  if (!_embedStoreRef) {
    const mod = await import("../services/embedStore");
    _embedStoreRef = mod.embedStore;
  }
}
function _getEmbedStore(): import("../services/embedStore").EmbedStore | null {
  return _embedStoreRef;
}

/**
 * Pass 1: Walk the document tree and collect all `app_id` values from `embed`
 * nodes (type "app-skill-use"). These are always populated from the raw JSON
 * fenced block in the markdown, so they are available on the first synchronous
 * parse without any IDB or network access.
 *
 * Returns a Map<embedRef | "*", appId> where "*" is a catch-all for the most
 * common app_id in the document (used when a ref can't be matched specifically).
 */
function collectEmbedAppIds(doc: any): string | null {
  // We walk the tree and collect all app_id values from `embed` nodes.
  // In practice a single message belongs to one app, so we return the first found.
  const appIds: string[] = [];

  function walk(node: any): void {
    if (!node) return;
    // `embed` nodes produced by enhanceDocumentWithEmbeds / groupConsecutiveEmbedsInDocument
    // carry attrs.app_id or attrs.appId from the fenced JSON block.
    if (node.type === "embed" || node.type === "app-skill-use") {
      const id = node.attrs?.app_id || node.attrs?.appId;
      if (typeof id === "string" && id) appIds.push(id);
    }
    if (Array.isArray(node.content)) {
      for (const child of node.content) walk(child);
    }
  }

  walk(doc);
  // Return the most-frequent app_id (or the only one). For mixed-app messages
  // this gives the dominant app; for single-app messages (the common case) it's exact.
  if (appIds.length === 0) return null;
  const freq = new Map<string, number>();
  for (const id of appIds) freq.set(id, (freq.get(id) ?? 0) + 1);
  let best = appIds[0];
  let bestCount = 0;
  for (const [id, count] of Array.from(freq.entries())) {
    if (count > bestCount) {
      best = id;
      bestCount = count;
    }
  }
  return best;
}

/**
 * Pass 2 inner: walk a node and convert embed: link marks to embedInline nodes.
 * Uses the pre-collected `fallbackAppId` when the live ref index has no entry.
 */
function convertEmbedLinksInNode(
  node: any,
  fallbackAppId: string | null,
): any | any[] {
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
      const embedRef = href.slice("embed:".length);
      const displayText = node.text || embedRef;

      // Primary: check the in-memory ref index (populated during live streaming).
      // Fallback: use app_id from sibling embed nodes collected in Pass 1 —
      //   always available on first parse, even on page reload, with no async work.
      const appId =
        _getEmbedStore()?.resolveAppIdByRef(embedRef) ?? fallbackAppId;

      return {
        type: "embedInline",
        attrs: {
          embedRef,
          embedId: null, // resolved lazily at click time via embedStore.resolveByRef()
          displayText,
          appId,
        },
      };
    }
  }

  // Recurse into children
  if (node.content && Array.isArray(node.content)) {
    const newContent: any[] = [];
    for (const child of node.content) {
      const result = convertEmbedLinksInNode(child, fallbackAppId);
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
 *
 * Two-pass: first collects app_id from sibling embed nodes (always available),
 * then converts embed: links using that as a fallback for the appId gradient.
 * Returns a new document object (does not mutate the input).
 */
function convertEmbedLinks(doc: any): any {
  if (!doc || !doc.content) return doc;
  // Warm up the embedStore ref asynchronously so the live-streaming path works
  // on subsequent renders. The result is intentionally not awaited — this function
  // must remain synchronous. The ref will be ready for the next render cycle.
  _ensureEmbedStore().catch(() => {
    /* ignore — embedStore may not be loaded in SSR/test envs */
  });
  // Pass 1: collect app_id from embed nodes already in the document.
  const fallbackAppId = collectEmbedAppIds(doc);
  // Pass 2: convert embed: links, using fallbackAppId when ref index has no entry.
  return convertEmbedLinksInNode(doc, fallbackAppId);
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
