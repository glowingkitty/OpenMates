# Figma-to-Code Workflow

Instructions for implementing UI components from Figma designs. **Load this document when given a Figma link or design to implement.**

---

## Overview

This workflow ensures high-fidelity translation of Figma designs into Svelte 5 components that follow OpenMates design system conventions. It is split into three sequential phases — never skip a phase.

---

## Phase 1: Design Interpretation (Before Writing Any Code)

### Step 1 — Extract Design Data

Use the **Figma MCP** to get structured design data from the provided Figma link:

```
# Parse fileKey and nodeId from the Figma URL
# URL format: figma.com/(file|design)/<fileKey>/...?node-id=<nodeId>

1. Call get_figma_data with fileKey (and nodeId if provided)
2. Call download_figma_images to capture PNG screenshots of target frames
```

Extract and document:
- **Layout**: flex direction, gap, padding, alignment, sizing constraints
- **Typography**: font family, size, weight, line height, letter spacing
- **Colors**: fill colors, stroke colors, gradients, opacity values
- **Spacing**: margins, padding, gap between elements
- **Component hierarchy**: parent/child relationships, repeated patterns

### Step 2 — Query All Breakpoints

If the Figma file contains multiple frames for different screen sizes (desktop, tablet, mobile), extract data for **ALL of them before writing any code**.

Build a comparison table documenting what changes between breakpoints:

```
| Property        | Desktop (1440px) | Tablet (768px) | Mobile (375px) |
|-----------------|------------------|----------------|-----------------|
| flex-direction  | row              | row            | column          |
| gap             | 24px             | 16px           | 12px            |
| font-size (h1)  | 32px             | 28px           | 24px            |
| padding         | 48px             | 32px           | 16px            |
| visibility      | all visible      | sidebar hidden | sidebar hidden  |
```

If only one breakpoint is provided in Figma, **note this explicitly** — it will be asked about in Step 5.

### Step 3 — Map to Existing Design System

Compare extracted Figma values against the OpenMates design system. Map every value to existing tokens before considering new ones.

#### Color Mapping

Reference: `frontend/packages/ui/src/styles/theme.css`

