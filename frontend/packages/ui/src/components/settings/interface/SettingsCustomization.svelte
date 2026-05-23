<!--
    SettingsCustomization.svelte — Interface customization settings.

    Holds optional playful UI/personality toggles that do not belong to
    language or theme selection. Furry Mode is synced to the account when the
    user is authenticated and mirrored locally for immediate avatar swapping.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { furryModeEnabled, setFurryModeEnabled } from '../../../stores/furryModeStore';
    import { authStore } from '../../../stores/authStore';
    import { updateProfile } from '../../../stores/userProfile';
    import { apiEndpoints, getApiEndpoint } from '../../../config/api';

    async function syncFurryMode(enabled: boolean): Promise<boolean> {
        if (!$authStore.isAuthenticated) return true;

        try {
            const endpoint = getApiEndpoint(apiEndpoints.settings.user.interfacePreferences);
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ furry_mode_enabled: enabled })
            });
            if (!response.ok) {
                console.warn(`[SettingsCustomization] Failed to sync Furry Mode: ${response.status}`);
                return false;
            }
            return true;
        } catch (error) {
            console.warn('[SettingsCustomization] Error syncing Furry Mode:', error);
            return false;
        }
    }

    async function toggleFurryMode() {
        const previousValue = $furryModeEnabled;
        const nextValue = !$furryModeEnabled;
        setFurryModeEnabled(nextValue);
        updateProfile({ furry_mode_enabled: nextValue });
        const synced = await syncFurryMode(nextValue);
        if (!synced) {
            setFurryModeEnabled(previousValue);
            updateProfile({ furry_mode_enabled: previousValue });
        }
    }
</script>

<div class="settings-customization-container" data-testid="interface-customization-settings">
    <SettingsItem
        type="quickaction"
        icon="subsetting_icon mate"
        title={$text('settings.interface.furry_mode')}
        subtitle={$text('settings.interface.furry_mode.description')}
        hasToggle={true}
        checked={$furryModeEnabled}
        onClick={toggleFurryMode}
    />
</div>

<style>
    .settings-customization-container {
        display: flex;
        flex-direction: column;
        gap: 5px;
    }
</style>
