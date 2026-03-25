---
status: active
last_verified: 2026-03-24
---

# Settings UI Design Guidelines

Single source of truth for all settings page components. Every visual element on a settings page MUST use a canonical component from this system — no custom inline HTML/CSS is allowed.

**Preview:** `/dev/preview/settings`
**Figma:** "settings_menu_elements" frame (node 4944-31418)
**Components:** `frontend/packages/ui/src/components/settings/elements/`

---

## Quick Reference

| # | Component | Import | Purpose | Preview |
|---|-----------|--------|---------|---------|
| 1–5 | `SettingsItem` | `@repo/ui/components/SettingsItem.svelte` | Menu rows (5 variants: submenu, toggle, quickaction, value, heading) | A |
| 6 | `SettingsConsentToggle` | `settings/elements` | Toggle with consent text | B |
| 7 | `SettingsInput` | `settings/elements` | Short text input | B |
| 8 | `SettingsTextarea` | `settings/elements` | Multi-line text input | B |
| 9 | `SettingsDropdown` | `settings/elements` | Select dropdown | B |
| 10 | `SettingsFileUpload` | `settings/elements` | File picker | B |
| 11 | `SettingsQuote` | `settings/elements` | Quoted text card | B |
| 12 | `SettingsTabs` | `settings/elements` | Icon tabs with animated pill | B |
| 13 | `SettingsInfoBox` | `settings/elements` | Info/success/error/warning message | B |
| — | `SearchSortBar` | `settings/SearchSortBar.svelte` | Search input + sort dropdown | C |
| 14 | `SettingsButton` | `settings/elements` | Action button (primary/danger/secondary/ghost) | D |
| 15 | `SettingsButtonGroup` | `settings/elements` | Flex container for button groups | D |
| 16 | `SettingsLoadingState` | `settings/elements` | Spinner / empty state / generating | E |
| 17 | `SettingsCard` | `settings/elements` | Section container card | F |
| 18 | `SettingsDetailRow` | `settings/elements` | Key-value pair row | F |
| 19 | `SettingsPageHeader` | `settings/elements` | Page title + description | G |
| 20 | `SettingsProgressBar` | `settings/elements` | Progress indicator bar | E |
| 21 | `SettingsBadge` | `settings/elements` | Status badge/pill | E |
| 22 | `SettingsConfirmBlock` | `settings/elements` | Destructive action confirmation | G |
| 23 | `SettingsCodeBlock` | `settings/elements` | Monospace text display | F |
| 24 | `SettingsAvatar` | `settings/elements` | Circular profile picture | G |
| 25 | `SettingsBalanceDisplay` | `settings/elements` | Hero amount display | F |
| 26 | `SettingsDivider` | `settings/elements` | Horizontal separator | H |
| 27 | `SettingsGradientLink` | `settings/elements` | Gradient text link | H |
| 28 | `SettingsCheckboxList` | `settings/elements` | Checkbox items with descriptions | G |
| 29 | `SettingsPageContainer` | `settings/elements` | Page wrapper with max-width | H |

---

## Usage Rules

### MUST use canonical components
- Every settings page MUST use only components from this system
- Every button MUST use `SettingsButton` — NEVER define `.save-button` or similar inline CSS
- Every error/warning/success message MUST use `SettingsInfoBox`
- Every loading/empty state MUST use `SettingsLoadingState`
- Every section container MUST use `SettingsCard`
- Every key-value display MUST use `SettingsDetailRow`
- Every progress indicator MUST use `SettingsProgressBar`
- Every page title MUST use `SettingsPageHeader`
- Every page wrapper MUST use `SettingsPageContainer`

### NEVER allowed in settings pages
- Custom `<style>` blocks with layout/component CSS
- Inline button styling (`.btn-*`, `.save-button`, `.delete-button`)
- Inline spinner CSS or `@keyframes spin`
- Custom error/warning containers
- Custom card/container backgrounds
- Hardcoded colors (use `var(--color-*)`)

### When to create a new element
A new canonical component is justified when:
1. Pattern appears in 3+ settings pages
2. Has a clear visual specification in Figma
3. Can be expressed with <5 props

To add: create in `settings/elements/`, export from `index.ts`, add demo to preview page.

---

## Page Composition Pattern

Every settings sub-page follows this structure:

