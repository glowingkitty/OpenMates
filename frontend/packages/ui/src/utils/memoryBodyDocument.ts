/**
 * Memory body <-> editor document conversion.
 * Spec: app-memories.references.embeds.
 *
 * A Memory body is Markdown. Embeds are written inline exactly like chat
 * messages write them (a fenced `json` block holding `{type, embed_id}`), and
 * the editor renders those blocks as embed previews. Everything outside embed
 * blocks round-trips byte for byte: one editor paragraph per line.
 * Memory references are derived from the embed blocks in the body, never edited
 * as a separate field.
 */
import { parse_message } from '../message_parsing/parse_message';
import { tipTapToCanonicalMarkdown } from '../message_parsing/serializers';
import { MAX_MEMORY_REFERENCES, type MemoryReference } from './ruleDocuments';

export interface BodyNode {
  type: string;
  attrs?: Record<string, unknown>;
  content?: BodyNode[];
  text?: string;
}
export interface BodyDocument { type: 'doc'; content: BodyNode[] }

const EMBED_FENCE = /```json\n([\s\S]*?)\n```/g;

function embedFenceId(json: string): string | null {
  try {
    const parsed: unknown = JSON.parse(json);
    if (!parsed || typeof parsed !== 'object') return null;
    const { type, embed_id: id } = parsed as { type?: unknown; embed_id?: unknown };
    return typeof type === 'string' && typeof id === 'string' && id ? id : null;
  } catch { return null; }
}

/** Embed ids written in the body, in order, without duplicates. */
export function embedIdsInBody(body: string): string[] {
  const ids: string[] = [];
  for (const match of body.matchAll(EMBED_FENCE)) {
    const id = embedFenceId(match[1]);
    if (id && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

export function referencesFromBody(body: string): MemoryReference[] {
  return embedIdsInBody(body).map((id) => ({ kind: 'embed' as const, id }));
}

export const bodyExceedsReferenceLimit = (body: string): boolean => embedIdsInBody(body).length > MAX_MEMORY_REFERENCES;

function textParagraphs(text: string): BodyNode[] {
  return text.split('\n').map((line) => (line ? { type: 'paragraph', content: [{ type: 'text', text: line }] } : { type: 'paragraph' }));
}

function embedNode(fence: string): BodyNode | null {
  const parsed = parse_message(fence, 'write', { unifiedParsingEnabled: true }) as BodyDocument | null;
  // The message parser wraps the inline embed node in a paragraph.
  const node = parsed?.content?.flatMap((block) => (block.type === 'embed' ? [block] : block.content ?? [])).find((candidate) => candidate.type === 'embed');
  // Always reference-only: removing the block from a Memory must never delete the embed itself.
  return node ? { ...node, attrs: { ...node.attrs, referenceOnly: true } } : null;
}

export function bodyToDocument(body: string): BodyDocument {
  const content: BodyNode[] = [];
  let cursor = 0;
  const pushText = (text: string, afterEmbed: boolean, beforeEmbed: boolean) => {
    let value = text;
    if (afterEmbed && value.startsWith('\n')) value = value.slice(1);
    if (beforeEmbed && value.endsWith('\n')) value = value.slice(0, -1);
    if (value !== '' || (!afterEmbed && !beforeEmbed)) content.push(...textParagraphs(value));
  };
  let afterEmbed = false;
  for (const match of body.matchAll(EMBED_FENCE)) {
    const node = embedFenceId(match[1]) ? embedNode(match[0]) : null;
    if (!node) continue;
    pushText(body.slice(cursor, match.index), afterEmbed, true);
    content.push({ type: 'paragraph', content: [node] });
    cursor = match.index + match[0].length;
    afterEmbed = true;
  }
  pushText(body.slice(cursor), afterEmbed, false);
  return { type: 'doc', content: content.length ? content : [{ type: 'paragraph' }] };
}

const embedMarkdown = (node: BodyNode): string => tipTapToCanonicalMarkdown({ type: 'doc', content: [node] } as never);

/** Text is written as typed; an embed always stands on its own lines. */
function paragraphText(node: BodyNode): string {
  let out = '';
  let afterEmbed = false;
  for (const child of node.content ?? []) {
    if (child.type === 'embed') {
      if (out !== '' && !out.endsWith('\n')) out += '\n';
      out += embedMarkdown(child);
      afterEmbed = true;
      continue;
    }
    if (afterEmbed) { out += '\n'; afterEmbed = false; }
    out += child.type === 'hardBreak' ? '\n' : child.text ?? '';
  }
  return out;
}

export function documentToBody(doc: BodyDocument): string {
  return (doc.content ?? []).map((node) => (node.type === 'embed' ? embedMarkdown(node) : paragraphText(node))).join('\n');
}

/**
 * Memories saved while references were a separate field keep them: each
 * reference missing from the body is appended as an inline embed block, so the
 * editor shows it and saving keeps it. Unresolvable ones stay in the document's
 * reference list until the author saves a body without them.
 */
export async function bodyWithLegacyReferences(
  body: string,
  references: readonly MemoryReference[] | undefined,
  embedType: (id: string) => Promise<string | null>,
): Promise<string> {
  const present = new Set(embedIdsInBody(body));
  let next = body;
  for (const reference of references ?? []) {
    if (present.has(reference.id)) continue;
    const type = await embedType(reference.id).catch(() => null);
    if (!type) continue;
    const fence = `\`\`\`json\n${JSON.stringify({ type, embed_id: reference.id, reference_only: true }, null, 2)}\n\`\`\``;
    next = next ? `${next}\n${fence}` : fence;
  }
  return next;
}
