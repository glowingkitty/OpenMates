#!/usr/bin/env node

/**
 * Deterministically scaffold a production example chat from a shared chat URL.
 *
 * This wraps scripts/extract-shared-chat.mjs, preserves extracted embeds exactly,
 * writes the example chat data file, writes English i18n source entries copied to
 * all supported languages, and registers the chat in exampleChatStore.ts.
 *
 * Usage:
 *   node scripts/create-example-chat-from-share.mjs "https://app.dev.openmates.org/share/chat/...#key=..." \
 *     --slug right-to-repair-laws-eu-us \
 *     --keywords "right to repair,EU,United States,consumer rights" \
 *     --dry-run
 *
 * For local testing without fetching a share URL:
 *   node scripts/create-example-chat-from-share.mjs --from-json /tmp/example-chat-extract.json --slug my-chat --dry-run
 */

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const REPO_ROOT = path.resolve(path.dirname(__filename), '..');

const EXAMPLE_DATA_DIR = path.join(
  REPO_ROOT,
  'frontend/packages/ui/src/demo_chats/data/example_chats',
);
const I18N_SOURCE_DIR = path.join(
  REPO_ROOT,
  'frontend/packages/ui/src/i18n/sources/example_chats',
);
const STORE_PATH = path.join(
  REPO_ROOT,
  'frontend/packages/ui/src/demo_chats/exampleChatStore.ts',
);
const EXTRACT_SCRIPT = path.join(REPO_ROOT, 'scripts/extract-shared-chat.mjs');

const LANGUAGES = [
  'en',
  'de',
  'zh',
  'es',
  'fr',
  'pt',
  'ru',
  'ja',
  'ko',
  'it',
  'tr',
  'vi',
  'id',
  'pl',
  'nl',
  'ar',
  'hi',
  'th',
  'cs',
  'sv',
  'he',
];

const CANONICAL_CATEGORIES = new Set([
  'software_development',
  'business_development',
  'medical_health',
  'legal_law',
  'openmates_official',
  'maker_prototyping',
  'marketing_sales',
  'finance',
  'design',
  'electrical_engineering',
  'movies_tv',
  'history',
  'science',
  'life_coach_psychology',
  'cooking_food',
  'activism',
  'general_knowledge',
  'onboarding_support',
]);

const CATEGORY_ALIASES = new Map([
  ['research', 'general_knowledge'],
  ['development', 'software_development'],
  ['software development', 'software_development'],
  ['software_development', 'software_development'],
  ['business', 'business_development'],
  ['business development', 'business_development'],
  ['health', 'medical_health'],
  ['medical', 'medical_health'],
  ['medical health', 'medical_health'],
  ['legal', 'legal_law'],
  ['law', 'legal_law'],
  ['maker', 'maker_prototyping'],
  ['maker prototyping', 'maker_prototyping'],
  ['marketing', 'marketing_sales'],
  ['sales', 'marketing_sales'],
  ['marketing sales', 'marketing_sales'],
  ['video', 'movies_tv'],
  ['videos', 'movies_tv'],
  ['movies', 'movies_tv'],
  ['movies tv', 'movies_tv'],
  ['finance', 'finance'],
  ['design', 'design'],
  ['electrical', 'electrical_engineering'],
  ['electrical engineering', 'electrical_engineering'],
  ['history', 'history'],
  ['science', 'science'],
  ['psychology', 'life_coach_psychology'],
  ['life coach psychology', 'life_coach_psychology'],
  ['cooking', 'cooking_food'],
  ['food', 'cooking_food'],
  ['cooking food', 'cooking_food'],
  ['activism', 'activism'],
  ['travel', 'general_knowledge'],
  ['productivity', 'general_knowledge'],
  ['general', 'general_knowledge'],
  ['general knowledge', 'general_knowledge'],
  ['general_knowledge', 'general_knowledge'],
  ['support', 'onboarding_support'],
  ['onboarding support', 'onboarding_support'],
]);

function usage() {
  console.error(`Usage: node scripts/create-example-chat-from-share.mjs <share-url> --slug <slug> [options]

Options:
  --from-json <path>       Use already extracted chat JSON instead of a share URL
  --slug <slug>            SEO slug, lowercase hyphenated (required)
  --title <title>          Override extracted title
  --summary <summary>      Override extracted summary
  --icon <icon>            Override extracted icon
  --category <category>    Override extracted category
  --keywords <csv>         Comma-separated SEO keywords
  --featured <true|false>  Whether the example is featured (default: true)
  --dry-run                Print planned changes without writing files
  --force                  Overwrite existing generated files
`);
  process.exit(1);
}

