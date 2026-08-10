---
name: openmates:add-example-chat
description: Create a new hardcoded example chat from a real OpenMates CLI chat, then verify the deployed example page
user-invocable: true
argument-hint: "<prompt-or-share-url-with-key>"
---

## Overview

Creates a new public example chat from a real OpenMates CLI chat, not from
hand-authored fixtures. The default workflow is mandatory:

1. Create a real chat through the OpenMates CLI against the dev API.
2. Share that real chat and use its share URL with the encryption key fragment.
3. Scaffold the permanent example chat from the shared real chat.
4. Deploy the example chat.
5. Verify the deployed example page yourself before giving the user the link.

Extraction generates TypeScript data + i18n YAML with 21-language translations,
registers it in the example chat store, builds translations, and prepares for deploy.

## Input

Preferred input is the public demo prompt or product moment to demonstrate. If
the user provides only a share URL, first confirm it was produced from a real
OpenMates CLI chat in this workflow or recreate the chat through the CLI before
scaffolding.

Share URLs look like:
```
https://app.dev.openmates.org/share/chat/{uuid}#key={encrypted-blob}
```

For new social videos that need a chat-based product demo, prefer creating **three candidate chats** with slight prompt variations first, then choose the strongest one for the video's intended highlight. Keep the winner, convert it to a permanent example chat, and delete/unshare the two weaker candidates when they are no longer needed.

## Required Workflow

Do not skip these gates for new or replaced example chats:

1. **Create a real CLI chat first.** Use the OpenMates CLI against the dev API so the source transcript reflects real model, tool, app-skill, embed, and sharing behavior. Do not use mocked SDK calls, hand-authored transcripts, direct backend functions, fixture replay, or copied static output as the source of a public example chat.
2. **Inspect the real chat before scaffolding.** Confirm the source chat has the intended messages, app-skill output, embeds, and any fullscreen-worthy embed state. If it is weak, create another real CLI chat rather than editing the transcript into shape.
3. **Create the example chat from that real chat.** Share the selected CLI chat, then run `scripts/create-example-chat-from-share.mjs` on the resulting share URL with key fragment.
4. **Deploy before final verification.** Use `sessions.py deploy`; do not report the example URL from undeployed local files.
5. **Verify the deployed example page yourself.** Open the deployed `/example/{slug}` page and confirm messages render, embeds render, and every relevant embed fullscreen opens correctly. Use browser/Playwright automation where practical, and run the targeted example-chat specs after deploy.
6. **Only then give the user the link.** The final response must include the deployed example-chat URL only after self-verification passes. If verification fails, fix it or state the blocker instead of giving an unverified link.

When a specific CLI command is not obvious, use the closest real CLI chat path
for the product surface being demonstrated, for example `openmates chat`,
`openmates apps <app> <skill>`, or the documented app-skill command. The key
requirement is that the source chat is created through the real OpenMates CLI
and dev API path before it becomes public example data.

## Fast Path

Use the scaffold script whenever possible after the real CLI source chat has
been created, inspected, and shared. It extracts the shared chat, creates the
TypeScript example-chat data file, creates the i18n source YAML, registers the
chat in the store, strips private embed fields such as `vault_key_id` and
`user_id`, and preserves existing order when `--force` is used.

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
2. Create and share three real chats through the OpenMates CLI against the dev API. Use the app only for a UI-only product moment with an explicit reason recorded in the handoff or final summary.
3. Inspect each candidate for the required product behavior and for video usefulness. For example, check whether the answer has a clear focal moment, enough but not too much text, relevant embeds, and a UI state that can be recorded cleanly.
4. Choose the strongest candidate based on content quality, brevity, visual usefulness for recording, and exact match to the social video's intended hook and payoff.
5. Convert only the winner with `scripts/create-example-chat-from-share.mjs`.
6. Delete, unshare, or otherwise clean up the two unused candidate chats if they were created only for this workflow.

## Steps

### 1. Create and inspect the real CLI source chat

Create the source chat with the real OpenMates CLI and dev API. Record the
command, chat ID, and share URL in the session notes or spec evidence. Inspect
the CLI output and, when needed, open the real chat in the web app before
scaffolding to confirm the transcript and embeds are suitable for public use.

Do not proceed if the real chat is missing the intended app-skill output,
contains broken embeds, has weak content, leaks private data, or requires manual
transcript rewriting to look good. Create a better real CLI chat instead.

### 2. Extract chat content

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

### 3. Determine slug and variable name

Ask the user for a natural-language slug if not obvious from the title. Examples:
- "Gigantic airplanes for transporting rocket parts" → `gigantic-airplanes-transporting-rocket-parts`
- "Artemis II Mission Highlights" → `artemis-ii-mission-highlights`

The slug should be SEO-friendly: lowercase, hyphens, no special chars, descriptive.

Derive the TypeScript variable name from the slug: `giganticAirplanesChat`, `artemisIIMissionChat`, etc.
The chat_id prefix is always `example-`: e.g. `example-gigantic-airplanes`.
The i18n key prefix is `example_chats.{snake_case_name}`.

### 4. Generate TypeScript data file

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

### 5. Generate i18n YAML source file

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

### 6. Register in exampleChatStore.ts

Add import and array entry in `frontend/packages/ui/src/demo_chats/exampleChatStore.ts`:

```typescript
import { {varName} } from "./data/example_chats/{slug}";

const ALL_EXAMPLE_CHATS: ExampleChat[] = [
  ...,
  {varName},
].sort((a, b) => a.metadata.order - b.metadata.order);
```

### 7. Build translations

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

### 8. Deploy

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
python3 scripts/tests.py run --suite playwright --spec example-chats-load.spec.ts --environment development --force
python3 scripts/tests.py run --suite playwright --spec example-chat-clone.spec.ts --environment development --force
```

Then verify the specific deployed example page yourself before responding:

1. Open `https://app.dev.openmates.org/example/{slug}`.
2. Confirm the expected user and assistant messages render in the transcript.
3. Confirm each expected embed preview renders without raw JSON, missing assets, or private fields.
4. Open every relevant embed fullscreen and confirm the fullscreen content, CTA links, and close behavior work.
5. Reload the page and confirm the same example chat still loads correctly.

Return the example-chat link only after these checks pass. Include the deployed
URL, the verification commands or browser checks performed, and the deploy
commit. If any check fails, do not give the link as complete; fix the issue or
report the blocker.

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
