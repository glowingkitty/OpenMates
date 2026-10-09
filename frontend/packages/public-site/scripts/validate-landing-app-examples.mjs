import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'yaml';

/** Uploaded files may accompany a natural request, but cannot replace one. */
export function hasNaturalOpening(opening) {
  if (typeof opening !== 'string' || /(^|\s)@[a-z][\w-]*:/i.test(opening)) return false;
  const prose = opening
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\[[^\]]*\]\(embed:[^)]+\)/g, '')
    .trim();
  return (prose.match(/\p{L}+/gu) ?? []).length >= 3;
}

/** Keep landing links tied to registered, natural-opening source chats. */
export function validateLandingAppExamples(root, eligibleIds) {
  const content = readFileSync(resolve(root, 'frontend/packages/public-site/src/components/landing/landingPageContent.ts'), 'utf8');
  const entries = content.match(/export const landingAppExamples: Record<string, string> = \{([\s\S]*?)\n\};/)?.[1];
  if (!entries) throw new Error('Landing example mapping is missing');

  const examplesRoot = resolve(root, 'frontend/packages/ui/src/demo_chats/data/example_chats');
  const registry = readFileSync(resolve(root, 'frontend/packages/ui/src/demo_chats/exampleChatData.ts'), 'utf8');
  const byChatId = new Map();
  for (const filename of readdirSync(examplesRoot).filter((name) => name.endsWith('.ts'))) {
    const source = readFileSync(resolve(examplesRoot, filename), 'utf8');
    const chatId = source.match(/\bchat_id:\s*["']([^"']+)["']/)?.[1];
    if (chatId) byChatId.set(chatId, { filename, source });
  }

  const mappings = [...entries.matchAll(/^\s+([a-z][a-z0-9_]*):\s*'(example-[\w-]+)',?\s*$/gm)];
  if (mappings.length !== entries.split('\n').filter((line) => line.trim() && !line.trim().startsWith('//')).length) {
    throw new Error('Landing example mapping contains an unrecognized entry');
  }
  const seenApps = new Set();
  for (const [, appId, chatId] of mappings) {
    if (!eligibleIds.has(appId) || seenApps.has(appId)) throw new Error(`Invalid landing example app: ${appId}`);
    seenApps.add(appId);
    const example = byChatId.get(chatId);
    if (!example) throw new Error(`Unknown landing example chat ID: ${chatId}`);
    const slug = example.filename.replace(/\.ts$/, '');
    if (!registry.includes(`./data/example_chats/${slug}`)) throw new Error(`Unregistered landing example: ${chatId}`);
    if (!example.source.slice(0, 700).includes('Extracted from shared chat')) {
      throw new Error(`Landing example lacks shared-chat provenance: ${chatId}`);
    }
    const locale = resolve(root, 'frontend/packages/ui/src/i18n/sources/example_chats', `${slug.replaceAll('-', '_')}.yml`);
    const opening = parse(readFileSync(locale, 'utf8'))?.message_1?.en;
    if (!hasNaturalOpening(opening)) {
      throw new Error(`Landing example must have a natural opening: ${chatId}`);
    }
  }
  const missing = [...eligibleIds].filter((appId) => !seenApps.has(appId));
  if (missing.length) throw new Error(`Public landing apps need matching real examples: ${missing.join(', ')}`);
}
