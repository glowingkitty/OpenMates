---
name: openmates:add-example-chat
description: Create a new hardcoded example chat from a shared chat URL with encryption key
user-invocable: true
argument-hint: "<share-url-with-key>"
---

## Overview

Creates a new example chat from a shared chat link (with encryption key in the URL fragment).
Extracts the full chat content, generates TypeScript data + i18n YAML with 21-language translations,
registers it in the example chat store, builds translations, and prepares for deploy.

## Input

The user provides a share URL like:
```
https://app.dev.openmates.org/share/chat/{uuid}#key={encrypted-blob}
```

For new social videos that need a chat-based product demo, prefer creating **three candidate chats** with slight prompt variations first, then choose the strongest one for the video's intended highlight. Keep the winner, convert it to a permanent example chat, and delete/unshare the two weaker candidates when they are no longer needed.

## Fast Path

Use the scaffold script whenever possible. It extracts the shared chat, creates the TypeScript example-chat data file, creates the i18n source YAML, registers the chat in the store, strips private embed fields such as `vault_key_id` and `user_id`, and preserves existing order when `--force` is used.

```bash
node scripts/create-example-chat-from-share.mjs "<SHARE_URL>" \
  --slug "<seo-friendly-slug>" \
  --title "<Public Example Chat Title>" \
  --summary "<One-sentence public summary>" \
  --icon "<icon-name>" \
  --category "<mate-category>" \
  --keywords "keyword 1,keyword 2,keyword 3" \
  --api-key "$OPENMATES_API_KEY" \
  --force
```

For pricing transparency, pass an API key for the source account when available.
The scaffold script fetches `/v1/settings/usage/chat-entries` for the source
chat and stores the summed AI + app-skill credits on each assistant response.
If API access is not available, export the same endpoint response to JSON and
pass `--usage-json /path/to/usage.json`. The script prints `priced responses:`;
do not assume pricing was captured unless that count is non-zero for examples
that should have billable assistant responses.

After scaffolding:

```bash
set -a && source .env && set +a
for lang in de zh es fr pt ru ja ko it tr vi id pl nl ar hi th cs sv he; do
  python3 scripts/auto_translate.py --lang "$lang" --file "example_chats/<snake_name>.yml" || exit 1
done
cd frontend/packages/ui && npm run build:translations && npm run validate:locales
```

If the translation tool skips a long assistant message, retry the missing locales only. If it still skips, manually add just the missing locale blocks while preserving JSON code blocks, embed links, wiki links, and source quote link targets unchanged.

## Candidate Flow

Use this when creating a permanent example chat for a new social video. The goal is to get a real chat that cleanly demonstrates the product moment the video will highlight, such as source-backed research, app auto-selection, fullscreen embeds, maps, web/news results, file analysis, or another chat-based feature.

1. Write three natural user prompts with slight variations that all satisfy the social video's product and story requirement. Do not mention internal app-skill names unless the user explicitly wants to demonstrate manual app selection.
2. Create and share three real chats through the OpenMates CLI or app. Prefer CLI for repeatability when it supports the needed flow.
3. Inspect each candidate for the required product behavior and for video usefulness. For example, check whether the answer has a clear focal moment, enough but not too much text, relevant embeds, and a UI state that can be recorded cleanly.
4. Choose the strongest candidate based on content quality, brevity, visual usefulness for recording, and exact match to the social video's intended hook and payoff.
5. Convert only the winner with `scripts/create-example-chat-from-share.mjs`.
6. Delete, unshare, or otherwise clean up the two unused candidate chats if they were created only for this workflow.

## Steps

### 1. Extract chat content

Run the extraction script to decrypt the shared chat:

```bash
node scripts/extract-shared-chat.mjs "<SHARE_URL>" 2>/dev/null | python3 -c "
import sys, json
text = sys.stdin.read()
start = text.find('DECRYPTED CHAT DATA')
json_start = text.find('{', start)
data = json.loads(text[json_start:])
with open('/tmp/example-chat-extract.json', 'w') as f:
    json.dump(data, f, indent=2)
print(f'Title: {data[\"title\"]}')
print(f'Messages: {len(data[\"messages\"])}')
print(f'Embeds: {len(data[\"embeds\"])} ({sum(1 for e in data[\"embeds\"] if e.get(\"content\"))} decrypted)')
for i, msg in enumerate(data['messages']):
    print(f'  Msg {i} ({msg[\"role\"]}): {msg[\"content\"][:120]}...')
"
```

### 2. Determine slug and variable name

Ask the user for a natural-language slug if not obvious from the title. Examples:
- "Gigantic airplanes for transporting rocket parts" → `gigantic-airplanes-transporting-rocket-parts`
- "Artemis II Mission Highlights" → `artemis-ii-mission-highlights`

The slug should be SEO-friendly: lowercase, hyphens, no special chars, descriptive.

Derive the TypeScript variable name from the slug: `giganticAirplanesChat`, `artemisIIMissionChat`, etc.
The chat_id prefix is always `example-`: e.g. `example-gigantic-airplanes`.
The i18n key prefix is `example_chats.{snake_case_name}`.

### 3. Generate TypeScript data file

Prefer the fast-path scaffold script above. Only create the files manually if the script cannot handle the source chat.

Create: `frontend/packages/ui/src/demo_chats/data/example_chats/{slug}.ts`

