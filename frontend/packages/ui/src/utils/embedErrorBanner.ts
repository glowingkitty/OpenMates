/**
 * Visibility rule for the message-level embed error banner
 * (`chat.embed_error.message`, `data-testid="embed-error-banner"`).
 *
 * A failed skill is already shown on its own embed card (status "error").
 * The message-level banner is only for a finished assistant turn that has no
 * answer text because its skills failed. It never shows while the assistant is
 * still working, and never when the finished message answers the user (for
 * example from the other skills of a multi-skill request).
 */

const FENCED_EMBED_REFERENCE_RE = /```(?:json|json_embed)\b[\s\S]*?```/gi;

/** Tiptap node shape used by assistant documents; only text nodes carry prose. */
type DocNode = { type?: unknown; text?: unknown; content?: unknown };

function collectDocText(node: unknown, parts: string[]): void {
  if (Array.isArray(node)) {
    for (const child of node) collectDocText(child, parts);
    return;
  }
  if (!node || typeof node !== 'object') return;
  const docNode = node as DocNode;
  if (docNode.type === 'text' && typeof docNode.text === 'string') parts.push(docNode.text);
  if (docNode.content !== undefined) collectDocText(docNode.content, parts);
}

/** True when the message content holds answer prose besides embed references. */
export function hasAnswerText(content: unknown): boolean {
  if (typeof content === 'string') {
    return content.replace(FENCED_EMBED_REFERENCE_RE, '').trim().length > 0;
  }
  const parts: string[] = [];
  collectDocText(content, parts);
  return parts.join('').trim().length > 0;
}

export function shouldShowEmbedErrorBanner(input: {
  role: string | undefined;
  hasEmbedErrors: boolean;
  /** The assistant turn is still running (streaming, processing or skills pending). */
  responseActive: boolean;
  status: string | undefined;
  content: unknown;
}): boolean {
  if (input.role !== 'assistant' || !input.hasEmbedErrors) return false;
  if (input.responseActive || input.status === 'streaming' || input.status === 'processing') return false;
  return !hasAnswerText(input.content);
}
