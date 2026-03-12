/* eslint-disable @typescript-eslint/no-explicit-any */
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
/**
 * Parse a #L line-range fragment from an embed: href suffix.
 * Supports:
 *   #L42        → { start: 42, end: 42 }
 *   #L10-L20    → { start: 10, end: 20 }
 *   #L10-20     → { start: 10, end: 20 }  (alternate form)
 * Returns null when no valid #L fragment is present.
 */
function _parseLineFragment(raw: string): {
  cleanRef: string;
  lineStart: number | null;
  lineEnd: number | null;
} {
  const lineMatch = raw.match(/#L(\d+)(?:-L?(\d+))?$/);
  if (!lineMatch) {
    return { cleanRef: raw, lineStart: null, lineEnd: null };
  }
  const cleanRef = raw.slice(0, raw.lastIndexOf("#"));
  const lineStart = parseInt(lineMatch[1], 10);
  const lineEnd = lineMatch[2] ? parseInt(lineMatch[2], 10) : lineStart;
  // Normalise reversed ranges
  return {
    cleanRef,
    lineStart: Math.min(lineStart, lineEnd),
    lineEnd: Math.max(lineStart, lineEnd),
  };
}

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
      const rawRef = href.slice("embed:".length);
      const displayText = node.text || "";

      // ── Embed preview large: [!](embed:ref) ──────────────────────────────
      // The LLM signals a full-width large preview card by using "!" as the
      // display text. This becomes a block-level embedPreviewLarge node.
      if (displayText === "!") {
        // Strip any accidental #L suffix (preview cards don't use line highlighting)
        const { cleanRef } = _parseLineFragment(rawRef);
        const appId =
          _getEmbedStore()?.resolveAppIdByRef(cleanRef) ?? fallbackAppId;
        return {
          type: "embedPreviewLarge",
          attrs: {
            embedRef: cleanRef,
            embedId: null,
            appId,
            carouselIndex: 0, // will be overwritten by _hoistBlockEmbedPreviews Phase B
            carouselTotal: 1,
          },
        };
      }

      // ── Fallback for [](embed:ref) — treat as [!](embed:ref) ───────────
      // Empty display text (from LLM hallucination or omission) is treated
      // the same as "!" — a visually highlighted embed preview block.
      // The embedPreviewSmall concept has been removed; all block-level
      // embed previews use the unified embedPreviewLarge node type, which
      // renders responsively (compact at ≤300px, expanded when wider).
      if (displayText === "") {
        const { cleanRef } = _parseLineFragment(rawRef);
        const appId =
          _getEmbedStore()?.resolveAppIdByRef(cleanRef) ?? fallbackAppId;
        return {
          type: "embedPreviewLarge",
          attrs: {
            embedRef: cleanRef,
            embedId: null,
            appId,
            carouselIndex: 0,
            carouselTotal: 1,
          },
        };
      }

      // ── Standard inline embed link: [display text](embed:ref) ────────────
      // Parse optional #L line-range fragment from the embed ref.
      const { cleanRef, lineStart, lineEnd } = _parseLineFragment(rawRef);

      // Primary: check the in-memory ref index (populated during live streaming).
      // Fallback: use app_id from sibling embed nodes collected in Pass 1 —
      //   always available on first parse, even on page reload, with no async work.
      const appId =
        _getEmbedStore()?.resolveAppIdByRef(cleanRef) ?? fallbackAppId;

      return {
        type: "embedInline",
        attrs: {
          embedRef: cleanRef,
          embedId: null, // resolved lazily at click time via embedStore.resolveByRef()
          displayText,
          appId,
          focusLineStart: lineStart,
          focusLineEnd: lineEnd,
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
  const withInlineNodes = convertEmbedLinksInNode(doc, fallbackAppId);
  // Pass 3: hoist embedPreviewLarge nodes out of their
  // paragraph wrappers to become true block-level document nodes.
  return _hoistBlockEmbedPreviews(withInlineNodes);
}

// ─── Block embed preview hoisting ────────────────────────────────────────────
//
// When the LLM writes [](embed:ref) or [!](embed:ref), markdown-it wraps the
// link inside a <p> tag, resulting in a paragraph node containing a single
// embedPreviewLarge child. We hoist those nodes to the
// document level so TipTap treats them as block-level elements.
//
// A paragraph qualifies for hoisting if ALL its meaningful content is a single
// embedPreviewLarge atom. Purely whitespace-only text
// siblings are discarded.

const BLOCK_EMBED_PREVIEW_TYPES = new Set(["embedPreviewLarge"]);

function _hoistBlockEmbedPreviews(doc: any): any {
  if (!doc || !doc.content) return doc;

  // Phase A: hoist block-preview embeds out of their paragraph wrappers.
  const hoisted: any[] = [];

  for (const node of doc.content) {
    // Only inspect paragraph nodes for potential hoisting
    if (node.type !== "paragraph" || !Array.isArray(node.content)) {
      hoisted.push(node);
      continue;
    }

    // Find all non-whitespace children
    const meaningful = node.content.filter(
      (c: any) => !(c.type === "text" && !c.text?.trim()),
    );

    // If the paragraph contains ONLY block-preview embeds (one or more), hoist
    // each one individually.  This handles the common case where the LLM writes
    // multiple [!](embed:ref) links on consecutive lines without blank lines
    // between them — markdown-it wraps them in a single paragraph.  Hoisting
    // each embed individually lets Phase B group them into a carousel.
    const allBlockPreviews =
      meaningful.length > 0 &&
      meaningful.every((c: any) => BLOCK_EMBED_PREVIEW_TYPES.has(c.type));
    if (allBlockPreviews) {
      for (const embedNode of meaningful) {
        hoisted.push(embedNode);
      }
    } else {
      hoisted.push(node);
    }
  }

  // Phase B: assign carouselIndex + carouselTotal to consecutive embedPreviewLarge
  // runs.  Walk the hoisted array and annotate runs of consecutive large-preview
  // nodes with their position within the run.
  const finalContent: any[] = [];
  let runStart = -1;

  function flushRun(endExclusive: number) {
    if (runStart < 0) return;
    const runLen = endExclusive - runStart;
    // The first card's embedRef is the shared runRef — all cards in the run
    // use it as the carousel store key so their navigation is synchronised.
    const runRef = hoisted[runStart].attrs.embedRef as string;
    for (let i = runStart; i < endExclusive; i++) {
      finalContent.push({
        ...hoisted[i],
        attrs: {
          ...hoisted[i].attrs,
          carouselIndex: i - runStart,
          carouselTotal: runLen,
          runRef,
        },
      });
    }
    runStart = -1;
  }

  for (let i = 0; i < hoisted.length; i++) {
    if (hoisted[i].type === "embedPreviewLarge") {
      if (runStart < 0) runStart = i;
      // continue accumulating the run
    } else {
      flushRun(i);
      finalContent.push(hoisted[i]);
    }
  }
  // Flush any trailing run
  flushRun(hoisted.length);

  return { ...doc, content: finalContent };
}

// ─── Source quote detection ──────────────────────────────────────────────────
//
// After `convertEmbedLinks` replaces embed: link marks with `embedInline` atoms,
// we check each `blockquote` node to see if it contains a single paragraph with
// a single `embedInline` child. This pattern matches the verified source quote
// syntax:
//
//   > [quoted text](embed:some-ref-k8D)
//
// If it matches, we replace the entire blockquote with a `sourceQuote` atom node
// that renders as a styled clickable card instead of a plain blockquote.
//
// This MUST run after convertEmbedLinks (which produces embedInline nodes) and
// convertEmbedLinksInNode (which is responsible for the embed: → embedInline transform).

/**
 * Walk a TipTap document and convert blockquotes that contain a single
 * embedInline node into sourceQuote block-level atom nodes.
 *
 * A blockquote matches when its structure is:
 *   blockquote > paragraph > [single child of type embedInline]
 *
 * The embedInline's displayText becomes the quoteText, and its embedRef/appId
 * are carried over to the sourceQuote node attributes.
 *
 * Returns a new document object (does not mutate the input).
 */
function convertSourceQuotes(doc: any): any {
  if (!doc || !doc.content) return doc;

  const newContent = doc.content.flatMap((node: any) => {
    const converted = _convertSourceQuoteNode(node);
    return Array.isArray(converted) ? converted : [converted];
  });

  return { ...doc, content: newContent };
}

/**
 * Convert an inline source quote pattern inside a paragraph:
 *
 *   <prefix text> > [quoted text](embed:ref)
 *
 * into:
 *   - paragraph(<prefix text>)   (optional, omitted if empty)
 *   - sourceQuote(quoted text, embedRef)
 *
 * This handles list-item cases where the quote marker appears inline after
 * an attribution (e.g. "Name: > [quote](embed:ref)") and markdown-it does
 * not produce a blockquote node.
 */
function _convertInlineSourceQuoteParagraph(node: any): any[] | null {
  if (node.type !== "paragraph" || !Array.isArray(node.content)) {
    return null;
  }

  const firstEmbedInlineIndex = node.content.findIndex(
    (child: any) => child?.type === "embedInline",
  );

  if (firstEmbedInlineIndex === -1) {
    return null;
  }

  const embedInlineCount = node.content.filter(
    (child: any) => child?.type === "embedInline",
  ).length;
  if (embedInlineCount !== 1) {
    return null;
  }

  const afterEmbedNodes = node.content.slice(firstEmbedInlineIndex + 1);

  const beforeEmbedNodes = node.content.slice(0, firstEmbedInlineIndex);
  const beforeEmbedText = beforeEmbedNodes
    .filter((child: any) => child?.type === "text")
    .map((child: any) => child.text || "")
    .join("");

  if (!/(^|\s)>\s*$/.test(beforeEmbedText)) {
    return null;
  }

  const cleanedPrefixNodes = beforeEmbedNodes.map((child: any) => ({
    ...child,
  }));

  for (let i = cleanedPrefixNodes.length - 1; i >= 0; i--) {
    const child = cleanedPrefixNodes[i];
    if (child?.type !== "text") {
      continue;
    }

    const text = child.text || "";
    const markerMatch = text.match(/^(.*?)(\s*>\s*)$/);
    if (!markerMatch) {
      break;
    }

    const withoutMarker = markerMatch[1] || "";
    if (withoutMarker.length > 0) {
      child.text = withoutMarker;
    } else {
      cleanedPrefixNodes.splice(i, 1);
    }
    break;
  }

  const hasMeaningfulPrefix = cleanedPrefixNodes.some((child: any) => {
    if (child?.type !== "text") {
      return true;
    }
    return /\S/.test(child.text || "");
  });

  const embedInline = node.content[firstEmbedInlineIndex];
  const cleanedSuffixNodes = afterEmbedNodes.map((child: any) => ({
    ...child,
  }));

  // Remove pure leading/trailing whitespace from the suffix paragraph to avoid
  // creating empty-looking lines around author attributions like
  // " – Hermann Hesse".
  while (cleanedSuffixNodes.length > 0) {
    const first = cleanedSuffixNodes[0];
    if (first?.type !== "text") {
      break;
    }
    const text = first.text || "";
    if (/^\s+$/.test(text)) {
      cleanedSuffixNodes.shift();
      continue;
    }
    first.text = text.replace(/^\s+/, "");
    break;
  }
  while (cleanedSuffixNodes.length > 0) {
    const last = cleanedSuffixNodes[cleanedSuffixNodes.length - 1];
    if (last?.type !== "text") {
      break;
    }
    const text = last.text || "";
    if (/^\s+$/.test(text)) {
      cleanedSuffixNodes.pop();
      continue;
    }
    last.text = text.replace(/\s+$/, "");
    break;
  }

  const hasMeaningfulSuffix = cleanedSuffixNodes.some((child: any) => {
    if (child?.type !== "text") {
      return true;
    }
    return /\S/.test(child.text || "");
  });

  const sourceQuoteNode = {
    type: "sourceQuote",
    attrs: {
      quoteText: embedInline?.attrs?.displayText || "",
      embedRef: embedInline?.attrs?.embedRef || "",
      appId: embedInline?.attrs?.appId || null,
    },
  };

  const outputNodes: any[] = [];

  if (hasMeaningfulPrefix) {
    outputNodes.push({
      ...node,
      content: cleanedPrefixNodes,
    });
  }

  outputNodes.push(sourceQuoteNode);

  if (hasMeaningfulSuffix) {
    outputNodes.push({
      ...node,
      content: cleanedSuffixNodes,
    });
  }

  return outputNodes;
}

/**
 * Inner recursive walker: checks if a node is a blockquote matching the
 * source quote pattern, and if so replaces it with a sourceQuote node.
 * Otherwise recurses into children.
 */
function _convertSourceQuoteNode(node: any): any {
  // Check if this is a blockquote that contains exactly one paragraph
  // with exactly one embedInline child — the source quote pattern.
  if (node.type === "blockquote" && Array.isArray(node.content)) {
    // Filter to meaningful content (skip empty paragraphs)
    const meaningfulChildren = node.content.filter(
      (child: any) =>
        child.type === "paragraph" &&
        Array.isArray(child.content) &&
        child.content.length > 0,
    );

    if (meaningfulChildren.length === 1) {
      const paragraph = meaningfulChildren[0];
      if (Array.isArray(paragraph.content) && paragraph.content.length > 0) {
        const embedIndexes = paragraph.content
          .map((child: any, index: number) =>
            child?.type === "embedInline" ? index : -1,
          )
          .filter((index: number) => index !== -1);

        if (embedIndexes.length === 1) {
          const embedIndex = embedIndexes[0];
          const embedInline = paragraph.content[embedIndex];

          const prefixNodes = paragraph.content
            .slice(0, embedIndex)
            .map((child: any) => ({ ...child }));
          const suffixNodes = paragraph.content
            .slice(embedIndex + 1)
            .map((child: any) => ({ ...child }));

          while (prefixNodes.length > 0) {
            const first = prefixNodes[0];
            if (first?.type !== "text") break;
            const text = first.text || "";
            if (/^\s+$/.test(text)) {
              prefixNodes.shift();
              continue;
            }
            first.text = text.replace(/^\s+/, "");
            break;
          }
          while (prefixNodes.length > 0) {
            const last = prefixNodes[prefixNodes.length - 1];
            if (last?.type !== "text") break;
            const text = last.text || "";
            if (/^\s+$/.test(text)) {
              prefixNodes.pop();
              continue;
            }
            last.text = text.replace(/\s+$/, "");
            break;
          }

          while (suffixNodes.length > 0) {
            const first = suffixNodes[0];
            if (first?.type !== "text") break;
            const text = first.text || "";
            if (/^\s+$/.test(text)) {
              suffixNodes.shift();
              continue;
            }
            first.text = text.replace(/^\s+/, "");
            break;
          }
          while (suffixNodes.length > 0) {
            const last = suffixNodes[suffixNodes.length - 1];
            if (last?.type !== "text") break;
            const text = last.text || "";
            if (/^\s+$/.test(text)) {
              suffixNodes.pop();
              continue;
            }
            last.text = text.replace(/\s+$/, "");
            break;
          }

          const hasMeaningfulPrefix = prefixNodes.some((child: any) => {
            if (child?.type !== "text") return true;
            return /\S/.test(child.text || "");
          });

          const hasMeaningfulSuffix = suffixNodes.some((child: any) => {
            if (child?.type !== "text") return true;
            return /\S/.test(child.text || "");
          });

          const outputNodes: any[] = [];
          if (hasMeaningfulPrefix) {
            outputNodes.push({
              type: "paragraph",
              content: prefixNodes,
            });
          }

          outputNodes.push({
            type: "sourceQuote",
            attrs: {
              quoteText: embedInline.attrs?.displayText || "",
              embedRef: embedInline.attrs?.embedRef || "",
              appId: embedInline.attrs?.appId || null,
            },
          });

          if (hasMeaningfulSuffix) {
            outputNodes.push({
              type: "paragraph",
              content: suffixNodes,
            });
          }

          return outputNodes;
        }
      }
    }
  }

  // Fallback pattern: inline quote marker in a paragraph
  // e.g. "Attribution: > [quoted text](embed:ref)"
  const inlineConversion = _convertInlineSourceQuoteParagraph(node);
  if (inlineConversion) {
    return inlineConversion;
  }

  // Not a source quote blockquote — recurse into children
  if (node.content && Array.isArray(node.content)) {
    const newContent = node.content.flatMap((child: any) => {
      const converted = _convertSourceQuoteNode(child);
      return Array.isArray(converted) ? converted : [converted];
    });
    return { ...node, content: newContent };
  }

  return node;
}

// ──────────────────────────────────────────────────────────────────────────────

/**
 * Unified message parser for both write and read modes
 * @param markdown - The raw markdown content to parse
 * @param mode - 'write' for editing mode, 'read' for display mode
 * @param opts - Parsing options including feature flags
 * @returns TipTap document JSON with unified embed nodes
 */
// ─── Assistant embed → large preview promotion ────────────────────────────────
//
// Assistant read-mode messages should render non app-skill embeds as large cards.
//
// Rules:
// - Non app-skill single embeds (including code) are promoted to embedPreviewLarge.
// - Non app-skill groups are expanded into consecutive embedPreviewLarge nodes so
//   _hoistBlockEmbedPreviews() can turn them into a slideshow run.
// - Code groups keep the existing horizontal regular-size layout (no promotion).
// - App-skill-use and app-skill-use-group never get auto-promoted here.

function getEmbedBaseType(type: string): string {
  return type.endsWith("-group") ? type.slice(0, -"-group".length) : type;
}

function isAppSkillEmbedType(type: string): boolean {
  return type === "app-skill-use" || type === "app-skill-use-group";
}

function extractEmbedId(attrs: any): string | null {
  if (!attrs) return null;
  if (
    typeof attrs.contentRef === "string" &&
    attrs.contentRef.startsWith("embed:")
  ) {
    return attrs.contentRef.replace("embed:", "");
  }
  if (typeof attrs.id === "string" && attrs.id.length > 0) {
    return attrs.id;
  }
  return null;
}

function createLargePreviewNode(embedId: string, appId: string | null): any {
  return {
    type: "embedPreviewLarge",
    attrs: {
      embedRef: embedId,
      embedId,
      appId,
      carouselIndex: 0,
      carouselTotal: 1,
    },
  };
}

function promoteEmbedAttrsToLargeNodes(attrs: any): any[] | null {
  if (!attrs || typeof attrs.type !== "string") return null;

  const embedType = attrs.type as string;
  const baseType = getEmbedBaseType(embedType);

  if (isAppSkillEmbedType(embedType)) return null;

  // Keep code groups as regular horizontal scroll previews.
  if (embedType.endsWith("-group") && baseType === "code-code") {
    return null;
  }

  // Expand non-code groups to consecutive large preview nodes.
  if (embedType.endsWith("-group")) {
    const groupedItems = Array.isArray(attrs.groupedItems)
      ? attrs.groupedItems
      : [];
    const largeNodes = groupedItems
      .map((item: any) => {
        const embedId = extractEmbedId(item);
        if (!embedId) return null;
        return createLargePreviewNode(embedId, getAppIdFromEmbedAttrs(item));
      })
      .filter(Boolean);

    return largeNodes.length > 0 ? largeNodes : null;
  }

  const embedId = extractEmbedId(attrs);
  if (!embedId) return null;
  return [createLargePreviewNode(embedId, getAppIdFromEmbedAttrs(attrs))];
}

/**
 * Derive the appId hint for the embedPreviewLarge node from embed attrs.
 * Used for fast routing in EmbedPreviewLarge.svelte before async resolution.
 */
function getAppIdFromEmbedAttrs(attrs: any): string | null {
  if (!attrs) return null;
  // For app-skill-use, use the explicit app_id
  if (attrs.app_id) return attrs.app_id;
  // For direct types, extract the app prefix (e.g. "docs-doc" → "docs")
  if (typeof attrs.type === "string" && attrs.type.includes("-")) {
    return attrs.type.split("-")[0];
  }
  return null;
}

/**
 * Promote eligible assistant embeds to embedPreviewLarge nodes.
 *
 * For paragraph nodes that contain only embed children (plus optional whitespace),
 * each eligible non app-skill embed is replaced with one or more embedPreviewLarge
 * block nodes. Group nodes may expand into multiple large nodes.
 *
 * This runs recursively so embeds in lists/blockquotes are handled too.
 */
function promoteAssistantEmbedsToLarge(doc: any, role?: string): any {
  if (role !== "assistant") return doc;

  function walkNodes(nodes: any[]): any[] {
    const result: any[] = [];

    for (const node of nodes) {
      if (!node || !Array.isArray(node.content)) {
        result.push(node);
        continue;
      }

      if (node.type === "paragraph") {
        const meaningful = node.content.filter(
          (c: any) => !(c.type === "text" && !c.text?.trim()),
        );

        const isEmbedOnlyParagraph =
          meaningful.length > 0 &&
          meaningful.every((c: any) => c.type === "embed");

        if (isEmbedOnlyParagraph) {
          const promoted = meaningful
            .map((embedNode: any) =>
              promoteEmbedAttrsToLargeNodes(embedNode.attrs),
            )
            .filter((parts: any[] | null) => Array.isArray(parts))
            .flat();

          if (promoted.length > 0) {
            result.push(...promoted);
            continue;
          }
        }

        result.push({ ...node, content: walkNodes(node.content) });
        continue;
      }

      result.push({ ...node, content: walkNodes(node.content) });
    }

    return result;
  }

  if (!Array.isArray(doc.content)) return doc;
  return {
    ...doc,
    content: walkNodes(doc.content),
  };
}

export function parse_message(
  markdown: string,
  mode: "write" | "read",
  opts: ParseMessageOptions = {},
): any {
  // If unified parsing is not enabled, fallback to existing behavior
  if (!opts.unifiedParsingEnabled) {
    const doc = markdownToTipTap(markdown);
    // Still apply embed: link + source quote conversion in read mode even on the fast path
    if (mode === "read") {
      const withLinks = convertEmbedLinks(doc);
      return convertSourceQuotes(withLinks);
    }
    return doc;
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

  // Promote eligible non app-skill embeds to large preview in assistant messages.
  // This runs AFTER grouping (so groups can be converted to slideshow runs) and
  // BEFORE convertEmbedLinks (so _hoistBlockEmbedPreviews can assign carousel metadata).
  if (mode === "read" && opts.role === "assistant") {
    unifiedDoc = promoteAssistantEmbedsToLarge(unifiedDoc, opts.role);
  }

  // Convert embed: link marks to embedInline atom nodes, then detect
  // blockquotes that are source quotes and convert them (read mode only)
  if (mode === "read") {
    unifiedDoc = convertEmbedLinks(unifiedDoc);
    unifiedDoc = convertSourceQuotes(unifiedDoc);
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
