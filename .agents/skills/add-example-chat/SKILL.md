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

Stage all changed files and deploy via `sessions.py deploy`:

```bash
git add \
  frontend/packages/ui/src/demo_chats/data/example_chats/{slug}.ts \
  frontend/packages/ui/src/demo_chats/exampleChatStore.ts \
  frontend/packages/ui/src/i18n/sources/example_chats/{snake_name}.yml \
  frontend/packages/ui/src/i18n/locales/
```

Then inject tracked files and deploy:
```bash
python3 -c "
import sys; sys.path.insert(0, 'scripts')
from sessions import _load_sessions, _save_sessions
import subprocess
data = _load_sessions()
s = data['sessions']['{SESSION_ID}']
result = subprocess.run(['git', 'diff', '--cached', '--name-only'], capture_output=True, text=True)
s['modified_files'] = [f for f in result.stdout.strip().split('\n') if f]
_save_sessions(data)
"

python3 scripts/sessions.py deploy \
  --session {SESSION_ID} \
  --title "feat: add example chat - {title}" \
  --message "New example chat from shared link. {n} messages, {m} embeds. All content behind i18n keys with 21 language translations." \
  --end --no-verify --skip-tests "New example chat content"
```

**IMPORTANT:** Always use `sessions.py deploy` — never raw `git commit`.

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
