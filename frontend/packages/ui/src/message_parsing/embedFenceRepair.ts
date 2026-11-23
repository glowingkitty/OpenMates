/**
 * Embed fence repair and raw-embed monitoring for rendered messages.
 *
 * An embed reference is a ```json fence holding `{"type": ..., "embed_id": ...}`.
 * Markdown only treats a fence as a block when it starts its line. Before
 * TASK-1610, clients prefixed the chat's model mention with a single space, so
 * a message that started with an uploaded file was stored as
 * `@ai-model:x:y ```json` and rendered as raw JSON plus a broken code block.
 *
 * - `repairInlineEmbedFences` moves such a fence onto its own block so stored
 *   messages render their embed again.
 * - `reportRawEmbedReferences` logs a content-free console error when a parsed
 *   document still shows an embed reference as text or code. Console errors are
 *   promoted to the error-context log stream and the daily issue digest, so a
 *   renderer that shows raw embed JSON is reported instead of passing silently.
 * Native Swift counterpart: apple/OpenMates/Sources/Shared/Components/RichMarkdownRenderer.swift
 */

const INLINE_EMBED_FENCE =
  /^([^\n`]*\S)[ \t]+(```json)\n([ \t]*\{[^\n]*"embed_id"[^\n]*\})\n[ \t]*(```)/gm;

/** Put an embed fence that follows inline text on the same line into its own block. */
export function repairInlineEmbedFences(markdown: string): string {
  if (!markdown.includes('"embed_id"')) return markdown;
  return markdown.replace(INLINE_EMBED_FENCE, "$1\n\n$2\n$3\n$4");
}

const RAW_EMBED_REFERENCE = /"embed_id"\s*:\s*"[^"]+"/;
export const RAW_EMBED_RENDER_LOG_TAG = "[EmbedRenderAnomaly]";
const reportedKeys = new Set<string>();

interface DocNode {
  type?: string;
  text?: string;
  content?: DocNode[];
}

/** Node types (text or code) in which a raw embed reference is still visible. */
export function findRawEmbedReferenceNodes(doc: DocNode | null | undefined): string[] {
  const found: string[] = [];
  const walk = (node: DocNode | undefined, inCode: boolean): void => {
    if (!node) return;
    const isCode = inCode || node.type === "codeBlock";
    if (node.type === "text" && typeof node.text === "string" && RAW_EMBED_REFERENCE.test(node.text)) {
      found.push(isCode ? "codeBlock" : "text");
    }
    for (const child of node.content ?? []) walk(child, isCode);
  };
  walk(doc ?? undefined, false);
  return found;
}

/**
 * Log one console error per message when the rendered document shows raw
 * embed JSON. The log carries only the role and node kinds, never content.
 */
export function reportRawEmbedReferences(
  doc: DocNode | null | undefined,
  context: { role?: string; messageKey?: string },
): boolean {
  const nodes = findRawEmbedReferenceNodes(doc);
  if (nodes.length === 0) return false;
  const key = `${context.role ?? "unknown"}:${context.messageKey ?? ""}`;
  if (context.messageKey && reportedKeys.has(key)) return true;
  if (context.messageKey) reportedKeys.add(key);
  console.error(
    `${RAW_EMBED_RENDER_LOG_TAG} message shows a raw embed reference instead of its embed`,
    { role: context.role ?? "unknown", nodeKinds: [...new Set(nodes)], count: nodes.length },
  );
  return true;
}
