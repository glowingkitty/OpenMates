<!-- frontend/packages/ui/src/components/settings/SettingsAllApps.svelte
     All Apps view — shows every available app in a filterable, sortable grid.
     
     Features:
     - Filter chips: All, Settings & Memories, Focus Modes, Skills
     - SearchSortBar: text search + sort (Newest, Name A–Z, Name Z–A)
     - Vertical auto-fill grid of AppStoreCards
     
     When navigated to with allAppsInitialFilter set (e.g. from the root
     "Settings & Memories" menu item), the filter is pre-selected on mount.
     
     Architecture: See docs/architecture/app-skills.md
     Navigation: clicking a card dispatches 'openSettings' → Settings.svelte
     navigates to app_store/{appId}, passing cameFrom='app_store/all' so
     the back button returns here instead of the App Store root.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { allAppsInitialFilter, type AllAppsFilterType } from '../../stores/allAppsFilterStore';
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

    // --- Filter state ---
    let activeFilter = $state<AllAppsFilterType>('all');

    // --- Search / sort state (owned here, passed as bindable to SearchSortBar) ---
    let searchQuery = $state('');
    let sortBy = $state<'newest' | 'name_asc' | 'name_desc'>('newest');

    // --- Derived sort options (reactive to language changes) ---
    let sortOptions = $derived([
        { value: 'newest',    label: $text('settings.app_store.all_apps.sort_by_newest') },
        { value: 'name_asc',  label: $text('settings.app_store.all_apps.sort_by_name_asc') },
        { value: 'name_desc', label: $text('settings.app_store.all_apps.sort_by_name_desc') },
    ]);

    // --- Filter options for the SearchSortBar dropdown (reactive to language changes) ---
    let filterOptions = $derived([
        { value: 'all',               label: $text('settings.app_store.all_apps.filter_all') },
        { value: 'settings_memories', label: $text('settings.app_store.all_apps.filter_settings_memories') },
        { value: 'focus_modes',       label: $text('settings.app_store.all_apps.filter_focus_modes') },
        { value: 'skills',            label: $text('settings.app_store.all_apps.filter_skills') },
    ]);

    /**
     * Read the initial filter from the store on mount, then reset it.
     * This allows the settings_memories menu item (or others) to pre-select a filter
     * without leaving stale state for subsequent visits.
     */
    onMount(() => {
        const unsubscribe = allAppsInitialFilter.subscribe((value) => {
            if (value !== 'all') {
                activeFilter = value;
            }
        });
        // Read once, then reset
        allAppsInitialFilter.set('all');
        unsubscribe();
    });

    /**
     * Filter apps by the active capability filter chip.
     * Returns only apps that have the selected capability (non-empty array).
     */
    function matchesCapabilityFilter(app: AppMetadata): boolean {
        switch (activeFilter) {
            case 'settings_memories':
                return (app.settings_and_memories?.length ?? 0) > 0;
            case 'focus_modes':
                return (app.focus_modes?.length ?? 0) > 0;
            case 'skills':
                return (app.skills?.length ?? 0) > 0;
            case 'all':
            default:
                return true;
        }
    }

    /**
     * Filter apps by search query (name, description, or provider names, case-insensitive),
     * apply the active capability filter, then sort by the selected sort option.
     * Uses i18n-translated app names/descriptions from the text store.
     * Provider matching lets users find apps by typing e.g. "Anthropic" or "Google".
     */
    let filteredAndSorted = $derived.by((): AppMetadata[] => {
        let list = [...appsList];

        // Apply capability filter first
        list = list.filter(matchesCapabilityFilter);

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
                // Also match against provider names (e.g. "Anthropic", "Google")
                const providers = (app.providers || []).join(' ').toLowerCase();
                return name.includes(query) || desc.includes(query) || providers.includes(query);
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
    <!-- Search, filter, and sort controls -->
    <div class="controls-bar">
        <SearchSortBar
            bind:searchQuery
            bind:sortBy
            bind:filterBy={activeFilter}
            searchPlaceholder={$text('settings.app_store.all_apps.search_placeholder')}
            {sortOptions}
            {filterOptions}
        />
    </div>

    {#if appsList.length === 0}
        <!-- No apps at all (store not loaded yet or empty) -->
        <div class="no-apps">
            <p>{$text('settings.app_store.no_apps_available')}</p>
        </div>
    {:else if filteredAndSorted.length === 0}
        <!-- Search/filter returned no results -->
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

    /* Search/sort/filter bar sits above the grid with a bottom margin */
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