function parseArgs(argv) {
  const args = {
    shareUrl: null,
    fromJson: null,
    slug: null,
    title: null,
    summary: null,
    icon: null,
    category: null,
    keywords: [],
    featured: true,
    dryRun: false,
    force: false,
  };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith('--') && !args.shareUrl) {
      args.shareUrl = arg;
      continue;
    }
    switch (arg) {
      case '--from-json':
        args.fromJson = argv[++i];
        break;
      case '--slug':
        args.slug = argv[++i];
        break;
      case '--title':
        args.title = argv[++i];
        break;
      case '--summary':
        args.summary = argv[++i];
        break;
      case '--icon':
        args.icon = argv[++i];
        break;
      case '--category':
        args.category = argv[++i];
        break;
      case '--keywords':
        args.keywords = (argv[++i] || '')
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean);
        break;
      case '--featured': {
        const value = argv[++i];
        args.featured = value !== 'false';
        break;
      }
      case '--dry-run':
        args.dryRun = true;
        break;
      case '--force':
        args.force = true;
        break;
      case '--help':
        usage();
        break;
      default:
        console.error(`Unknown argument: ${arg}`);
        usage();
    }
  }

  if (!args.slug || (!args.shareUrl && !args.fromJson)) {
    usage();
  }
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(args.slug)) {
    console.error(`Invalid slug "${args.slug}". Use lowercase letters, numbers, and hyphens.`);
    process.exit(1);
  }
  return args;
}

