import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'yaml';

/** Uploaded files may accompany a natural request, but cannot replace one. */
export function hasNaturalOpening(opening) {
  if (typeof opening !== 'string') return false;
  // A user-selected mate may prefix an otherwise natural CLI request.
  const request = opening.replace(/^@mate:[a-z][\w-]*\s+/i, '');
  if (/(^|\s)@[a-z][\w-]*:/i.test(request)) return false;
  const prose = request
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\[[^\]]*\]\(embed:[^)]+\)/g, '')
    .trim();
  return (prose.match(/\p{L}+/gu) ?? []).length >= 3;
}

/** Generated example source stores embed content as escaped strings. */
export function hasCapabilityEvidence(source, app) {
  const { type, id } = app.capability;
  if (type === 'app') return true;
  const normalized = source.replaceAll('\\n', '\n').replaceAll('\\"', '"');
  const escapeRegExp = (value) => value.replace(/[.*+?^$()|[\]{}\\]/g, '\\$&');
  const appId = escapeRegExp(app.id);
  const capabilityId = escapeRegExp(id);
  const hasApp = new RegExp(`\\bapp_id:\\s*"?${appId}"?\\b|["']app_id["']:\\s*["']${appId}["']`).test(normalized);
  if (!hasApp) return false;
  if (type === 'skill') return new RegExp(`\\bskill_id:\\s*"?${capabilityId}"?\\b|["']skill_id["']:\\s*["']${capabilityId}["']`).test(normalized);
  if (type === 'focus') return new RegExp(`\\bfocus_id:\\s*"?${appId}-${capabilityId}"?\\b|["']active_focus_id["']:\\s*["']${appId}-${capabilityId}["']`).test(normalized);
  return (app.evidence_types?.length ? app.evidence_types : [id]).some((sourceType) => {
    const alias = escapeRegExp(sourceType);
    return new RegExp(`\\b(?:type|skill_id):\\s*"?${alias}"?\\b|["'](?:type|skill_id)["']:\\s*["']${alias}["']`).test(normalized);
  });
}

/** Keep metadata links tied to registered, natural-opening source chats. */
export function validateLandingAppExamples(root, apps) {
  const examplesRoot = resolve(root, 'frontend/packages/ui/src/demo_chats/data/example_chats');
  const registry = readFileSync(resolve(root, 'frontend/packages/ui/src/demo_chats/exampleChatData.ts'), 'utf8');
  const byChatId = new Map();
  for (const filename of readdirSync(examplesRoot).filter((name) => name.endsWith('.ts'))) {
    const source = readFileSync(resolve(examplesRoot, filename), 'utf8');
    const chatId = source.match(/\bchat_id:\s*["']([^"']+)["']/)?.[1];
    if (chatId) byChatId.set(chatId, { filename, source });
  }

  const usedExamples = new Set();
  for (const app of apps) {
    const { id: appId, example_chat_id: chatId } = app;
    if (!chatId) throw new Error(`Public landing apps need matching real examples: ${appId}`);
    if (usedExamples.has(chatId)) throw new Error(`Duplicate landing example chat ID: ${chatId}`);
    usedExamples.add(chatId);
    const example = byChatId.get(chatId);
    if (!example) throw new Error(`Unknown landing example chat ID: ${chatId}`);
    const slug = example.filename.replace(/\.ts$/, '');
    if (!registry.includes(`./data/example_chats/${slug}`)) throw new Error(`Unregistered landing example: ${chatId}`);
    if (!example.source.slice(0, 700).includes('Extracted from shared chat')) {
      throw new Error(`Landing example lacks shared-chat provenance: ${chatId}`);
    }
    if (!hasCapabilityEvidence(example.source, app)) {
      throw new Error(`Landing example does not demonstrate ${app.id} ${app.capability.type}:${app.capability.id}: ${chatId}`);
    }
    const locale = resolve(root, 'frontend/packages/ui/src/i18n/sources/example_chats', `${slug.replaceAll('-', '_')}.yml`);
    const opening = parse(readFileSync(locale, 'utf8'))?.message_1?.en;
    if (!hasNaturalOpening(opening)) {
      throw new Error(`Landing example must have a natural opening: ${chatId}`);
    }
    if (app.capability.type === 'app' && !opening.includes(app.source_evidence.request_excerpt)) {
      throw new Error(`Reviewed app-level landing source evidence does not match opening: ${app.id}`);
    }
  }
}
