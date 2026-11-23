/**
 * Chat model send routing: prefixes the saved model preference as an
 * `@ai-model:` mention unless the message already names a model.
 *
 * The mention must never share a line with a block construct that starts the
 * message (an uploaded file's embed fence, a heading, a list, a quote, a
 * table): a fence that does not start its line is plain text in markdown, so
 * the file would render as raw JSON instead of its embed (TASK-1610).
 * Native Swift counterpart: apple/OpenMates/Sources/Shared/Composer/ChatModelPreferenceService.swift
 */
const BLOCK_START = /^[ \t]*(?:```|~~~|#{1,6}[ \t]|>|[-*+][ \t]|\d+[.)][ \t]|\|)/;

/** Separator between a prefixed mention and the message: a blank line before block content. */
export function mentionPrefixSeparator(markdown: string): string {
  return BLOCK_START.test(markdown) ? '\n\n' : ' ';
}

/** Keep an explicit @model mention authoritative over the chat preference. */
export function applyChatModelSendRouting(markdown: string, selection: string): string {
  if (selection === 'auto' || /@(?:ai-model|best-model):/.test(markdown)) return markdown;
  const separator = selection.indexOf('/');
  if (separator < 1 || separator === selection.length - 1) return markdown;
  const mention = `@ai-model:${selection.slice(separator + 1)}:${selection.slice(0, separator)}`;
  return `${mention}${mentionPrefixSeparator(markdown)}${markdown}`;
}
