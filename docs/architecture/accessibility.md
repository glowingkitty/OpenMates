# Accessibility Architecture

**Status:** Active
**Last updated:** 2026-03-20

## Overview

This document describes the accessibility (a11y) patterns used across the OpenMates web app. The goal is WCAG 2.1 AA compliance for keyboard navigation, screen readers, and color contrast.

---

## Focus-Visible System

The global focus indicator lives in `frontend/packages/ui/src/styles/theme.css`:

```css
/* Remove browser default ring for pointer users */
*:focus:not(:focus-visible) {
  outline: none;
}

/* Orange ring for keyboard users */
*:focus-visible {
  outline: 3px solid var(--color-button-primary, #ff553b);
  outline-offset: 2px;
}
```

### Rules

1. **Never add `outline: none` in component CSS.** The global rule handles both cases: pointer users see no ring, keyboard users see the orange ring. Component-level `outline: none` overrides this (due to Svelte scoped style specificity) and breaks keyboard navigation.
2. **Custom focus styles** (e.g., border-color change on `:focus`) should use `:focus` for the visual enhancement but **must not** include `outline: none`. The global system handles outline suppression.
3. **Orange buttons** use a blue/indigo focus ring (`--color-primary-start`) instead of orange — defined in `buttons.css` to avoid same-color-on-same-color.

---

## Skip Navigation Link

A visually-hidden skip link is the first focusable element on the page (`+page.svelte`). It becomes visible on keyboard focus and jumps to `#main-chat`.

```html
<a href="#main-chat" class="skip-link">{$text('navigation.skip_to_content')}</a>
```

The target has `tabindex="-1"` for programmatic focus. CSS lives in `theme.css`.

---

## Focus Trap Action

`frontend/packages/ui/src/actions/focusTrap.ts` — a Svelte action for modal dialogs.

### Usage

```svelte
<script>
  import { focusTrap } from '../actions/focusTrap';
</script>

<div role="dialog" aria-modal="true" use:focusTrap={{ onEscape: close }}>
  ...
</div>
```

### Behaviour

- On mount: focuses the first focusable child (or the node itself)
- Tab/Shift+Tab wraps around inside the node
- Escape calls the optional `onEscape` callback
- On destroy: restores focus to the previously-focused element

---

## Modal/Dialog Checklist

Every modal must have:

| Attribute | Required | Why |
|-----------|----------|-----|
| `role="dialog"` | Yes | Announces as dialog |
| `aria-modal="true"` | Yes | Tells AT background is inert |
| `aria-labelledby="..."` | Yes | Links to the dialog's heading |
| `use:focusTrap` | Yes | Traps Tab inside the dialog |
| `tabindex="-1"` on dialog | Recommended | Allows programmatic focus |
| Overlay: `role="presentation"` | Yes | Overlay is not interactive |
| Escape closes | Yes | Handled by focusTrap `onEscape` |

**Gold standard:** `SecurityAuth.svelte` and `PaymentAuth.svelte`.

**Anti-patterns to avoid:**
- `role="button"` on overlay (use `role="presentation"`)
- `role="presentation"` on the modal content (use `role="dialog"`)
- `onkeydown` on overlay for Escape (use focusTrap instead)

---

## Icon Accessibility

`Icon.svelte` has two accessibility props:

| Prop | Type | Default | Use |
|------|------|---------|-----|
| `ariaHidden` | `boolean` | `false` | Set `true` for decorative icons inside labeled parents |
| `ariaLabel` | `string` | `undefined` | Override the accessible label (defaults to icon name) |

### Rules

- **Decorative icons** (inside a button with text, or inside an `aria-label`ed container): use `ariaHidden={true}`
- **Icon-only buttons**: must have `ariaLabel` (button variant requires a label)
- **Never** use `'placeholder'` as an accessible name — if no name is set, the icon is silently unlabeled

---

## Interactive Element Rules

1. **Always use `<button>`** for clickable elements. Avoid `<div onclick>`.
2. If `<div>` must be interactive (rare cases), it **must** have:
   - `role="button"`
   - `tabindex="0"`
   - `onkeydown` handler for Enter and Space
3. **Space key:** `role="button"` elements must respond to both Enter and Space (Space is the native button activation key).
4. **Never suppress Svelte a11y warnings** with `svelte-ignore`. Fix the underlying issue instead.

---

## Screen Reader Guidelines

- **Chat items:** Use `chat.title` for `aria-label`, never `chat.encrypted_title` (which is ciphertext)
- **AppStoreCard:** Use `aria-label={app.name}`, hide description and provider icons with `aria-hidden="true"`
- **Notification aria-live regions:** Already in place for sync status, error messages
- **i18n:** All labels use `$text()` for localization

---

## Color Contrast

Light theme targets WCAG AA (4.5:1 for normal text, 3:1 for large text):

| Variable | Value | Ratio on white |
|----------|-------|----------------|
| `--color-font-primary` | Dark | >7:1 |
| `--color-font-secondary` | `#a9a9a9` | ~2.6:1 (below AA — tracked for fix) |
| `--color-font-field-placeholder` | `#9e9e9e` | ~2.8:1 (below AA — tracked for fix) |

Dark theme passes all ratios.

---

## Tab Order

Expected keyboard tab order:

1. Skip link (visible only on focus)
2. Header navigation
3. Main chat content area
4. Message input
5. Sidebar (if open; hidden from tab order when closed via `visibility: hidden`)

Focus is programmatically moved to `#main-chat` when a chat is selected from the sidebar.

---

## Automated Accessibility Testing

E2E accessibility tests live in `frontend/apps/web_app/tests/a11y-*.spec.ts` and use `@axe-core/playwright` for automated WCAG 2.1 AA violation scanning.

### Test Files

| File | Coverage |
|------|----------|
| `a11y-helpers.ts` | Shared utilities: `scanPageA11y`, `scanComponentA11y`, `assertNoA11yViolations`, `KNOWN_VIOLATIONS` |
| `a11y-pages.spec.ts` | Full-page axe scans: landing, login, chat, settings, 404 |
| `a11y-keyboard-nav.spec.ts` | Skip link, tab order, focus trap, sidebar toggle via keyboard |
| `a11y-modal-dialogs.spec.ts` | Dialog ARIA attributes, focus trap, Escape, overlay roles |

### Known Exclusions

These violations are tracked but excluded from CI failure:

- `color-contrast` — `--color-font-secondary` (#a9a9a9, ~2.6:1) and `--color-font-field-placeholder` (#9e9e9e, ~2.8:1) are below WCAG AA on light backgrounds
- Third-party iframes (Stripe, reCAPTCHA) are excluded from scans

### Running

```bash
# All a11y specs
npx playwright test a11y-

# Specific suite
npx playwright test a11y-pages
npx playwright test a11y-keyboard-nav
npx playwright test a11y-modal-dialogs
```
