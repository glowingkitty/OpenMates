# Frontend Standards (Svelte/TypeScript)

Standards for modifying frontend code in `frontend/` - Svelte 5 components, TypeScript services, CSS, and stores.

---

## Svelte 5 Requirements (CRITICAL)

**USE SVELTE 5 RUNES ONLY:**

- `$state()` for reactive state
- `$derived()` for computed values
- `$effect()` for side effects
- `$props()` for component props

**NEVER use `$:` reactive statements** - this is Svelte 4 syntax and must not be used.

### Component Structure

```svelte
<script lang="ts">
  // Imports first
  import { onMount } from 'svelte';

  // Props interface
  interface Props {
    title: string;
    isVisible?: boolean;
  }

  // Props with defaults using Svelte 5 runes
  let { title, isVisible = true }: Props = $props();

  // Local state using Svelte 5 runes
  let isLoading = $state(false);

  // Derived/computed values using Svelte 5 runes (NOT $:)
  let displayTitle = $derived(title.toUpperCase());
</script>

<div class="component-wrapper">
  {#if isVisible}
    <h1>{displayTitle}</h1>
  {/if}
</div>

<style>
  .component-wrapper {
    padding: 1rem;
    background-color: var(--color-grey-20);
  }
</style>
```

---

## TypeScript Standards

- Use strict type checking
- Define interfaces for all props and data structures
- Use type assertions sparingly
- Prefer `interface` over `type` for object shapes

---

## Styling Guidelines

- Use CSS custom properties defined in `frontend/packages/ui/src/styles/theme.css`
- Follow the existing design system with predefined color variables
- Reference existing CSS files: `theme.css`, `buttons.css`, `cards.css`, `chat.css`, `fields.css`
- Create custom CSS only when the existing design system doesn't suffice
- Follow mobile-first responsive design

### Colors — Dark Mode Compatibility (CRITICAL)

**Never use raw color literals.** The dark theme inverts the entire grey scale via `[data-theme="dark"]` — a hardcoded `white` or `#fff` will be invisible or broken in dark mode. Always use theme variables:

| Use case                  | Variable                                                    | Never use                    |
| ------------------------- | ----------------------------------------------------------- | ---------------------------- |
| Page / card background    | `var(--color-grey-0)`                                       | `white`, `#fff`, `#ffffff`   |
| Subtle surface / input bg | `var(--color-grey-10)` – `var(--color-grey-20)`             | `#f9f9f9`, `#f3f3f3`         |
| Dividers / borders        | `var(--color-grey-25)` – `var(--color-grey-30)`             | `#e3e3e3`, `rgba(0,0,0,0.1)` |
| Body text                 | `var(--color-font-primary)`                                 | `black`, `#000`, `#222`      |
| Secondary / muted text    | `var(--color-font-secondary)`, `var(--color-font-tertiary)` | `#a9a9a9`, `#6b6b6b`, `gray` |
| Error states              | `var(--color-error)`, `var(--color-error-light)`            | `#e74c3c`, `red`             |
| Warning states            | `var(--color-warning)`, `var(--color-warning-bg)`           | `#e67e22`, `orange`          |

**Exception:** Intentionally hardcoded values (syntax highlighting, brand gradients) must have an inline comment explaining why.

### Font Sizes — Use `rem`, Never `px`

`px` is fixed and ignores the user's browser font size preference (accessibility: zoom, large-text). Always use `rem`.

| Context                         | Variable                                                            | Never use         |
| ------------------------------- | ------------------------------------------------------------------- | ----------------- |
| Body / paragraphs               | `var(--font-size-p)`                                                | `font-size: 16px` |
| Headings                        | `var(--font-size-h1)` – `var(--font-size-h4)`                       | `font-size: 24px` |
| Buttons                         | `var(--button-font-size)`                                           | `font-size: 16px` |
| Inputs                          | `var(--input-font-size)` (must stay >= 1rem — iOS Safari auto-zoom) | `font-size: 16px` |
| Small / secondary text          | `var(--processing-details-font-size)`                               | `font-size: 14px` |
| One-off size (no variable fits) | `0.875rem`, `1.125rem`, etc.                                        | `14px`, `18px`    |

**`rem` vs `em`:** Use `rem` for `font-size` (relative to root — consistent, non-compounding). `em` is acceptable for `padding`/`margin`/`line-height` inside a text container where scaling with local font size is intentional. Never use `em` for `font-size` in components.

---

## State Management

- Use Svelte stores for global state
- Prefer local component state when possible
- Use derived stores for computed values
- Implement proper store subscriptions and cleanup

---

## Module Boundaries

- **Stores** must NOT import from other stores' internal modules. Use barrel exports (e.g., import from `authStore.ts`, not `authSessionActions.ts`).
- **Shared components** live in `frontend/packages/ui/src/components/`. If you find the same component logic in 2+ app-specific files, extract it.
- **Shared services/utils** live in `frontend/packages/ui/src/services/` and `src/utils/`. Search there before writing new utility functions.

---

## Component Preview Requirements

Every new `.svelte` component in `frontend/packages/ui/src/components/` MUST have a companion `.preview.ts` file:

