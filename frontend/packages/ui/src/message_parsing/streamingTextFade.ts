import type { Node as ProseMirrorNode } from '@tiptap/pm/model';

/** Text added without replacing existing rendered text. Structural or markdown
 * corrections remain visible immediately so earlier content never fades again. */
export function appendedTextRanges(oldDoc: ProseMirrorNode, newDoc: ProseMirrorNode): Array<{ from: number; to: number }> {
  const stableText = oldDoc.textContent;
  const nextText = newDoc.textContent;
  if (!nextText.startsWith(stableText) || nextText.length === stableText.length) return [];

  const ranges: Array<{ from: number; to: number }> = [];
  let textOffset = 0;
  newDoc.descendants((node, position) => {
    if (!node.isText) return;
    const previousOffset = textOffset;
    textOffset += node.text?.length ?? 0;
    const from = position + Math.max(0, stableText.length - previousOffset);
    const to = position + node.nodeSize;
    if (to > from) ranges.push({ from, to });
  });
  return ranges;
}
