/**
 * Write-mode composer documents keep markdown as plain text: the composer
 * schema has no list, heading, blockquote or rule nodes (editorConfig.ts).
 * The shared markdown parser still emits them, and Tiptap discards a whole
 * document holding an unknown node ("RangeError: Unknown node type:
 * listItem", issue WRPEB), which emptied the composer under a pending send.
 * This turns such blocks back into paragraphs that carry their markdown
 * prefix, so the editor text matches what the user typed or pasted.
 */

type DocNode = { type?: string; attrs?: Record<string, unknown>; content?: DocNode[]; text?: string; marks?: unknown[] };

const FLATTENED_TYPES = new Set(["bulletList", "orderedList", "listItem", "heading", "blockquote", "horizontalRule"]);

function prefixed(block: DocNode, prefix: string): DocNode {
  if (!prefix || block.type !== "paragraph") return block;
  const content = block.content ?? [];
  const first = content[0];
  if (first?.type === "text" && !first.marks) {
    return { ...block, content: [{ ...first, text: prefix + (first.text ?? "") }, ...content.slice(1)] };
  }
  return { ...block, content: [{ type: "text", text: prefix }, ...content] };
}

/** List item text keeps the newline that preceded a nested list in the HTML; drop it. */
function trimTrailingNewline(block: DocNode): DocNode {
  const content = block.content ?? [];
  const last = content[content.length - 1];
  if (block.type !== "paragraph" || last?.type !== "text" || !/\n+$/.test(last.text ?? "")) return block;
  const text = (last.text ?? "").replace(/\n+$/, "");
  const rest = content.slice(0, -1);
  return { ...block, content: text ? [...rest, { ...last, text }] : rest };
}

function textParagraph(text: string): DocNode {
  return { type: "paragraph", content: [{ type: "text", text }] };
}

function flattenList(list: DocNode, depth: number): DocNode[] {
  const indent = "  ".repeat(depth);
  const start = typeof list.attrs?.start === "number" ? list.attrs.start : 1;
  return (list.content ?? []).flatMap((item, index) => {
    const marker = list.type === "orderedList" ? `${start + index}. ` : "- ";
    let markerUsed = false;
    const blocks = (item.content ?? []).flatMap((child) => {
      if (child.type === "bulletList" || child.type === "orderedList") return flattenList(child, depth + 1);
      return flattenBlock(child).map((block) => {
        const prefix = markerUsed ? indent + "  " : indent + marker;
        markerUsed = true;
        return prefixed(trimTrailingNewline(block), prefix);
      });
    });
    return markerUsed ? blocks : [textParagraph(indent + marker.trimEnd()), ...blocks];
  });
}

function flattenBlock(node: DocNode): DocNode[] {
  switch (node?.type) {
    case "bulletList":
    case "orderedList":
      return flattenList(node, 0);
    case "listItem":
      return flattenList({ type: "bulletList", content: [node] }, 0);
    case "heading":
      return [prefixed({ type: "paragraph", content: node.content ?? [] }, "#".repeat(typeof node.attrs?.level === "number" ? node.attrs.level : 1) + " ")];
    case "blockquote":
      return (node.content ?? []).flatMap(flattenBlock).map((block) => prefixed(block, "> "));
    case "horizontalRule":
      return [textParagraph("---")];
    default:
      return [node];
  }
}

/** Returns a write-mode document whose top-level blocks all exist in the composer schema. */
export function flattenWriteModeBlocks<T extends DocNode>(doc: T): T {
  if (!doc || !Array.isArray(doc.content) || !doc.content.some((node) => FLATTENED_TYPES.has(node?.type ?? ""))) return doc;
  return { ...doc, content: doc.content.flatMap(flattenBlock) };
}
