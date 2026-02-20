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

---

## State Management

- Use Svelte stores for global state
- Prefer local component state when possible
- Use derived stores for computed values
- Implement proper store subscriptions and cleanup

---

## Error Handling

- **NEVER use fallback values to hide errors**
- Use try-catch blocks for async operations
- Always log errors with `console.error()` for debugging
- Display user-friendly error messages to users

---

## Frontend Development Workflow

### No Local Dev Server (CRITICAL)

**DO NOT run `pnpm dev` or `npm run dev`** - there is no local development server running on the server.

**Default deployment workflow:**

1. Make frontend code changes
2. Run linter to verify changes: `./scripts/lint_changed.sh --ts --svelte --path frontend/`
3. Commit and push changes to git
4. The web app is **automatically built and deployed** when changes are pushed
5. **CRITICAL: Wait for and verify the Vercel deployment succeeded** — do NOT assume the push means a successful deployment. See `docs/claude/git-and-deployment.md` → "Vercel Deployment Check" for the full procedure. Fix any build errors and re-push until the status shows "● Ready".

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
