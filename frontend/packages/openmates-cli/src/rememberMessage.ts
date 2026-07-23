/**
 * Remember-message helpers for CLI and TypeScript SDK send paths.
 * These helpers rewrite explicit user text like "Remember my message @abc123"
 * into a visible quote block before encryption/sending. They do not mutate
 * backend compression state or hidden LLM context.
 */

export interface RememberableMessage {
  id: string;
  content: string;
}

export const REMEMBER_MESSAGE_PREFIX = "Remember my earlier message:";

const REMEMBER_MESSAGE_REFERENCE_RE = /\bRemember my (?:earlier )?message @([A-Za-z0-9-]{4,36})\b/gi;

export function formatRememberMessageDraft(content: string): string {
  const trimmed = content.trim();
  if (!trimmed) return REMEMBER_MESSAGE_PREFIX;
  const quoted = trimmed
    .split(/\r?\n/)
    .map((line) => `> ${line}`)
    .join("\n");
  return `${REMEMBER_MESSAGE_PREFIX}\n\n${quoted}`;
}

export function rewriteRememberMessageReferences(
  message: string,
  messages: RememberableMessage[],
): string {
  return message.replace(REMEMBER_MESSAGE_REFERENCE_RE, (match, messageId: string) => {
    const remembered = messages.find(
      (candidate) => candidate.id === messageId || candidate.id.startsWith(messageId),
    );
    if (!remembered) return match;
    return formatRememberMessageDraft(remembered.content);
  });
}

export function hasRememberMessageReference(message: string): boolean {
  REMEMBER_MESSAGE_REFERENCE_RE.lastIndex = 0;
  return REMEMBER_MESSAGE_REFERENCE_RE.test(message);
}
