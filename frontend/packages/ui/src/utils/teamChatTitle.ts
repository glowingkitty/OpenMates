/** Derive an ordinary Team chat title locally, without sending text to AI. */
export function teamChatTitleFromMessage(content: string, maxCharacters = 80): string {
  const text = content.replace(/\s+/gu, ' ').trim();
  if (!text) return 'New team chat';
  const characters = Array.from(text);
  if (characters.length <= maxCharacters) return text;
  return characters.slice(0, Math.max(1, maxCharacters - 1)).join('').trimEnd() + '…';
}