Structure:
```typescript
import type { ExampleChat } from "../../types";

export const {varName}: ExampleChat = {
  chat_id: "example-{short-id}",
  slug: "{slug}",
  title: "example_chats.{snake_name}.title",
  summary: "example_chats.{snake_name}.summary",
  icon: "{icon}",          // from extracted data
  category: "{category}",  // from extracted data
  keywords: [...],          // SEO keywords (English, not translated)
  follow_up_suggestions: [
    "example_chats.{snake_name}.follow_up_1",
    ...
  ],
  messages: [
    {
      id: "{message_id}",
      role: "user",
      content: "example_chats.{snake_name}.user_message_1",  // i18n key
      created_at: {timestamp},
      category: "{category}",  // if present
    },
    {
      id: "{message_id}",
      role: "assistant",
      content: "example_chats.{snake_name}.assistant_message_2",  // i18n key
      created_at: {timestamp},
      category: "{category}",
      model_name: "{model}",
    },
    ...
  ],
  embeds: [
    // Copy all embeds from extracted data — content stays as TOON strings (not translated)
    {
      embed_id: "...",
      type: "...",
      content: `...`,        // TOON-encoded, English only
      parent_embed_id: null,
      embed_ids: null,
    },
    ...
  ],
  metadata: {
    featured: true,
    order: {next_order_number},
  },
};
```

**Rules:**
- ALL message content fields use i18n keys (both user AND assistant)
- Embeds stay as-is (TOON content, English only, not translated)
- Keywords are English only (SEO)

### 4. Generate i18n YAML source file

Prefer `scripts/create-example-chat-from-share.mjs` plus `scripts/auto_translate.py`. Only create translations manually when the automation fails for a specific locale/key.

Create: `frontend/packages/ui/src/i18n/sources/example_chats/{snake_name}.yml`

For each key, provide translations in ALL 21 languages:
`en, de, zh, es, fr, pt, ru, ja, ko, it, tr, vi, id, pl, nl, ar, hi, th, cs, sv, he`

**Translation rules for assistant messages:**
- JSON code blocks (```json ... ```) — IDENTICAL in all languages, do NOT translate
- Embed references `[!](embed:xxx)` — IDENTICAL in all languages
- Markdown links `[text](url)` — translate text, keep URL
- Technical proper nouns — keep as-is
- Follow-up tags like `[ai]`, `[web-search]` — keep tag, translate text after it

Use YAML block scalar `|` for multiline content (assistant messages).

**TIP:** Use 3 parallel subagents (one per language group) to speed up translation:
- Agent 1: de, zh, es, fr, pt, ru, ja
- Agent 2: ko, it, tr, vi, id, pl, nl
- Agent 3: ar, hi, th, cs, sv, he

### 5. Register in exampleChatStore.ts

Add import and array entry in `frontend/packages/ui/src/demo_chats/exampleChatStore.ts`:

```typescript
import { {varName} } from "./data/example_chats/{slug}";

const ALL_EXAMPLE_CHATS: ExampleChat[] = [
  ...,
  {varName},
].sort((a, b) => a.metadata.order - b.metadata.order);
```

### 6. Build translations

```bash
cd frontend/packages/ui && npm run build:translations
```

Verify the new keys appear in `en.json`:
```bash
python3 -c "
import json
with open('src/i18n/locales/en.json') as f:
    data = json.load(f)
ec = data.get('example_chats', {}).get('{snake_name}', {})
print(f'Keys: {list(ec.keys())}')
"
```

### 7. Deploy

Track only intended files and deploy via `sessions.py deploy`:

```bash
python3 scripts/sessions.py start --mode feature --tags frontend,i18n,feature

python3 scripts/sessions.py track --session {SESSION_ID} --file \
  scripts/create-example-chat-from-share.mjs \
  .agents/skills/add-example-chat/SKILL.md \
  frontend/packages/ui/src/demo_chats/exampleChatStore.ts \
  frontend/packages/ui/src/demo_chats/data/example_chats/{slug}.ts \
  frontend/packages/ui/src/i18n/sources/example_chats/{snake_name}.yml

python3 scripts/sessions.py prepare-deploy --session {SESSION_ID}

python3 scripts/sessions.py deploy \
  --session {SESSION_ID} \
  --title "feat: add example chat - {title}" \
  --message "New example chat from shared link. {n} messages, {m} embeds. All content behind i18n keys with 21 language translations." \
  --skip-tests "OpenMates E2E specs must run against deployed dev per repo policy; targeted syntax, translation build, and locale validation passed pre-deploy." \
  --end
```

**IMPORTANT:** Always use `sessions.py deploy` — never raw `git commit`, never `git add .`, and do not use `--no-verify` unless a pre-existing hook bug is confirmed and documented.

After deploy, run related Playwright specs against deployed dev:

```bash
python3 scripts/run_tests.py --suite playwright --spec example-chats-load.spec.ts --environment development --force
python3 scripts/run_tests.py --suite playwright --spec example-chat-clone.spec.ts --environment development --force
```

If the example is for a marketing video, hand off the final slug and deployed example URL to the marketing repo's Remotion workflow. The video should use the permanent example chat rather than a temporary shared chat whenever possible.

## File locations

| File | Purpose |
|------|---------|
| `scripts/extract-shared-chat.mjs` | Decrypts shared chat from URL |
| `frontend/packages/ui/src/demo_chats/data/example_chats/` | TypeScript data files |
| `frontend/packages/ui/src/demo_chats/exampleChatStore.ts` | Central registry |
| `frontend/packages/ui/src/demo_chats/types.ts` | ExampleChat type definition |
| `frontend/packages/ui/src/i18n/sources/example_chats/` | YAML translation sources |
| `frontend/packages/ui/src/i18n/locales/` | Generated JSON locale files |

## SEO

Each example chat automatically gets:
- `/example/{slug}` SEO page (prerendered at build time)
- Sitemap entry via `sitemap.xml/+server.ts`
- JSON-LD structured data, OG tags, keywords meta
