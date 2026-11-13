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
