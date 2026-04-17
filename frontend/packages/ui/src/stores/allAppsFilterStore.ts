/**
 * Store for passing an initial filter to the All Apps page (SettingsAllApps.svelte).
 *
 * Used when navigating from the root Settings menu — e.g. the "Memories"
 * item sets filter to 'settings_memories' before opening app_store/all, so the page
 * lands pre-filtered to show only apps that define memories categories.
 *
 * Architecture: See docs/architecture/app-skills.md
 * Tests: (none yet)
 */
import { writable } from 'svelte/store';

/**
 * Available capability filter types:
 * - 'all'               — no filter (show every app)
 * - 'settings_memories' — apps with settings_and_memories defined
 * - 'focus_modes'       — apps with focus_modes defined
 * - 'skills'            — apps with skills defined
 */
export type AllAppsFilterType = 'all' | 'settings_memories' | 'focus_modes' | 'skills';

/**
 * Writable store holding the initial filter value.
 * Set before navigating to app_store/all; SettingsAllApps reads it on mount
 * then resets it to 'all' so subsequent visits start unfiltered.
 */
export const allAppsInitialFilter = writable<AllAppsFilterType>('all');
