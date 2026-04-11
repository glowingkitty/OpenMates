<!-- frontend/packages/ui/src/components/settings/SettingsMemoriesHub.svelte
     Hub page listing all settings & memories entries across all apps the user has created.
     Provides a single place to browse and manage them, with a deep link to the App Store
     for discovering new apps that support settings & memories.

     Architecture: See docs/architecture/app-skills.md
     Route: settings_memories (top-level, shown in sidebar nav)
     Navigation: Clicking a category navigates to app_store/{appId}/settings_memories/{categoryId}
                 with cameFrom='settings_memories' so back-navigation returns here.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { createEventDispatcher } from 'svelte';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { authStore } from '../../stores/authStore';
    import { appSettingsMemoriesStore } from '../../stores/appSettingsMemoriesStore';
    import SettingsItem from '../SettingsItem.svelte';
    import { SettingsSectionHeading } from './elements';
    import AppStoreCard from './AppStoreCard.svelte';
    import type { AppMetadata, MemoryFieldMetadata } from '../../types/apps';
    import { text } from '@repo/ui';
    import { allAppsInitialFilter } from '../../stores/allAppsFilterStore';

    const dispatch = createEventDispatcher();

    // Auth state — hub only shows entries for authenticated users
    let isAuthenticated = $derived($authStore.isAuthenticated);

    // Store state
    let storeState = $state(appSkillsStore.getState());
    let memoriesStoreState = $derived($appSettingsMemoriesStore);
    let isLoading = $state(false);

    /**
     * Build a flat list of { app, category, entryCount } for all app+category combinations
     * that have at least one user entry. Sorted by most recently updated entry first.
     */
    interface HubEntry {
        app: AppMetadata;
        category: MemoryFieldMetadata;
        entryCount: number;
        lastUpdated: number; // Unix seconds for sorting
    }

    let hubEntries = $derived.by((): HubEntry[] => {
        const result: HubEntry[] = [];
        const apps = storeState.apps;
        const entriesByApp = memoriesStoreState.entriesByApp;

        for (const appId of Object.keys(apps)) {
            const app = apps[appId];
            if (!app.settings_and_memories || app.settings_and_memories.length === 0) continue;

            const appEntriesMap = entriesByApp.get(appId);
            if (!appEntriesMap) continue;

            for (const category of app.settings_and_memories) {
                const categoryEntries = appEntriesMap[category.id];
                if (!categoryEntries || categoryEntries.length === 0) continue;

                // Find the most recently updated entry in this category
                const lastUpdated = categoryEntries.reduce(
                    (max, e) => Math.max(max, (e as { updated_at: number }).updated_at ?? 0),
                    0
                );

                result.push({
                    app,
                    category,
                    entryCount: categoryEntries.length,
                    lastUpdated,
                });
            }
        }

        // Sort: most recently updated category first
        result.sort((a, b) => b.lastUpdated - a.lastUpdated);
        return result;
    });

    /**
     * Group hub entries by app for display — each app becomes a section heading
     * followed by its category rows.
     */
    interface AppSection {
        app: AppMetadata;
        categories: HubEntry[];
    }

    let appSections = $derived.by((): AppSection[] => {
        const byApp = new Map<string, AppSection>();

        for (const entry of hubEntries) {
            const appId = entry.app.id;
            if (!byApp.has(appId)) {
                byApp.set(appId, { app: entry.app, categories: [] });
            }
            byApp.get(appId)!.categories.push(entry);
        }

        return Array.from(byApp.values());
    });

    /**
     * Load all app settings/memories entries on mount.
     * Uses loadEntries() (not loadEntriesForApp) to fetch across all apps at once.
     */
    onMount(async () => {
        if (!isAuthenticated) return;
        isLoading = true;
        try {
            await appSettingsMemoriesStore.loadEntries();
        } catch (err) {
            console.error('[SettingsMemoriesHub] Error loading entries:', err);
        } finally {
            isLoading = false;
        }
    });

    /**
     * Normalise icon_image filename to the icon name used by the Icon component.
     * Handles special cases (coding→code, heart→health).
     */
    function getAppIconName(iconImage: string | undefined, appId: string): string {
        if (!iconImage) return appId;
        let name = iconImage.replace(/\.svg$/, '');
        if (name === 'coding') name = 'code';
        if (name === 'heart') name = 'health';
        return name;
    }

    /**
     * Navigate to the per-category settings/memories page for an app.
     * Passes cameFrom='settings_memories' so that back navigation from the category page
     * returns here instead of the parent app settings page.
     */
    function openCategory(app: AppMetadata, categoryId: string, categoryName: string) {
        dispatch('openSettings', {
            settingsPath: `app_store/${app.id}/settings_memories/${categoryId}`,
            direction: 'forward',
            icon: getAppIconName(app.icon_image, app.id),
            title: categoryName,
            cameFrom: 'settings_memories',
            cameFromTitle: $text('settings.settings_memories'),
        });
    }

    /**
     * Navigate to All Apps with the "Settings & Memories" filter pre-set,
     * so the user sees only apps that define settings & memories categories.
     */
    function openAppStore() {
        allAppsInitialFilter.set('settings_memories');
        dispatch('openSettings', {
            settingsPath: 'app_store/all',
            direction: 'forward',
            icon: 'app_store',
            title: $text('settings.app_store.show_all_apps'),
            cameFrom: 'settings_memories',
            cameFromTitle: $text('settings.settings_memories'),
        });
    }
