/**
 * Settings UI Elements — Barrel export for all shared settings components.
 *
 * These components implement all canonical settings UI element types from
 * the Figma "settings_menu_elements" design system (node 4944-31418).
 * Combined with SettingsItem (which handles the 5 menu row types) and
 * SearchSortBar, they cover every visual element allowed on settings pages.
 *
 * Usage:
 *   import { SettingsInput, SettingsButton, SettingsCard } from '../settings/elements';
 *
 * Preview: /dev/preview/settings
 * Guidelines: docs/architecture/settings-ui.md
 * Design reference: Figma "settings_menu_elements" frame
 */

// ── Form Elements (original 8) ──────────────────────────────────────
export { default as SettingsInput } from "./SettingsInput.svelte";
export { default as SettingsTextarea } from "./SettingsTextarea.svelte";
export { default as SettingsDropdown } from "./SettingsDropdown.svelte";
export { default as SettingsFileUpload } from "./SettingsFileUpload.svelte";
export { default as SettingsConsentToggle } from "./SettingsConsentToggle.svelte";
export { default as SettingsQuote } from "./SettingsQuote.svelte";
export { default as SettingsTabs } from "./SettingsTabs.svelte";
export { default as SettingsInfoBox } from "./SettingsInfoBox.svelte";

// ── Action & Layout ─────────────────────────────────────────────────
export { default as SettingsButton } from "./SettingsButton.svelte";
export { default as SettingsButtonGroup } from "./SettingsButtonGroup.svelte";
export { default as SettingsPageContainer } from "./SettingsPageContainer.svelte";
export { default as SettingsPageHeader } from "./SettingsPageHeader.svelte";
export { default as SettingsDivider } from "./SettingsDivider.svelte";
export { default as SettingsSectionHeading } from "./SettingsSectionHeading.svelte";
export { default as SettingsGradientLink } from "./SettingsGradientLink.svelte";

// ── Data Display ────────────────────────────────────────────────────
export { default as SettingsCard } from "./SettingsCard.svelte";
export { default as SettingsDetailRow } from "./SettingsDetailRow.svelte";
export { default as SettingsBalanceDisplay } from "./SettingsBalanceDisplay.svelte";
export { default as SettingsCodeBlock } from "./SettingsCodeBlock.svelte";
export { default as SettingsProgressBar } from "./SettingsProgressBar.svelte";
export { default as SettingsBadge } from "./SettingsBadge.svelte";

// ── Feedback & Interaction ──────────────────────────────────────────
export { default as SettingsLoadingState } from "./SettingsLoadingState.svelte";
export { default as SettingsConfirmBlock } from "./SettingsConfirmBlock.svelte";
export { default as SettingsAvatar } from "./SettingsAvatar.svelte";
export { default as SettingsCheckboxList } from "./SettingsCheckboxList.svelte";

// ── Menu Rows ───────────────────────────────────────────────────────
export { default as SettingsItem } from "./SettingsItem.svelte";
