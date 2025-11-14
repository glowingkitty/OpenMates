<!-- frontend/packages/ui/src/components/settings/SettingsAllApps.svelte
     All Apps view - shows all apps in a vertical list layout, sorted by date.
     
     This is a submenu of the App Store that displays all available apps
     in a vertical grid layout instead of horizontal scrollable categories.
-->

<script lang="ts">
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import type { AppMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    // @ts-expect-error - Svelte components are default exports
    import AppStoreCard from './AppStoreCard.svelte';
    
    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();
    
    // Use $state() for reactive state (Svelte 5)
    // Access the store state directly - the store is a singleton with static data
    // that's loaded at build time, so this pattern works correctly
    let storeState = $state(appSkillsStore.getState());
    
    // Reactive derived values
    let apps = $derived(storeState.apps);
    let appsList = $derived(Object.values(apps));
    
    /**
     * Get all apps sorted by last_updated date (newest first).
     */
    function getAllAppsSorted(): AppMetadata[] {
        return appsList
            .map(app => ({
                app,
                date: app.last_updated ? new Date(app.last_updated).getTime() : 0
            }))
            .sort((a, b) => b.date - a.date) // Sort newest first
            .map(({ app }) => app);
    }
    
    /**
     * Navigate to app details page.
     * This dispatches an event to the parent Settings component to navigate to app_store/{appId}.
     */
    function selectApp(appId: string) {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}`,
            direction: 'forward',
            icon: appId,
            title: apps[appId]?.name || appId
        });
    }
    
    let allAppsSorted = $derived(getAllAppsSorted());
</script>

<div class="settings-all-apps">
    {#if appsList.length === 0}
        <div class="no-apps">
            <p>{$text('settings.app_store.no_apps_available')}</p>
        </div>
    {:else}
        <!-- Vertical grid layout for all apps -->
        <div class="apps-grid">
            {#each allAppsSorted as app (app.id)}
                <AppStoreCard {app} onSelect={selectApp} />
            {/each}
        </div>
    {/if}
</div>

<style>
    .settings-all-apps {
        padding: 1rem 0 3rem 0;
        max-width: 1400px;
        margin: 0 auto;
        min-height: fit-content;
    }
    
    .no-apps {
        padding: 3rem;
        text-align: center;
        color: var(--text-secondary, #666666);
    }
    
    .apps-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(223px, 1fr));
        gap: 1rem;
        padding: 0;
        justify-items: center; /* Center the app cards */
    }
</style>

