/** Stable exchange identities and bounded plain-text previews. */
import type { Message } from '../types/chat';
import MarkdownIt from 'markdown-it';
import { voiceTranscriptDisplayText } from './voiceTranscriptDisplay';

export type TimelineEntry = Pick<Message, 'message_id' | 'created_at' | 'role' | 'user_message_id'> & { bookmarked?: boolean; response_id?: string };
export type TimelinePreview = { user: Message; assistant: Message | null; pending: boolean };
const markdown = new MarkdownIt({ html: false, linkify: false });

/** Associate private bookmarks without loading any message bodies. */
export function bookmarkedTimelineExchanges(entries: TimelineEntry[], bookmarks: ReadonlySet<string>): Set<string> {
  return buildTimelineExchangeIndex(entries, bookmarks).bookmarkedExchanges;
}

/** One exchange per question, irrespective of internal activity/tool rows. */
export function buildTimelineExchangeIndex(entries: TimelineEntry[], bookmarks: ReadonlySet<string>) {
  const questions = entries.filter(entry => entry.role === 'user');
  const users = new Set(questions.map(entry => entry.message_id));
  const explicit = new Map<string, string>();
  const legacy = new Map<string, string>();
  const assistantUsers = new Map<string, string>();
  const result = new Set<string>();
  const assistantBookmarks = new Set<string>();
  const legacyAliases = new Map<string, string[]>();
  let previousUser: string | null = null;
  for (const entry of entries) {
    if (entry.role === 'user') previousUser = entry.message_id;
    if (entry.role !== 'assistant') continue;
    const target = entry.user_message_id || previousUser;
    if (!target || !users.has(target)) continue;
    assistantUsers.set(entry.message_id, target);
    const responses = entry.user_message_id ? explicit : legacy;
    if (!responses.has(target)) responses.set(target, entry.message_id);
    if (bookmarks.has(entry.message_id)) { result.add(target); assistantBookmarks.add(entry.message_id); }
  }
  const exchanges = questions.map(question => {
    const responseId = explicit.get(question.message_id) ?? legacy.get(question.message_id);
    if (responseId) {
      legacyAliases.set(responseId, [question.message_id]);
      if (bookmarks.has(question.message_id)) { result.add(question.message_id); assistantBookmarks.add(responseId); }
    }
    return { ...question, response_id: responseId, bookmarked: result.has(question.message_id) };
  });
  return { entries: exchanges, answeredCount: explicit.size + [...legacy.keys()].filter(id => !explicit.has(id)).length,
    assistantBookmarks, legacyAliases, assistantUsers, bookmarkedExchanges: result };
}

export function mergeTimelineEntries(...pages: TimelineEntry[][]): TimelineEntry[] {
  const byId = new Map<string, TimelineEntry>();
  for (const page of pages) for (const row of page) byId.set(row.message_id, {
    message_id: row.message_id, created_at: row.created_at, role: row.role, user_message_id: row.user_message_id,
  });
  return [...byId.values()].sort((a, b) => a.created_at - b.created_at || a.message_id.localeCompare(b.message_id));
}

export function timelineResponseId(entries: TimelineEntry[], id: string): string | null {
  const index = entries.findIndex(entry => entry.message_id === id && entry.role === 'user');
  if (index < 0) return null;
  const linked = entries.find(entry => entry.role === 'assistant' && entry.user_message_id === id);
  if (linked) return linked.message_id;
  for (let i = index + 1; i < entries.length && entries[i].role !== 'user'; i++) {
    if (entries[i].role === 'assistant' && !entries[i].user_message_id) return entries[i].message_id;
  }
  return null;
}

export function pairTimelineExchange(messages: Message[], id: string, pendingUserId?: string): TimelinePreview {
  const user = messages.find(message => message.message_id === id && message.role === 'user');
  if (!user) throw new Error('Timeline exchange unavailable');
  if (user.encrypted_content && !user.content) throw new Error('Timeline message could not be decrypted');
  const responseId = timelineResponseId(messages, id);
  const assistant = messages.find(message => message.message_id === responseId) ?? null;
  return { user, assistant, pending: !assistant && pendingUserId === id };
}

export function timelinePreviewText(message: Message): string {
  const parts: string[] = [];
  let remaining = 400;
  if (typeof message.content === 'string') {
    // Previews need readable text, not hydration or application-store imports.
    const tokens = markdown.parse(voiceTranscriptDisplayText(message.content.slice(0, 16000), message.role), {});
    const walk = (items: typeof tokens): void => {
      for (const token of items) {
        if (remaining-- <= 0) return;
        if (token.children) walk(token.children);
        else if (['text', 'code_inline', 'image'].includes(token.type)) parts.push(token.content);
        else if (['softbreak', 'hardbreak'].includes(token.type)) parts.push('\n');
        else if (['fence', 'code_block'].includes(token.type)) {
          // Never surface serialized embed identifiers or result payloads.
          if (!/^\s*\{[\s\S]*"(?:embed_id|app_id|type)"\s*:/.test(token.content)) parts.push(token.content);
        }
        if (token.block && token.nesting === -1) parts.push('\n');
      }
    };
    walk(tokens);
    return parts.join('').replace(/\n{3,}/g, '\n\n').trim().slice(0, 800);
  }
  function visit(value: unknown): void {
    if (!value || typeof value !== 'object' || remaining-- <= 0) return;
    const node = value as { type?: string; text?: string; content?: unknown[] };
    if (node.type === 'text' && typeof node.text === 'string') parts.push(node.text);
    if (Array.isArray(node.content)) node.content.forEach(visit);
    if (['paragraph', 'heading', 'listItem', 'hardBreak'].includes(node.type ?? '')) parts.push('\n');
  }
  visit(message.content);
  return parts.join('').replace(/\n{3,}/g, '\n\n').trim().slice(0, 800);
}
