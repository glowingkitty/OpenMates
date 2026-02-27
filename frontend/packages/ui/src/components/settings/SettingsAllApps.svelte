<!-- frontend/packages/ui/src/components/settings/SettingsAllApps.svelte
     All Apps view — shows every available app in a filterable, sortable grid.
     
     Features:
     - SearchSortBar at the top (shared component also used by AiAskSkillSettings)
     - Filter by app name or description text
     - Sort: Newest (default), Name A–Z, Name Z–A
     - Vertical auto-fill grid of AppStoreCards
     
     Navigation: clicking a card dispatches 'openSettings' → Settings.svelte
     navigates to app_store/{appId}, passing cameFrom='app_store/all' so
     the back button returns here instead of the App Store root.
-->

<script lang="ts">
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import type { AppMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import AppStoreCard from './AppStoreCard.svelte';
    import SearchSortBar from './SearchSortBar.svelte';

    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();

    // --- Store state ---
    // Access the store state directly — static data loaded at build time
    let storeState = $state(appSkillsStore.getState());

    let apps = $derived(storeState.apps);
    let appsList = $derived(Object.values(apps));

    // --- Search / sort state (owned here, passed as bindable to SearchSortBar) ---
    let searchQuery = $state('');
    let sortBy = $state<'newest' | 'name_asc' | 'name_desc'>('newest');

    // --- Derived sort options (reactive to language changes) ---
    let sortOptions = $derived([
        { value: 'newest',    label: $text('settings.app_store.all_apps.sort_by_newest') },
        { value: 'name_asc',  label: $text('settings.app_store.all_apps.sort_by_name_asc') },
        { value: 'name_desc', label: $text('settings.app_store.all_apps.sort_by_name_desc') },
    ]);

    /**
     * Filter apps by search query (name or description, case-insensitive),
     * then sort by the selected sort option.
     * Uses i18n-translated app names/descriptions from the text store.
     */
    let filteredAndSorted = $derived.by((): AppMetadata[] => {
        let list = [...appsList];

        // Filter by search query
        const query = searchQuery.trim().toLowerCase();
        if (query) {
            list = list.filter(app => {
                const name = app.name_translation_key
                    ? $text(app.name_translation_key).toLowerCase()
                    : (app.name || '').toLowerCase();
                const desc = app.description_translation_key
                    ? $text(app.description_translation_key).toLowerCase()
                    : '';
                return name.includes(query) || desc.includes(query);
            });
        }

        // Sort
        list.sort((a, b) => {
            switch (sortBy) {
                case 'name_asc': {
                    const nameA = a.name_translation_key ? $text(a.name_translation_key) : (a.name || '');
                    const nameB = b.name_translation_key ? $text(b.name_translation_key) : (b.name || '');
                    return nameA.localeCompare(nameB);
                }
                case 'name_desc': {
                    const nameA = a.name_translation_key ? $text(a.name_translation_key) : (a.name || '');
                    const nameB = b.name_translation_key ? $text(b.name_translation_key) : (b.name || '');
                    return nameB.localeCompare(nameA);
                }
                case 'newest':
                default: {
                    const dateA = a.last_updated ? new Date(a.last_updated).getTime() : 0;
                    const dateB = b.last_updated ? new Date(b.last_updated).getTime() : 0;
                    return dateB - dateA;
                }
            }
        });

        return list;
    });

    /**
     * Navigate to the app's detail page.
     * Passes cameFrom so the back button returns to All Apps instead of the App Store root.
     */
    function selectApp(appId: string) {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}`,
            direction: 'forward',
            icon: appId,
            title: apps[appId]?.name || appId,
            cameFrom: 'app_store/all',
        });
    }
</script>

<div class="settings-all-apps">
    <!-- Search and sort controls -->
    <div class="controls-bar">
        <SearchSortBar
            bind:searchQuery
            bind:sortBy
            searchPlaceholder={$text('settings.app_store.all_apps.search_placeholder')}
            {sortOptions}
        />
    </div>

    {#if appsList.length === 0}
        <!-- No apps at all (store not loaded yet or empty) -->
        <div class="no-apps">
            <p>{$text('settings.app_store.no_apps_available')}</p>
        </div>
    {:else if filteredAndSorted.length === 0}
        <!-- Search returned no results -->
        <div class="no-apps">
            <p>{$text('settings.app_store.all_apps.no_apps_found')}</p>
        </div>
    {:else}
        <!-- Vertical grid layout for all apps -->
        <div class="apps-grid">
            {#each filteredAndSorted as app (app.id)}
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

    /* Search/sort bar sits above the grid with a bottom margin */
    .controls-bar {
        padding: 0 0 1rem 0;
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
        justify-items: center;
    }
</style>
