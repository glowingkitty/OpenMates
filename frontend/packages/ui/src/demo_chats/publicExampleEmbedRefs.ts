// Synchronous public metadata for parsing; keep browser services and component
// registries out of this module and public UUIDs out of the private ref index.
import { ALL_EXAMPLE_CHATS, INTERNAL_EXAMPLE_CHATS } from './exampleChatData';
import type { EmbedRefIndexEntry } from '../services/embedRefIndex';

function field(content: string, key: string): string | null {
  if (content.trimStart().startsWith('{')) {
    try {
      const value: unknown = JSON.parse(content)[key];
      return typeof value === 'string' ? value : null;
    } catch { return null; }
  }
  return content.match(new RegExp(`(?:^|\\n)${key}:\\s*"?([^\\n"]+)"?`))?.[1]?.trim() ?? null;
}

export function resolveExampleChatEmbedRef(ref: string, chatId: string | null | undefined): EmbedRefIndexEntry | null {
  const group = [...ALL_EXAMPLE_CHATS, ...INTERNAL_EXAMPLE_CHATS].find(example =>
    example.chat_id === chatId || example.sub_chats?.some(child => child.chat_id === chatId));
  if (!group) return null;
  for (const embed of [...group.embeds, ...(group.sub_chats ?? []).flatMap(child => child.embeds)]) {
    if (!embed.content || !embed.embed_id) continue;
    const embedId = embed.embed_id.replace(/^embed:/, '');
    if (ref.replace(/^embed:/, '') !== embedId && field(embed.content, 'embed_ref') !== ref) continue;
    const appId = field(embed.content, 'app_id');
    const skillId = field(embed.content, 'skill_id');
    // Historical result children can retain the invocation server type. Their
    // parent relationship identifies output that must stay inline.
    const type = embed.parent_embed_id
      && ['app_skill_use', 'app-skill-use'].includes(embed.type)
      ? field(embed.content, 'type')?.replace(/^app[_-]skill[_-]use$/, 'app-skill-result') ?? 'app-skill-result'
      : embed.type;
    return { embedId, appId, skillId, type };
  }
  return null;
}
