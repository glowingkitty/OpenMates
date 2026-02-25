<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml

-->

<script lang="ts">
    // SettingsDarkMode.svelte
    // Dark mode sub-page in Interface settings.
    //
    // Presents three options:
    //   Auto  — follows OS prefers-color-scheme (default)
    //   Light — always light mode
    //   Dark  — always dark mode
    //
    // For unauthenticated users the preference is stored in localStorage only.
    // For authenticated users it is also synced to the backend via
    // POST /v1/settings/user/darkmode so the preference is preserved
    // cross-device on login.

    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { themeMode, setThemeMode } from '../../../stores/theme';
    import { authStore } from '../../../stores/authStore';
    import { createEventDispatcher } from 'svelte';

    const dispatch = createEventDispatcher();

    // The three available mode options.
    type ThemeMode = 'auto' | 'light' | 'dark';

    const modes: Array<{ value: ThemeMode; labelKey: string; descKey: string; icon: string }> = [
        {
            value: 'auto',
            labelKey: 'interface.dark_mode.auto',
            descKey: 'interface.dark_mode.auto.description',
            icon: 'subsetting_icon settings',
        },
        {
            value: 'light',
            labelKey: 'interface.dark_mode.light',
            descKey: 'interface.dark_mode.light.description',
            icon: 'subsetting_icon light_mode',
        },
        {
            value: 'dark',
            labelKey: 'interface.dark_mode.dark',
            descKey: 'interface.dark_mode.dark.description',
            icon: 'subsetting_icon dark_mode',
        },
    ];

    async function handleModeChange(mode: ThemeMode) {
        // Skip if already selected.
        if (mode === $themeMode) return;

        // Sync to server only when the user is authenticated and selecting a
        // manual mode (light/dark). Auto is a client-only concept.
        const syncToServer = $authStore.isAuthenticated && mode !== 'auto';
        await setThemeMode(mode, syncToServer);

        // Dispatch event so the parent (SettingsInterface) can navigate back.
        dispatch('darkModeChanged', { mode });
    }
</script>

<div class="settings-dark-mode-container">
    {#each modes as modeOption}
        <SettingsItem
            type="quickaction"
            icon={modeOption.icon}
            title={$text(modeOption.labelKey)}
            subtitle={$text(modeOption.descKey)}
            hasToggle={true}
            checked={$themeMode === modeOption.value}
            onClick={() => handleModeChange(modeOption.value)}
        />
    {/each}
</div>

<style>
    .settings-dark-mode-container {
        display: flex;
        flex-direction: column;
        gap: 5px;
    }
</style>
