import { existsSync, readFileSync, readdirSync } from 'node:fs';
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

/** Inspect each recorded embed separately, so one failure cannot borrow another embed's result. */
export function hasCapabilityEvidence(source, app, assistantMessages = []) {
  const { type, id } = app.capability;
  if (!['skill', 'focus', 'artifact'].includes(type)) return false;
  // Some generated examples build their embed list from named arrays and spread it.
  const embeds = source.split(/\n\s*metadata:\s*\{/)[0];
  const records = embeds.split(/\n\s*["']?embed_id["']?\s*:\s*["']/).slice(1);
  const escapeRegExp = (value) => value.replace(/[.*+?^$()|[\]{}\\]/g, '\\$&');
  const field = (name, value, text) => new RegExp(`(?:^|\\n)\\s*["']?${name}["']?:\\s*["']?${escapeRegExp(value)}(?:["']|\\s|$)`, 'm').test(text);
  const substantive = (text, names) => {
    const payload = new RegExp(`(?:^|\\n)\\s*(?:${names}):\\s*([^\\n]*)`, 'gim');
    return [...text.matchAll(payload)].some((match) => {
      const value = match[1].trim().replace(/^["'`]+|["'`}\],;\s]+$/g, '').trim();
      return value !== '' && value !== '[]' && value !== '{}' && value !== 'null' && value !== 'unknown';
    });
  };
  const normalizedRecords = records.map((record) => record.replaceAll('\\n', '\n').replaceAll('\\"', '"').replaceAll("\\'", "'").replace(/(?:["']content["']|\bcontent):\s*["'`]/, '\n'));
  return normalizedRecords.some((normalized) => {
    if (!field('app_id', app.id, normalized)) return false;
    if (/(?:^|\n)\s*status:\s*(?:error|failed|failure|pending|running|started)\b/im.test(normalized)) return false;
    if (/(?:^|\n)\s*provider_status:\s*(?:error|failed|failure|unknown)\b/im.test(normalized)) return false;
    if (/(?:^|\n)\s*availability:\s*unknown\b/im.test(normalized)) return false;
    if (substantive(normalized, 'check_error')) return false;
    if (/(?:^|\n)\s*result_count:\s*0\b/im.test(normalized)) return false;
    if (type === 'skill') {
      if (!field('skill_id', id, normalized)) return false;
      // A finished invocation needs a positive count or useful output. Some result
      // embeds omit status, so inspect their own content with the same rule.
      return /(?:^|\n)\s*result_count:\s*[1-9]\d*\b/m.test(normalized) ||
        /(?:^|\n)\s*(?:items|preview_results)\[[1-9]\d*\][^\n]*:/m.test(normalized) ||
        substantive(normalized, 'title|name|summary|description|text|url|previewAudioUrl|previewImageUrl|price|price_before_taxes|price_after_taxes|content|value|answer|data');
    }
    if (type === 'focus') {
      if (!field('focus_id', `${app.id}-${id}`, normalized)) return false;
      if (field('status', 'finished', normalized)) return true;
      // Focus activation has its own saved lifecycle; it does not finish like a skill.
      return field('type', 'focus-mode-activation', normalized) &&
        field('status', 'activated', normalized) && assistantMessages.some(hasNaturalOpening);
    }
    if (!field('status', 'finished', normalized)) return false;
    const aliases = app.evidence_types?.length ? app.evidence_types : [id];
    if (!aliases.some((alias) => field('type', alias, normalized) || field('skill_id', alias, normalized))) return false;
    if (/(?:^|\n)\s*(?:file_refs|nodes|blocks)\[[1-9]\d*\][^\n]*:/m.test(normalized)) return true;
    return substantive(normalized, 'filename|text|body|content|model|docx_model|source_json|html_source|plot_spec|url|file_url|image_url|audio_url|html|markdown|svg');
  });
}

/** Check the whole public conversation, including skills beyond its landing card. */
export function validatePublishedExampleSkills(root) {
  const unavailable = new Set();
  const appsRoot = resolve(root, 'backend/apps');
  for (const app of readdirSync(appsRoot, { withFileTypes: true }).filter((entry) => entry.isDirectory())) {
    const path = resolve(appsRoot, app.name, 'app.yml');
    if (!existsSync(path)) continue;
    const metadata = parse(readFileSync(path, 'utf8'));
    for (const skill of metadata?.skills ?? []) {
      if (skill.provider_required === true && !skill.providers?.length) unavailable.add(`${app.name}.${skill.id}`);
    }
  }
  const registry = readFileSync(resolve(root, 'frontend/packages/ui/src/demo_chats/exampleChatData.ts'), 'utf8');
  const published = registry.match(/export const ALL_EXAMPLE_CHATS[^=]*=\s*\[([\s\S]*?)\]/)?.[1];
  if (!published) throw new Error('Public example registry is missing');
  const names = new Set(published.match(/\b\w+\b/g));
  for (const match of registry.matchAll(/import \{ (\w+) \} from ["']\.\/data\/example_chats\/([^"']+)["']/g)) {
    if (!names.has(match[1])) continue;
    const source = readFileSync(resolve(root, 'frontend/packages/ui/src/demo_chats/data/example_chats', `${match[2]}.ts`), 'utf8');
    const normalized = source.replaceAll('\\n', '\n').replaceAll('\\"', '"').replace(/(?:["']content["']|\bcontent):\s*["'`]/g, '\n');
    for (const record of normalized.split(/\n\s*["']?embed_id["']?\s*:/).slice(1)) {
      const appId = record.match(/(?:^|[\n{,])\s*["']?app_id["']?\s*:\s*["']?([\w-]+)/)?.[1];
      const skillId = record.match(/(?:^|[\n{,])\s*["']?skill_id["']?\s*:\s*["']?([\w-]+)/)?.[1];
      if (appId && skillId && unavailable.has(`${appId}.${skillId}`)) {
        throw new Error(`Public example ${match[2]} uses unavailable skill ${appId}.${skillId}`);
      }
    }
  }
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
    const locale = resolve(root, 'frontend/packages/ui/src/i18n/sources/example_chats', `${slug.replaceAll('-', '_')}.yml`);
    const messages = parse(readFileSync(locale, 'utf8'));
    const messageRecords = example.source.split(/\n\s*["']?role["']?\s*:\s*["']/).slice(1);
    const assistantMessages = messageRecords
      .filter((record) => /^assistant["']/.test(record))
      .map((record) => record.match(/\n\s*["']?content["']?\s*:\s*["'](example_chats\.[^."']+\.([^."']+))["']/)?.[2])
      .map((key) => key ? messages?.[key]?.en : undefined);
    if (!hasCapabilityEvidence(example.source, app, assistantMessages)) {
      throw new Error(`Landing example does not demonstrate ${app.id} ${app.capability.type}:${app.capability.id}: ${chatId}`);
    }
    const firstUser = messageRecords.find((record) => /^user["']/.test(record));
    const openingKey = firstUser?.match(/\n\s*["']?content["']?\s*:\s*["']example_chats\.[^."']+\.([^."']+)["']/)?.[1];
    const opening = messages?.[openingKey ?? 'message_1']?.en;
    if (!hasNaturalOpening(opening)) {
      throw new Error(`Landing example must have a natural opening: ${chatId}`);
    }
  }
}
