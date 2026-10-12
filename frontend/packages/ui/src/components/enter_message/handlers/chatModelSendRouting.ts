/** Keep an explicit @model mention authoritative over the chat preference. */
export function applyChatModelSendRouting(markdown: string, selection: string): string {
  if (selection === 'auto' || /@(?:ai-model|best-model):/.test(markdown)) return markdown;
  const separator = selection.indexOf('/');
  if (separator < 1 || separator === selection.length - 1) return markdown;
  return `@ai-model:${selection.slice(separator + 1)}:${selection.slice(0, separator)} ${markdown}`;
}
