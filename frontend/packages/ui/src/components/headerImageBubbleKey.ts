/**
 * Header image bubbles built from a parent search embed's preview rows have no
 * stored child embed. Their key identifies the bubble in the header only; it is
 * never an embed id, so opening one must not ask the server for it.
 */
const PREVIEW_BUBBLE_MARKER = ':preview:';

export function headerPreviewBubbleKey(parentEmbedId: string, index: number): string {
  return `${parentEmbedId}${PREVIEW_BUBBLE_MARKER}${index}`;
}

/** The child embed to focus in fullscreen, or null when the bubble has no stored child. */
export function headerBubbleFocusChildEmbedId(childEmbedId: string): string | null {
  return childEmbedId && !childEmbedId.includes(PREVIEW_BUBBLE_MARKER) ? childEmbedId : null;
}
