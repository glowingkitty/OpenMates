# Settings UI — Compact Reference

**29 canonical components for settings pages. No custom inline CSS allowed.**

Preview: `/dev/preview/settings` | Full docs: `docs/architecture/settings-ui.md`
Components: `frontend/packages/ui/src/components/settings/elements/`

## Import

```svelte
import { SettingsButton, SettingsCard, SettingsDetailRow, ... } from '@repo/ui/components/settings/elements';
import SettingsItem from '@repo/ui/components/SettingsItem.svelte';
import SearchSortBar from '@repo/ui/components/settings/SearchSortBar.svelte';
```

## Component Quick-Ref

| Component | Key Props | Use For |
|-----------|-----------|---------|
| `SettingsItem` | type, icon, title, hasToggle | Menu rows, headings |
| `SettingsInput` | value, placeholder, type | Short text fields |
| `SettingsTextarea` | value, placeholder, rows | Multi-line text |
| `SettingsDropdown` | value, options | Select menus |
| `SettingsFileUpload` | accept, label, onFileSelected | File pickers |
| `SettingsConsentToggle` | checked, consentText | Consent checkboxes |
| `SettingsQuote` | text, onClick | Example prompts |
| `SettingsTabs` | tabs, activeTab | Tab navigation |
| `SettingsInfoBox` | type (info/success/error/warning) | Messages, alerts |
| `SearchSortBar` | searchQuery, sortBy | List filtering |
| **`SettingsButton`** | **variant, loading, disabled** | **All buttons** |
| `SettingsButtonGroup` | align | Button containers |
| `SettingsLoadingState` | variant (spinner/empty/generating) | Loading/empty |
| `SettingsCard` | variant, padding | Section containers |
| `SettingsDetailRow` | label, value | Key-value pairs |
| `SettingsPageHeader` | title, description | Page titles |
| `SettingsProgressBar` | value, variant | Progress bars |
| `SettingsBadge` | variant, text | Status pills |
| `SettingsConfirmBlock` | warningText, confirmLabel, checked | Destructive confirms |
| `SettingsCodeBlock` | code, copyable | Monospace display |
| `SettingsAvatar` | src, size | Profile pictures |
| `SettingsBalanceDisplay` | amount, label | Balance display |
| `SettingsDivider` | spacing | Separators |
| `SettingsGradientLink` | href, onClick | Gradient links |
| `SettingsCheckboxList` | options | Multi-select lists |
| `SettingsPageContainer` | maxWidth | Page wrapper |

## Banned Patterns

NEVER use in settings pages:
- Custom `<style>` blocks for layout/component CSS
- `.save-button`, `.delete-button`, `.btn-*` classes
- `@keyframes spin` or custom spinners
- Inline error/warning containers
- Hardcoded hex colors