| Figma Value | Maps To |
|-------------|---------|
| Whites/grays | `--color-grey-0` (#fff) through `--color-grey-100` (#000) — 12 levels |
| Brand blue gradient | `--color-primary` (135deg, #4867CD → #5A85EB) |
| Orange button | `--color-button-primary` (#FF553B) with `-hover` and `-pressed` variants |
| Gray button | `--color-button-secondary` (#808080) with `-hover` and `-pressed` variants |
| Body text | `--color-font-primary` (#000 light / #e6e6e6 dark) |
| Subtle text | `--color-font-secondary` (#A9A9A9) or `--color-font-tertiary` (#6B6B6B) |
| Button text | `--color-font-button` (#fff) |
| Placeholder | `--color-font-field-placeholder` (#9e9e9e) |
| App-specific | `--color-app-{name}` with `-start`/`-end` for gradients |

**NEVER hardcode hex colors.** If a Figma color does not match any existing token within a reasonable tolerance (±5 on each RGB channel), flag it in the clarifying questions.

#### Typography Mapping

The project uses **Lexend Deca** (variable font, loaded dynamically) and **Work Sans** (Penpot/fallback). Map Figma font specs to existing patterns found in components.

#### Spacing Mapping

No formal spacing scale exists — spacing is component-specific. Check similar existing components for consistent patterns (common values: 4px, 8px, 12px, 16px, 24px, 32px, 48px).

#### CSS File Reference

| File | What It Covers |
|------|----------------|
| `theme.css` | All CSS custom properties (colors, gradients) |
| `buttons.css` | Button styles (primary, secondary, social) |
| `cards.css` | App card components (large/small variants) |
| `chat.css` | Chat message layout (user/mate bubbles, animations) |
| `fields.css` | Input field styles (text, email, password, search) |
| `icons.css` | Icon system (CSS mask-image technique with SVG) |
| `mates.css` | Mate profile pictures (avatars with AI badge) |

All at: `frontend/packages/ui/src/styles/`

### Step 4 — Search for Reusable Components

Before creating anything new, search the existing 273+ components:

```
frontend/packages/ui/src/components/
├── common/          # Button, InputWarning, Tooltip
├── embeds/          # 65 embed components (Preview + Fullscreen pairs)
├── settings/        # 60+ settings components
├── signup/          # 20+ signup step components
├── cards/           # App cards
├── nav/             # Navigation
├── payment/         # Payment forms
├── enter_message/   # Message input system
└── (root level)     # Header, Footer, Toggle, Field, Icon, etc.
```

Key shared base components to know about:
- **`UnifiedEmbedPreview.svelte`** — Base for all embed preview cards (300x200 desktop, 150x290 mobile)
- **`UnifiedEmbedFullscreen.svelte`** — Base for all embed fullscreen views
- **`BasicInfosBar.svelte`** — Shared bottom bar for embeds (app icon, skill icon, status)
- **`Button.svelte`**, **`Field.svelte`**, **`Toggle.svelte`** — Root-level shared components

Identify which existing components can be:
1. **Reused directly** (the Figma design matches an existing component)
2. **Extended** (add a prop or variant to an existing component)
3. **Composed** (combine existing components into a new layout)
4. **Created new** (nothing similar exists — document why)

### Step 5 — Ask Clarifying Questions

**ALWAYS ask the user these questions before proceeding.** Do not assume answers.

#### Required Questions

1. **Responsive behavior** — If only one breakpoint was provided in Figma:
   - "The Figma design shows a desktop layout at Xpx width. How should this behave on tablet (768px) and mobile (375px)? Should I follow the existing mobile-first patterns from similar components, or do you have specific requirements?"

2. **Interactive states** — For each interactive element:
   - "I see [button/input/card/etc.]. What should the hover, active, disabled, and loading states look like? Should I follow the existing patterns from `buttons.css` / `fields.css`?"

3. **Data flow** — For any content shown in the design:
   - "Which parts of this design are dynamic (passed as props) vs static? What TypeScript interface should the props follow?"

4. **Component reuse** — When existing components are close matches:
   - "I found [ComponentName] which is similar to [part of the Figma design]. Should I reuse/extend it, or create a new component?"

5. **Dark mode** — Since the app supports light/dark themes:
   - "Does this design need dark mode support? The CSS custom properties handle most cases automatically, but [specific elements] may need explicit dark mode overrides."

#### Conditional Questions

- **If the component involves embeds**: "Should this follow the UnifiedEmbedPreview/Fullscreen pattern?"
- **If new colors appear**: "The Figma design uses [hex value] which doesn't match any existing token. Should I add a new CSS custom property, or map it to the nearest existing token [token name, hex value]?"
- **If new icons appear**: "The design includes an icon that doesn't exist in `static/icons/`. Should I create a new SVG icon, or is there an existing one I should use?"
- **If animations are present**: "I see [animation/transition] in the design. What is the expected behavior? Should I use CSS transitions or the existing animation patterns?"

### Step 6 — Present Implementation Plan

After receiving answers, present a brief implementation plan:

```
## Implementation Plan

### New files:
- frontend/packages/ui/src/components/[path]/[ComponentName].svelte

### Modified files:
- [list any existing files that need changes]

### Design token usage:
- Background: var(--color-grey-20)
- Text: var(--color-font-primary)
- [etc.]

### Responsive strategy:
- Mobile-first with breakpoints at 768px and 1440px
- [specific layout changes per breakpoint]

### Component composition:
- Reuses: [existing components]
- New: [what needs to be created]
```

**Wait for user confirmation before proceeding to Phase 2.**

---

## Phase 2: Implementation

### Coding Standards

Follow `docs/claude/frontend-standards.md` strictly. Key reminders:

- **Svelte 5 runes ONLY**: `$state()`, `$derived()`, `$effect()`, `$props()` — NEVER `$:`
- **CSS custom properties**: Always use `var(--color-*)` — NEVER hardcode hex values
- **TypeScript strict**: Define `interface Props` for all component props
- **Mobile-first**: Write base styles for mobile, add `@media` queries for larger screens
- **Comments**: Explain layout decisions that aren't obvious from the code

### Asset Handling

- **Icons**: Use existing icons from `static/icons/` with the CSS mask technique from `icons.css`. Only add new SVGs if confirmed in Phase 1.
- **Images**: Download via Figma MCP `download_figma_images`, place in appropriate `static/` directory.
- **Fonts**: Use existing Lexend Deca / Work Sans. Do NOT add new fonts without explicit confirmation.

### File Naming & Location

- Components in `frontend/packages/ui/src/components/` following the existing directory structure
- PascalCase filenames matching the component name
- Colocate related utilities (e.g., `componentContent.ts`) in the same directory

### Preview Files (for the Component Preview System)

When creating a new component, also create a `.preview.ts` companion file with mock
props so the component can be previewed at `/dev/preview/`:

```typescript
// ComponentName.preview.ts (same directory as ComponentName.svelte)

/** Default props for the component preview */
const defaultProps = {
  title: 'Example Title',
  status: 'finished' as const,
  onClose: () => console.log('[Preview] Close clicked'),
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  loading: {
    ...defaultProps,
    status: 'processing' as const,
  },
  error: {
    ...defaultProps,
    status: 'error' as const,
  },
  mobile: {
    ...defaultProps,
    isMobile: true,
  },
};
```

This enables:
- Auto-loaded mock data when navigating to the component in the preview system
- Variant switching to test different states (loading, error, mobile, etc.)
- Editable props via the built-in JSON editor

### After Implementation

Run the linter before proceeding to validation:

```bash
./scripts/lint_changed.sh --ts --svelte --path frontend/packages/ui
```

Fix all linting errors before Phase 3.

---

## Phase 3: Visual Validation

### Using the Component Preview System

OpenMates includes a built-in component preview system at `/dev/preview/`.
It is accessible on dev environments (localhost and `app.dev.openmates.org`) but
blocked on production.

- **Dev deployment**: `https://app.dev.openmates.org/dev/preview/`
- **Local dev server**: `http://localhost:5173/dev/preview/` (if running `pnpm dev`)

1. Navigate to the preview URL to browse all components
2. Find the component you implemented in the component tree
3. Use the preview to visually compare against the Figma screenshot

### Using Playwright MCP for Automated Validation

For precise validation, use the **Playwright MCP** browser tools:

```
1. Navigate to the component preview URL or the page containing the component
2. Resize to match Figma frame dimensions (browser_resize)
3. Take a screenshot (browser_take_screenshot)
4. Compare against the Figma screenshot from Phase 1
5. Use browser_evaluate to verify computed CSS properties:
```

Example computed style verification:

```javascript
// browser_evaluate function:
() => {
  const el = document.querySelector('.your-component');
  const computed = window.getComputedStyle(el);
  return {
    display: computed.display,
    flexDirection: computed.flexDirection,
    gap: computed.gap,
    padding: computed.padding,
    fontSize: computed.fontSize,
    color: computed.color,
    backgroundColor: computed.backgroundColor,
  };
}
```

Compare these computed values against the Figma design context values from Phase 1.

### Validation Checklist

For each breakpoint (desktop 1440px, tablet 768px, mobile 375px):

- [ ] Layout direction and alignment match Figma
- [ ] Spacing (gap, padding, margin) matches within 1px
- [ ] Typography (font size, weight, line height) matches
- [ ] Colors match design tokens (not hardcoded)
- [ ] Interactive states work (hover, focus, active, disabled)
- [ ] Dark mode renders correctly (if applicable)
- [ ] Component is accessible (proper semantic HTML, ARIA attributes)
- [ ] No console errors or warnings

### Iteration

If discrepancies are found:
1. **Fix the source code** — NEVER use CSS injection or runtime patches
2. Re-run the linter
3. Re-validate until all checks pass

Stop the dev server when validation is complete.

---

## Quick Reference: Common Patterns

### Embed Preview Component Pattern

All embed previews follow this structure:

```svelte
<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';

  interface Props {
    id: string;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    // ... skill-specific props
    isMobile?: boolean;
    onFullscreen?: () => void;
  }

  let { id, status, isMobile = false, onFullscreen, ...rest }: Props = $props();
</script>

<UnifiedEmbedPreview
  {id}
  appId="appname"
  skillId="skillname"
  skillIconName="icon_name"
  {status}
  skillName="Skill Display Name"
  {isMobile}
  {onFullscreen}
>
  {#snippet details({ isMobile })}
    <!-- Skill-specific preview content here -->
  {/snippet}
</UnifiedEmbedPreview>
```

### Embed Fullscreen Component Pattern

```svelte
<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';

  interface Props {
    onClose: () => void;
    // ... skill-specific props
  }

  let { onClose, ...rest }: Props = $props();
</script>

<UnifiedEmbedFullscreen
  appId="appname"
  title="Fullscreen Title"
  {onClose}
>
  {#snippet content({ children, isLoadingChildren })}
    <!-- Skill-specific fullscreen content here -->
  {/snippet}
</UnifiedEmbedFullscreen>
```

### Standard Component with Design Tokens

```svelte
<style>
  .container {
    background-color: var(--color-grey-10);
    color: var(--color-font-primary);
    padding: 16px;
    border-radius: 12px;
    border: 1px solid var(--color-grey-25);
  }

  .title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-grey-100);
  }

  .subtitle {
    font-size: 14px;
    color: var(--color-font-tertiary);
  }

  /* Mobile-first: base styles are mobile, override for larger */
  @media (min-width: 768px) {
    .container {
      padding: 24px;
    }
    .title {
      font-size: 22px;
    }
  }
</style>
```