- **File location:** Next to the component: `ComponentName.preview.ts` alongside `ComponentName.svelte`
- **Default export:** `Record<string, unknown>` — realistic mock props for the default state
- **Variants export (recommended):** `Record<string, Record<string, unknown>>` — named variant prop sets for different states (e.g., `processing`, `error`, `loading`, `mobile`)
- **Verify on dev preview:** After creating a new component, verify it renders at `app.dev.openmates.org/dev/preview/<component-path>` with the preview data

This enables the `/dev/preview/` system to render every component for visual inspection and testing. Components without preview files show a "Render Error" panel.

---

## Required Props Over Optional Props

Callback props that are required for functionality (`onFullscreen`, `onClose`, `onSubmit`) MUST be typed as **required**, not optional. This is enforced because 40+ embed previews silently failed when `onFullscreen` was typed as optional and callers forgot to pass it.

If a prop is sometimes not needed, use two component variants or a discriminated union type instead of `prop?: Type`.

---

## Error Handling

- **NEVER use fallback values to hide errors**
- Use try-catch blocks for async operations
- Always log errors with `console.error()` for debugging
- Display user-friendly error messages to users

---

## UI Bug Investigation Workflow (CRITICAL)

When a UI/visual issue is reported, **always ask for a share link before attempting to reproduce the bug manually.**

### Step 1: Ask for a Share Link

If the user hasn't provided one, ask:

> "Could you share a link to the chat or embed where this happens?  
> (Open the chat → Share button → copy the link)  
> This lets me inspect the actual content and render it directly."

### Step 2: Use the Share Link with Firecrawl

Once you have the share URL, open it in a Firecrawl browser session to observe the visual bug directly — no login, no manual reproduction needed:

```
firecrawl_browser_create
→ agent-browser open "<share-url>"
→ agent-browser screenshot          # observe the actual visual bug
→ agent-browser snapshot -i -c      # inspect DOM structure if needed
```

### Step 3: Also Inspect the Content (Optional)

The same share URL can decrypt and display the message/embed content involved:

```bash
docker exec api python /app/backend/scripts/debug.py chat <chat_id> \
  --share-url "<share-url>"
```

### When You Cannot Get a Share Link

Fall back to manual reproduction on `https://app.dev.openmates.org` using a Firecrawl session. See `docs/claude/debugging.md` → "Browser-Based Debugging with Firecrawl" for the full workflow.

---

## Frontend Development Workflow

### No Local Dev Server (CRITICAL)

**DO NOT run `pnpm dev` or `npm run dev`** - there is no local development server running on the server.

**Default deployment workflow:**

1. Make frontend code changes
2. Run linter to verify changes: `./scripts/lint_changed.sh --ts --svelte --path frontend/`
3. Commit and push changes to git
4. The web app is **automatically built and deployed** when changes are pushed

**Only start a dev server if:**

- The user **explicitly and specifically** requests running a local dev server
- The user says something like "start the dev server" or "run pnpm dev"

**Never assume** a dev server is needed - the CI/CD pipeline handles building and deploying frontend changes automatically.

---

## Images, Icons, and SVG Assets (CRITICAL)

**NEVER create, generate, or write SVG, PNG, JPG, or any other image/icon files yourself.**

- Do NOT write inline SVG markup to represent logos, illustrations, or icons that need to be sourced from a designer/user
- Do NOT generate placeholder image data or base64-encoded images
- Do NOT attempt to approximate or recreate a graphic you haven't been given

**When an image or icon is needed:**

1. Stop and ask the user to provide the asset
2. Describe clearly what is needed (e.g., "Please provide a PNG or SVG for the app logo")
3. Tell the user the exact path where the file must be saved (e.g., `frontend/packages/ui/src/assets/logo.svg`) and the ideal resolution or dimensions (e.g., "512×512px PNG" or "SVG preferred for scalability")
4. Once the user confirms the file has been added at that path, reference it in code using the appropriate `<img>` tag or CSS `url()` — do not modify its content

**Exceptions (allowed):**

- Simple CSS-only shapes (borders, `border-radius` circles, etc.) that are purely decorative layout elements
- Icon libraries already installed as a dependency (e.g., referencing an existing icon component from a library already in the project)

---

## Package and Dependency Management (CRITICAL)

**NEVER add a package with a version number from memory.** LLM training data is outdated — versions you "know" may be months or years behind. Every new or updated dependency MUST have its version verified before being written into any file.

### Mandatory Version Lookup Steps

Before adding or updating ANY npm/pnpm package:

1. **Look up the latest version** using web search (e.g., search `<package-name> npm latest version`) or run:
   ```bash
   pnpm info <package-name> version
   ```
2. **Use the exact version returned** — do not guess, do not use a version from memory.
3. **Use a precise version** (e.g., `"1.2.3"`) or a conservative range (e.g., `"^1.2.3"`). Do NOT use `"latest"` or `"*"`.

### Prohibited

- Writing `"package": "1.x.x"` based on what you think the current version is
- Using `"latest"` or `"*"` as a version specifier
- Skipping the lookup because the package "seems well-known"