</script>

<div class="settings-memories-hub">
    <p class="encryption-notice">{$text('settings.app_settings_memories.encryption_notice')}</p>

    {#if !isAuthenticated}
        <!-- Non-authenticated users: prompt to sign in -->
        <div class="empty-state">
            <p class="empty-text">{$text('settings.app_settings_memories.authentication_required')}</p>
        </div>
    {:else if isLoading}
        <div class="loading-state">
            <p>{$text('settings.app_settings_memories.loading')}</p>
        </div>
    {:else if appSections.length === 0}
        <!-- No entries yet -->
        <div class="empty-state">
            <p class="empty-text">{$text('settings.app_store.settings_memories.hub_no_entries')}</p>
        </div>
    {:else}
        <!-- One section per app that has entries -->
        {#each appSections as section, sectionIndex (section.app.id)}
            <!-- Spacing between app sections (not before the first one) -->
            <div class="app-section" class:section-gap={sectionIndex > 0}>
                <!-- App section heading — uses canonical SettingsSectionHeading with app-specific gradient icon -->
                <SettingsSectionHeading
                    title={section.app.name_translation_key ? $text(section.app.name_translation_key) : section.app.id}
                    icon={section.app.id}
                    iconClass="icon settings_size app-{section.app.id}"
                />

                <!-- Category cards for this app -->
                <div class="items-scroll-container">
                    <div class="items-scroll">
                        {#each section.categories as entry (entry.category.id)}
                            {@const categoryName = entry.category.name_translation_key
                                ? $text(entry.category.name_translation_key)
                                : entry.category.id}
                            {@const categoryApp: AppMetadata = {
                                id: entry.app.id,
                                name_translation_key: entry.category.name_translation_key,
                                description_translation_key: entry.category.description_translation_key,
                                icon_image: entry.category.icon_image || entry.app.icon_image,
                                icon_colorgradient: entry.app.icon_colorgradient,
                                providers: [],
                                skills: [],
                                focus_modes: [],
                                settings_and_memories: []
                            }}
                            <AppStoreCard
                                app={categoryApp}
                                cardIconType="memory"
                                onSelect={() => openCategory(entry.app, entry.category.id, categoryName)}
                            />
                        {/each}
                    </div>
                </div>
            </div>
        {/each}
    {/if}

    <!-- Footer: deep link to App Store -->
    <div class="discover-link-section">
        <SettingsItem
            type="submenu"
            icon="app_store"
            title={$text('settings.app_store.settings_memories.discover_link')}
            onClick={openAppStore}
        />
    </div>
</div>

<style>
    .settings-memories-hub {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }

    .encryption-notice {
        color: var(--color-font-secondary);
        font-size: 0.9rem;
        line-height: 1.5;
        margin: 0 0 1rem 0;
        padding: 0 0.5rem;
    }

    .empty-state {
        padding: 1.5rem 0.5rem;
    }

    .empty-text {
        color: var(--color-font-secondary);
        font-size: 0.9rem;
        line-height: 1.5;
        margin: 0;
    }

    .loading-state {
        padding: 1rem 0.5rem;
        color: var(--color-font-secondary);
        font-size: 0.9rem;
    }


    .items-scroll-container {
        overflow-x: auto;
        overflow-y: hidden;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
        margin-top: 0.5rem;
    }

    .items-scroll-container::-webkit-scrollbar {
        display: none;
    }

    .items-scroll {
        display: flex;
        gap: var(--spacing-6);
        padding: 4px 0;
    }

    .app-section.section-gap {
        margin-top: 1.5rem;
        padding-top: 0.5rem;
        border-top: 1px solid var(--color-grey-15, var(--color-grey-20));
    }

    .discover-link-section {
        margin-top: 1.5rem;
        padding-top: 0.5rem;
        border-top: 1px solid var(--color-grey-15, var(--color-grey-20));
    }
</style>