function loadExtractedChat(args) {
  if (args.fromJson) {
    return JSON.parse(readFileSync(path.resolve(args.fromJson), 'utf8'));
  }

  const output = execFileSync(process.execPath, [EXTRACT_SCRIPT, args.shareUrl], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    maxBuffer: 128 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  const marker = 'DECRYPTED CHAT DATA';
  const markerIndex = output.indexOf(marker);
  const jsonStart = output.indexOf('{', markerIndex);
  if (markerIndex === -1 || jsonStart === -1) {
    throw new Error('Could not find decrypted chat JSON in extractor output.');
  }
  return JSON.parse(output.slice(jsonStart));
}

function toSnake(slug) {
  return slug.replace(/-/g, '_');
}

function toPascal(slug) {
  return slug
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');
}

function toCamel(slug) {
  const pascal = toPascal(slug);
  return pascal.charAt(0).toLowerCase() + pascal.slice(1);
}

function shortChatId(slug) {
  const parts = slug.split('-');
  return parts.slice(0, Math.min(parts.length, 4)).join('-');
}

function normalizeTimestamp(value) {
  if (typeof value === 'number') return Math.floor(value);
  if (typeof value === 'string') {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return Math.floor(numeric);
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return Math.floor(parsed / 1000);
  }
  return Math.floor(Date.now() / 1000);
}

function extractEmbedRefsFromMessages(messages) {
  const refs = new Set();
  const pattern = /\(embed:([^)#]+)(?:#[^)]+)?\)/g;
  for (const message of messages) {
    let match;
    while ((match = pattern.exec(message.content || '')) !== null) {
      refs.add(match[1]);
    }
  }
  return refs;
}

function extractEmbedRefsFromEmbeds(embeds) {
  const refs = new Set();
  const pattern = /^embed_ref:\s*"?([^\n"]+)"?\s*$/m;
  for (const embed of embeds) {
    const match = String(embed.content || '').match(pattern);
    if (match) refs.add(match[1].trim());
  }
  return refs;
}

function sanitizeEmbedContent(content) {
  return String(content || '')
    .split('\n')
    .filter((line) => !/^(vault_key_id|user_id):\s*/.test(line))
    .join('\n');
}

function validateExtractedChat(chat) {
  const required = ['chat_id', 'messages', 'embeds'];
  for (const key of required) {
    if (!chat[key]) throw new Error(`Extracted chat is missing ${key}.`);
  }
  if (!Array.isArray(chat.messages) || chat.messages.length === 0) {
    throw new Error('Extracted chat has no messages.');
  }
  if (!Array.isArray(chat.embeds)) {
    throw new Error('Extracted chat embeds must be an array.');
  }

  const embedRefsInMessages = extractEmbedRefsFromMessages(chat.messages);
  const embedRefsInEmbeds = extractEmbedRefsFromEmbeds(chat.embeds);
  const missingRefs = [...embedRefsInMessages].filter((ref) => !embedRefsInEmbeds.has(ref));
  if (missingRefs.length > 0) {
    throw new Error(
      `Message content references embed refs not present in extracted embeds: ${missingRefs.join(', ')}`,
    );
  }
}

function readExistingOrder(slug) {
  const filePath = path.join(EXAMPLE_DATA_DIR, `${slug}.ts`);
  if (!existsSync(filePath)) return null;
  const source = readFileSync(filePath, 'utf8');
  const match = source.match(/order:\s*(\d+)/);
  return match ? Number(match[1]) : null;
}

function nextOrder(excludeSlug = null) {
  const store = readFileSync(STORE_PATH, 'utf8');
  const importMatches = [...store.matchAll(/import \{ (\w+) \} from "\.\/data\/example_chats\/([^";]+)";/g)];
  const orders = [];
  for (const [, , importPath] of importMatches) {
    if (excludeSlug && importPath === excludeSlug) continue;
    const filePath = path.join(EXAMPLE_DATA_DIR, `${importPath}.ts`);
    if (!existsSync(filePath)) continue;
    const source = readFileSync(filePath, 'utf8');
    const match = source.match(/order:\s*(\d+)/);
    if (match) orders.push(Number(match[1]));
  }
  return orders.length > 0 ? Math.max(...orders) + 1 : 1;
}

function tsString(value) {
  return JSON.stringify(value ?? '');
}

function tsArray(values) {
  return `[${values.map((value) => tsString(value)).join(', ')}]`;
}

function normalizeCategory(value) {
  if (!value) return 'general_knowledge';
  const trimmed = String(value).trim();
  if (CANONICAL_CATEGORIES.has(trimmed)) return trimmed;

  const normalized = trimmed.toLowerCase().replace(/[-_]+/g, ' ').replace(/\s+/g, ' ');
  const alias = CATEGORY_ALIASES.get(normalized);
  if (alias) return alias;

  throw new Error(
    `Invalid category "${value}". Use a canonical category ID: ${[...CANONICAL_CATEGORIES].sort().join(', ')}`,
  );
}

function formatTs(chat, metadata) {
  const varName = `${toCamel(metadata.slug)}Chat`;
  const messages = chat.messages.map((message, index) => ({
    id: message.message_id || message.id || `${metadata.chatId}-message-${index + 1}`,
    role: message.role,
    content: `example_chats.${metadata.snake}.message_${index + 1}`,
    created_at: normalizeTimestamp(message.created_at),
    category: message.category || undefined,
    model_name: message.model_name || undefined,
    pii_mappings: message.pii_mappings || undefined,
  }));
  const embeds = chat.embeds.map((embed) => ({
    embed_id: embed.embed_id,
    type: embed.type,
    content: sanitizeEmbedContent(embed.content),
    parent_embed_id: embed.parent_embed_id ?? null,
    embed_ids: embed.embed_ids ?? null,
  }));

  return `// frontend/packages/ui/src/demo_chats/data/example_chats/${metadata.slug}.ts
//
// Example chat: ${metadata.title}
// Extracted from shared chat ${chat.chat_id}
// Generated by scripts/create-example-chat-from-share.mjs

import type { ExampleChat } from "../../types";

export const ${varName}: ExampleChat = {
  chat_id: ${tsString(metadata.chatId)},
  slug: ${tsString(metadata.slug)},
  title: ${tsString(`example_chats.${metadata.snake}.title`)},
  summary: ${tsString(`example_chats.${metadata.snake}.summary`)},
  icon: ${tsString(metadata.icon)},
  category: ${tsString(metadata.category)},
  keywords: ${tsArray(metadata.keywords)},
  follow_up_suggestions: ${tsArray(metadata.followUps.map((_, i) => `example_chats.${metadata.snake}.follow_up_${i + 1}`))},
  messages: ${JSON.stringify(messages, null, 4)},
  embeds: ${JSON.stringify(embeds, null, 4)},
  metadata: {
    featured: ${metadata.featured},
    order: ${metadata.order},
  },
};
`;
}

function yamlScalar(value) {
  const text = String(value ?? '');
  if (text.includes('\n')) {
    return `|\n${text.split('\n').map((line) => `    ${line}`).join('\n')}`;
  }
  return JSON.stringify(text);
}

function yamlEntry(key, context, english) {
  const lines = [`${key}:`, `  context: ${JSON.stringify(context)}`];
  for (const lang of LANGUAGES) {
    const scalar = yamlScalar(english);
    if (scalar.startsWith('|\n')) {
      lines.push(`  ${lang}: ${scalar}`);
    } else {
      lines.push(`  ${lang}: ${scalar}`);
    }
  }
  lines.push('  verified_by_human: []');
  return `${lines.join('\n')}\n`;
}

function formatYaml(chat, metadata) {
  const entries = [];
  entries.push(yamlEntry('title', `Title of example chat: ${metadata.title}`, metadata.title));
  entries.push(yamlEntry('summary', `Summary of example chat: ${metadata.title}`, metadata.summary));
  chat.messages.forEach((message, index) => {
    entries.push(
      yamlEntry(
        `message_${index + 1}`,
        `${message.role} message ${index + 1} in example chat: ${metadata.title}. Keep markdown, JSON code blocks, embed links, source quote links, and placeholders unchanged.`,
        message.content || '',
      ),
    );
  });
  metadata.followUps.forEach((followUp, index) => {
    entries.push(yamlEntry(`follow_up_${index + 1}`, `Follow-up suggestion ${index + 1}`, followUp));
  });
  return `${entries.join('\n')}\n`;
}

function updateStoreSource(source, slug, varName) {
  const importLine = `import { ${varName} } from "./data/example_chats/${slug}";`;
  if (!source.includes(importLine)) {
    const importMatches = [...source.matchAll(/^import \{ \w+ \} from "\.\/data\/example_chats\/[^"]+";$/gm)];
    const lastImport = importMatches[importMatches.length - 1];
    if (!lastImport) throw new Error('Could not find example chat imports in exampleChatStore.ts.');
    source = `${source.slice(0, lastImport.index + lastImport[0].length)}\n${importLine}${source.slice(lastImport.index + lastImport[0].length)}`;
  }

  const entryLine = `  ${varName},`;
  if (!source.includes(entryLine)) {
    const arrayEnd = source.indexOf('].sort((a, b) => a.metadata.order - b.metadata.order);');
    if (arrayEnd === -1) throw new Error('Could not find ALL_EXAMPLE_CHATS array end.');
    source = `${source.slice(0, arrayEnd)}${entryLine}\n${source.slice(arrayEnd)}`;
  }
  return source;
}

function writeIfChanged(filePath, content, args) {
  const exists = existsSync(filePath);
  if (exists && !args.force) {
    const current = readFileSync(filePath, 'utf8');
    if (current !== content) {
      throw new Error(`${path.relative(REPO_ROOT, filePath)} already exists. Pass --force to overwrite.`);
    }
  }
  if (args.dryRun) return;
  writeFileSync(filePath, content);
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const chat = loadExtractedChat(args);
  validateExtractedChat(chat);

  const slug = args.slug;
  const metadata = {
    slug,
    snake: toSnake(slug),
    title: args.title || chat.title || slug,
    summary: args.summary || chat.summary || '',
    icon: args.icon || chat.icon || 'search',
    category: normalizeCategory(args.category || chat.category),
    keywords: args.keywords,
    featured: args.featured,
    followUps: Array.isArray(chat.follow_up_suggestions) ? chat.follow_up_suggestions : [],
    order: readExistingOrder(slug) ?? nextOrder(slug),
    chatId: `example-${shortChatId(slug)}`,
  };

  const dataPath = path.join(EXAMPLE_DATA_DIR, `${slug}.ts`);
  const yamlPath = path.join(I18N_SOURCE_DIR, `${metadata.snake}.yml`);
  const varName = `${toCamel(slug)}Chat`;
  const tsContent = formatTs(chat, metadata);
  const yamlContent = formatYaml(chat, metadata);
  const updatedStore = updateStoreSource(readFileSync(STORE_PATH, 'utf8'), slug, varName);

  console.log(`Example chat scaffold: ${metadata.title}`);
  console.log(`  chat_id: ${metadata.chatId}`);
  console.log(`  slug: ${metadata.slug}`);
  console.log(`  category: ${metadata.category}`);
  console.log(`  messages: ${chat.messages.length}`);
  console.log(`  embeds: ${chat.embeds.length}`);
  console.log(`  order: ${metadata.order}`);
  console.log(`  data: ${path.relative(REPO_ROOT, dataPath)}`);
  console.log(`  i18n: ${path.relative(REPO_ROOT, yamlPath)}`);
  console.log(`  store: ${path.relative(REPO_ROOT, STORE_PATH)}`);

  if (args.dryRun) {
    console.log('\nDry run: no files written.');
    return;
  }

  writeIfChanged(dataPath, tsContent, args);
  writeIfChanged(yamlPath, yamlContent, args);
  writeIfChanged(STORE_PATH, updatedStore, { ...args, force: true });
}

main();
