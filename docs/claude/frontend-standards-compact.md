# Frontend Standards (Compact)

Full reference: `sessions.py context --doc frontend-standards`

## Critical Rules

- **Svelte 5 ONLY**: `$state()`, `$derived()`, `$effect()`, `$props()`. NEVER use `$:` (Svelte 4)
- **No local dev server**: DO NOT run `pnpm dev`. Push to git — Vercel builds automatically
- **No image/SVG generation**: Ask user to provide assets. CSS-only shapes are OK
- **Package versions**: ALWAYS look up latest via `pnpm info <pkg> version`. Never use versions from memory
- **Required props**: Callback props (`onFullscreen`, `onClose`) MUST be required, not optional
- **Component previews**: Every new `.svelte` component needs a `.preview.ts` file

## Translations — `$text()` Rules (CRITICAL)

**NEVER use `{ default: '...' }` fallbacks in `$text()` calls.** The build validator scans every `$text('some.key')` call and fails the Vercel build if the key is absent from `en.json` — the fallback option does not bypass this check.

**Workflow for any new UI string:**

1. **First** add the key to the correct YAML source file under `frontend/packages/ui/src/i18n/sources/`
2. **Then** use `$text('your.new.key')` — no `{ default }`, no fallbacks ever
3. Run `cd frontend/packages/ui && npm run validate:locales` locally to confirm before committing

```svelte
<!-- ✅ Correct -->
{$text('chats.search.placeholder')}

<!-- ❌ Wrong — fallbacks hide missing keys and break the Vercel build -->
{$text('chats.search_placeholder', { default: 'Search' })}
```

The `validate:locales` check runs automatically in `sessions.py prepare-deploy` and `sessions.py deploy` (and via the git pre-commit hook if installed with `./scripts/install-hooks.sh`).

## Colors — Dark Mode

NEVER use raw color literals. Always use CSS variables:

| Use case   | Variable                                        | Never             |
| ---------- | ----------------------------------------------- | ----------------- |
| Background | `var(--color-grey-0)`                           | `white`, `#fff`   |
| Surface    | `var(--color-grey-10)` – `var(--color-grey-20)` | `#f9f9f9`         |
| Borders    | `var(--color-grey-25)` – `var(--color-grey-30)` | `#e3e3e3`         |
| Body text  | `var(--color-font-primary)`                     | `black`, `#000`   |
| Muted text | `var(--color-font-secondary)`                   | `gray`, `#6b6b6b` |
| Error      | `var(--color-error)`                            | `red`, `#e74c3c`  |

## Font Sizes — `rem` Only, Never `px`

| Context    | Variable                                      |
| ---------- | --------------------------------------------- |
| Body       | `var(--font-size-p)`                          |
| Headings   | `var(--font-size-h1)` – `var(--font-size-h4)` |
| Buttons    | `var(--button-font-size)`                     |
| Inputs     | `var(--input-font-size)` (>= 1rem for iOS)    |
| Small text | `var(--processing-details-font-size)`         |

## Module Boundaries

- Stores must NOT import from other stores' internal modules — use barrel exports
- Shared components: `frontend/packages/ui/src/components/`
- Shared utils: `frontend/packages/ui/src/services/` and `src/utils/`

## UI Bug Workflow

1. Ask for share link first
2. Open in Firecrawl browser: `agent-browser open "<share-url>"` + screenshot
3. Inspect content: `debug.py chat <id> --share-url "<url>"`
