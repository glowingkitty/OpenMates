---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/styles/theme.css
  - frontend/packages/ui/src/actions/focusTrap.ts
  - frontend/apps/web_app/tests/a11y-helpers.ts
  - frontend/apps/web_app/tests/a11y-pages.spec.ts
  - frontend/apps/web_app/tests/a11y-keyboard-nav.spec.ts
  - frontend/apps/web_app/tests/a11y-modal-dialogs.spec.ts
---

# Accessibility

> WCAG 2.1 AA compliance patterns for keyboard navigation, screen readers, and color contrast across the OpenMates web app.

## Why This Exists

Ensures the web app is usable by everyone, including keyboard-only users and screen reader users. The system provides global focus indicators, focus trapping for modals, and automated axe-core testing.

## How It Works

### Focus-Visible System

Global rules in `theme.css` (line ~724):

- `*:focus:not(:focus-visible)` removes outline for pointer users
- `*:focus-visible` shows a 3px orange ring (`--color-button-primary`) with 2px offset for keyboard users
- Orange buttons use a blue/indigo ring (`--color-primary-start`) to avoid same-color-on-same-color

**Rules:**
1. Never add `outline: none` in component CSS -- the global rule handles both cases
2. Custom `:focus` styles must not include `outline: none`
3. Svelte scoped style specificity can override global rules, so be careful

### Skip Navigation

A visually-hidden skip link is the first focusable element, jumping to `#main-chat`. CSS in `theme.css`, target has `tabindex="-1"`.

### Focus Trap Action (`focusTrap.ts`)

Svelte action for modal dialogs:
- On mount: focuses first focusable child (or node itself)
- Tab/Shift+Tab wraps inside the node
- Escape calls optional `onEscape` callback
- On destroy: restores focus to previously-focused element

### Modal/Dialog Checklist

Every modal must have: `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, `use:focusTrap`, overlay with `role="presentation"`, Escape closes. Gold standard: `SecurityAuth.svelte`, `PaymentAuth.svelte`.

### Icon Accessibility (`Icon.svelte`)

- Decorative icons (inside labeled parents): `ariaHidden={true}`
- Icon-only buttons: must have `ariaLabel`
- Never use `'placeholder'` as an accessible name

### Interactive Elements

1. Always use `<button>` for clickable elements
2. If `<div>` must be interactive: `role="button"`, `tabindex="0"`, `onkeydown` for Enter and Space
3. Never suppress Svelte a11y warnings with `svelte-ignore`

### Screen Reader Guidelines

- Chat items use `chat.title` for `aria-label`, never `chat.encrypted_title`
- All labels use `$text()` for localization
- Notification `aria-live` regions in place for sync status and errors

### Tab Order

1. Skip link -> 2. Header -> 3. Main chat -> 4. Message input -> 5. Sidebar (if open; hidden via `visibility: hidden` when closed)

## Edge Cases

### Color Contrast

Light theme targets WCAG AA. Two known failures tracked for fix:
- `--color-font-secondary` (#a9a9a9): ~2.6:1 ratio (below 4.5:1 AA)
- `--color-font-field-placeholder` (#9e9e9e): ~2.8:1 ratio (below 4.5:1 AA)

Dark theme passes all ratios.

### Known Test Exclusions

- `color-contrast` -- the two variables above
- `meta-viewport` -- `maximum-scale=1` for mobile PWA input focus prevention
- Third-party iframes (Stripe, reCAPTCHA) excluded from scans

## Automated Testing

Tests use `@axe-core/playwright` via shared helpers in `a11y-helpers.ts`:

| File | Coverage |
|------|----------|
| `a11y-helpers.ts` | `scanPageA11y`, `scanComponentA11y`, `assertNoA11yViolations`, `KNOWN_VIOLATIONS` |
| `a11y-pages.spec.ts` | Full-page axe scans: landing, login, chat, settings, 404 |
| `a11y-keyboard-nav.spec.ts` | Skip link, tab order, focus trap, sidebar toggle |
| `a11y-modal-dialogs.spec.ts` | Dialog ARIA attributes, focus trap, Escape, overlay roles |

## Related Docs

- [Web App Architecture](./web-app.md) -- overall app structure
- [Focus Modes Implementation](../apps/focus-modes-implementation.md) -- ESC key handling in focus mode embeds