```svelte
<SettingsPageContainer>
    <SettingsPageHeader title="Page Title" description="Optional description" />

    <!-- Content sections -->
    <SettingsCard>
        <SettingsDetailRow label="Key" value="Value" />
        <SettingsDetailRow label="Key" value="Value" />
    </SettingsCard>

    <SettingsInfoBox type="info">Explanatory text</SettingsInfoBox>

    <!-- Form inputs -->
    <SettingsItem type="heading" icon="settings" title="Section" />
    <SettingsInput bind:value={name} placeholder="Enter name" />

    <!-- Actions -->
    <SettingsButtonGroup>
        <SettingsButton variant="secondary">Cancel</SettingsButton>
        <SettingsButton variant="primary" onClick={handleSave}>Save</SettingsButton>
    </SettingsButtonGroup>
</SettingsPageContainer>
```

---

## Component Details

### SettingsButton
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| variant | "primary" \| "danger" \| "secondary" \| "ghost" | "primary" | Visual style |
| size | "sm" \| "md" | "md" | Button size |
| disabled | boolean | false | Disabled state |
| loading | boolean | false | Shows spinner, disables click |
| fullWidth | boolean | false | Stretches to 100% width |
| onClick | () => void | — | Click handler |
| children | Snippet | required | Button label content |

**Do:**
```svelte
<SettingsButton variant="danger" onClick={handleDelete}>Delete Account</SettingsButton>
```
**Don't:**
```svelte
<button class="delete-button" onclick={handleDelete}>Delete Account</button>
```

### SettingsCard
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| variant | "default" \| "highlighted" \| "current" | "default" | Visual style |
| highlightColor | string | — | CSS color for highlight border |
| padding | "sm" \| "md" \| "lg" | "md" | Inner padding |
| children | Snippet | required | Card content |

### SettingsDetailRow
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| label | string | required | Left-side label |
| value | string | "" | Right-side value |
| muted | boolean | false | Reduced opacity |
| highlight | boolean | false | Primary color on value |
| icon | string | "" | Icon class name next to value |
| iconColor | string | "" | Icon color |

### SettingsLoadingState
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| variant | "spinner" \| "empty" \| "generating" | "spinner" | Display mode |
| text | string | "" | Message text |
| hint | string | "" | Smaller secondary text |

### SettingsProgressBar
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| value | number | required | 0–100 progress |
| variant | "default" \| "warning" \| "success" | "default" | Color variant |
| label | string | "" | Label above bar |
| showPercent | boolean | false | Show percentage |

### SettingsBadge
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| variant | "info" \| "success" \| "warning" \| "danger" \| "neutral" | "neutral" | Color variant |
| text | string | required | Badge text |

### SettingsConfirmBlock
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| warningText | string | required | Warning message |
| confirmLabel | string | required | Toggle label |
| checked | boolean (bindable) | false | Toggle state |
| variant | "danger" \| "warning" | "danger" | Severity |

### SettingsCodeBlock
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| code | string | required | Text content |
| copyable | boolean | false | Show copy button |
| maxHeight | string | "" | Max height with scroll |
| wrap | boolean | true | Wrap text |

### SettingsAvatar
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| src | string | "" | Image URL |
| size | "sm" \| "md" \| "lg" | "md" | Avatar size |
| placeholder | string | "" | Placeholder icon/text |
| editable | boolean | false | Show edit overlay |
| onEdit | () => void | — | Edit handler |

### SettingsBalanceDisplay
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| amount | string | required | Formatted amount |
| label | string | "" | Label below |
| icon | string | "" | Icon class |
| iconColor | string | "" | Icon color |

### SettingsDivider
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| spacing | "sm" \| "md" \| "lg" | "md" | Vertical spacing |

### SettingsGradientLink
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| href | string | "" | Link URL |
| external | boolean | false | Opens in new tab |
| onClick | () => void | — | Click handler |
| children | Snippet | required | Link text |

### SettingsCheckboxList
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| options | Array<{id, label, description?, icon?, checked}> (bindable) | required | Checkbox items |
| nested | boolean | false | Indented style |
| onChange | (id, checked) => void | — | Change handler |

### SettingsPageContainer
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| maxWidth | "narrow" \| "default" \| "wide" | "default" | Content max-width |
| children | Snippet | required | Page content |

### SettingsPageHeader
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| title | string | required | Page title |
| description | string | "" | Description below title |

### SettingsButtonGroup
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| align | "left" \| "center" \| "right" \| "space-between" | "right" | Button alignment |
| wrap | boolean | true | Allow wrapping |
| children | Snippet | required | Button children |
