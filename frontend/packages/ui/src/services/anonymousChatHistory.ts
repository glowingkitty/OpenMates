// Restore generated code/plot source for an anonymous follow-up. The server
// receives only the projected text; embed rows and keys stay in this browser.
import { computeSHA256 } from '../message_parsing/utils';
import { decodeToonContent } from './embedResolver';
import { embedStore } from './embedStore';

const GENERATED_REFERENCE_FENCE = /^[ \t]*```json[ \t]*\r?\n(?<body>\{[^`]*\})\r?\n[ \t]*```[ \t]*(?=\r?$)/gm;
const MAX_REFERENCES = 12;
const MAX_EMBED_CONTEXT_BYTES = 32 * 1024;
// AnonymousHistoryMessage.content has max_length=20_000 on the API.
const MAX_HISTORY_MESSAGE_CHARS = 20_000;

type GeneratedType = 'code' | 'math-plot';

function generatedReference(body: string): { type: GeneratedType; embedId: string } | null {
  let value: unknown;
  try {
    value = JSON.parse(body);
  } catch {
    return null;
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const reference = value as Record<string, unknown>;
  if (Object.keys(reference).length !== 2 || !('type' in reference) || !('embed_id' in reference)) return null;
  if (reference.type !== 'code' && reference.type !== 'math-plot') return null;
  if (typeof reference.embed_id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(reference.embed_id)) return null;
  return { type: reference.type, embedId: reference.embed_id };
}

function fencedSource(source: string, header: string): string {
  const longestRun = Math.max(2, ...Array.from(source.matchAll(/`+/g), (match) => match[0].length));
  const fence = '`'.repeat(longestRun + 1);
  return `${fence}${header}\n${source}\n${fence}`;
}

function sourceFromDecoded(decoded: Record<string, unknown>, type: GeneratedType): string | null {
  if (decoded.type !== type) return null;
  if (type === 'math-plot') {
    return typeof decoded.plot_spec === 'string' && decoded.plot_spec.trim()
      ? fencedSource(decoded.plot_spec, 'plot')
      : null;
  }
  if (typeof decoded.code !== 'string' || !decoded.code.trim()) return null;
  const language = typeof decoded.language === 'string' && /^[a-z0-9_+#.-]{1,32}$/i.test(decoded.language)
    ? decoded.language
    : 'text';
  const filename = typeof decoded.filename === 'string' && /^[^\r\n`]{1,128}$/.test(decoded.filename)
    ? `:${decoded.filename}`
    : '';
  return fencedSource(decoded.code, `${language}${filename}`);
}

/** Project only local, same-chat generated code and plot cards back into AI history. */
export async function projectAnonymousChatHistory(markdown: string, chatId: string): Promise<string> {
  if (!markdown.includes('```json') || !chatId) return markdown;
  const matches = [...markdown.matchAll(GENERATED_REFERENCE_FENCE)];
  if (matches.length === 0) return markdown;

  const expectedChatHash = await computeSHA256(chatId);
  const resolved = new Map<string, string | null>();
  const encoder = new TextEncoder();
  let embedContextBytes = 0;
  let projectedLength = markdown.length;
  let referencesSeen = 0;
  let result = '';
  let cursor = 0;

  for (const match of matches) {
    const original = match[0];
    const start = match.index ?? cursor;
    result += markdown.slice(cursor, start);
    cursor = start + original.length;
    const reference = generatedReference(match.groups?.body ?? '');
    if (!reference) {
      result += original;
      continue;
    }
    if (++referencesSeen > MAX_REFERENCES) {
      result += original;
      continue;
    }

    const cacheKey = `${reference.type}:${reference.embedId}`;
    if (!resolved.has(cacheKey)) {
      let replacement: string | null = null;
      try {
        const contentRef = `embed:${reference.embedId}`;
        const raw = await embedStore.getRawEntry(contentRef);
        if (raw?.hashed_chat_id === expectedChatHash && raw.embed_id === reference.embedId && raw.status === 'finished') {
          const stored = await embedStore.get(contentRef);
          if (stored && typeof stored === 'object' && stored.hashed_chat_id === expectedChatHash && typeof stored.content === 'string') {
            const decoded = await decodeToonContent(stored.content);
            if (decoded) replacement = sourceFromDecoded(decoded, reference.type);
          }
        }
      } catch {
        // The display reference remains available to the local UI and the server
        // strips it from history if its source is unavailable here.
      }
      resolved.set(cacheKey, replacement);
    }

    const replacement = resolved.get(cacheKey);
    const replacementBytes = replacement ? encoder.encode(replacement).byteLength : 0;
    if (replacement && embedContextBytes + replacementBytes <= MAX_EMBED_CONTEXT_BYTES && projectedLength - original.length + replacement.length <= MAX_HISTORY_MESSAGE_CHARS) {
      result += replacement;
      embedContextBytes += replacementBytes;
      projectedLength += replacement.length - original.length;
    } else {
      result += original;
    }
  }

  return result + markdown.slice(cursor);
}
