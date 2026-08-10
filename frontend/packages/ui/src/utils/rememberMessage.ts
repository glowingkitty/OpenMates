// frontend/packages/ui/src/utils/rememberMessage.ts
//
// Formats forgotten chat messages for explicit re-insertion into the user's next
// draft. This intentionally does not mutate backend compression state or hidden
// LLM context; the user sees and can edit the quoted content before sending.
// Keep this helper UI-only so message encryption boundaries remain unchanged.

export const REMEMBER_MESSAGE_PREFIX = 'Remember my earlier message:';

export function formatRememberMessageDraft(content: string): string {
  const trimmed = content.trim();
  if (!trimmed) return REMEMBER_MESSAGE_PREFIX;
  const quoted = trimmed
    .split(/\r?\n/)
    .map((line) => `> ${line}`)
    .join('\n');
  return `${REMEMBER_MESSAGE_PREFIX}\n\n${quoted}`;
}
