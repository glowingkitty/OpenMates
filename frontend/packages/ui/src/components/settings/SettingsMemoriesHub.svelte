<!-- frontend/packages/ui/src/components/settings/SettingsMemoriesHub.svelte
     Hub page listing all memories entries across all apps the user has created.
     Provides a single place to browse and manage them, with a deep link to the Apps
     for discovering new apps that support memories.

     Architecture: See docs/architecture/app-skills.md
     Route: settings_memories (top-level, shown in sidebar nav); settings_memories/create and
            settings_memories/<id> (or memories/<id> deep links) show only the memory's own page.
     Navigation: Clicking a category navigates to apps/{appId}/settings_memories/{categoryId}
                 with cameFrom='settings_memories' so back-navigation returns here.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { authStore } from '../../stores/authStore';
    import SettingsItem from './elements/SettingsItem.svelte';
    import { SettingsSectionHeading, SettingsPageContainer } from './elements';
    import AppStoreCard from './AppStoreCard.svelte';
    import type { AppMetadata } from '../../types/apps';
    import { text } from '@repo/ui';
    import { allAppsInitialFilter } from '../../stores/allAppsFilterStore';

    import MemoriesEditor, { type MemoryEditorView } from './MemoriesEditor.svelte';
    import { defaultMemoryEditorService, recommendationMemoryEditorService } from '../../services/memoryEditorService';
    import { memoryDraftSuggestion } from '../../stores/memoryDraftSuggestionStore';

    /**
     * Route: settings_memories (list), settings_memories/create, or settings_memories/<memory id>
     * (also reached as memories/<id> by deep links from chat rows, recommendations and mentions).
     */
    let { activeSettingsView = 'settings_memories' }: { activeSettingsView?: string } = $props();
    let deepLinkMemoryId = $derived(
        decodeURIComponent(activeSettingsView.split('&')[0].match(/^(?:settings_memories|memories)\/([^/]+)$/)?.[1] ?? '') || null,
    );
    let editorView = $derived<MemoryEditorView>(
        deepLinkMemoryId === 'create' ? { kind: 'create' }
            : deepLinkMemoryId ? { kind: 'entry', id: deepLinkMemoryId } : { kind: 'list' },
    );
    // Only a draft addressed to the opened memory is shown; it stays unsaved.
    let deepLinkSuggestion = $derived(
        $memoryDraftSuggestion && $memoryDraftSuggestion.id === deepLinkMemoryId
            ? { title: $memoryDraftSuggestion.title, memory: $memoryDraftSuggestion.memory, when_to_use: $memoryDraftSuggestion.when_to_use,
                load_mode: $memoryDraftSuggestion.load_mode, valid_from: $memoryDraftSuggestion.valid_from, valid_until: $memoryDraftSuggestion.valid_until,
                app_id: $memoryDraftSuggestion.app_id, is_new: $memoryDraftSuggestion.is_new, base_document: $memoryDraftSuggestion.base_document }
            : null,
    );
    // A draft opened from a chat Recommendation resolves it when saved.
    let memoriesService = $derived(
        deepLinkSuggestion && $memoryDraftSuggestion?.origin
            ? recommendationMemoryEditorService($memoryDraftSuggestion.origin)
            : defaultMemoryEditorService,
    );

    const dispatch = createEventDispatcher();

    // Authenticated users see encrypted entries; guests see read-only examples.
    let isAuthenticated = $derived($authStore.isAuthenticated);

    // Store state
    let storeState = $state(appSkillsStore.getState());

    /**
     * Build a flat list of app+category combinations.
     * Authenticated users see categories with saved entries. Guests see categories
     * that ship example entries, so the Memories menu can be explored read-only.
     */
    interface HubCategory {
        id: string;
        name_translation_key: string;
        description_translation_key: string;
        icon_image?: string;
    }

    interface HubEntry {
        app: AppMetadata;
        category: HubCategory;
        published?: import('../../types/apps').PublishedAppMemory;
        entryCount: number;
        lastUpdated: number; // Unix seconds for sorting
    }

    let hubEntries = $derived.by((): HubEntry[] => {
        const result: HubEntry[] = [];
        const apps = storeState.apps;

        // Only public app Memories are listed here; app-specific typed memories were removed.
        for (const appId of Object.keys(apps)) {
            const app = apps[appId];
            for (const memory of app.memories ?? []) {
                result.push({ app, published: memory, category: { id: `published_${memory.id.split(':').at(-1)}`,
                    name_translation_key: '', description_translation_key: '' }, entryCount: 1, lastUpdated: 0 });
            }
        }

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
            settingsPath: `apps/${app.id}/settings_memories/${categoryId}`,
            direction: 'forward',
            icon: getAppIconName(app.icon_image, app.id),
            title: categoryName,
            cameFrom: 'settings_memories',
            cameFromTitle: $text('settings.settings_memories'),
        });
    }

    /**
     * Memory subpages live under settings_memories/ so the header Back button returns to this list.
     */
    function navigateMemories(view: MemoryEditorView, title: string) {
        const settingsTitle = $text('settings.settings_memories');
        dispatch('openSettings', view.kind === 'list'
            ? { settingsPath: 'settings_memories', direction: 'backward', icon: 'settings_memories', title: settingsTitle }
            : {
                settingsPath: view.kind === 'create' ? 'settings_memories/create' : `settings_memories/${encodeURIComponent(view.id)}`,
                direction: 'forward', icon: 'settings_memories', title: title || settingsTitle,
            });
    }

    /**
     * Navigate to All Apps with the "Memories" filter pre-set,
     * so the user sees only apps that define memories categories.
     */
    function openAppStore() {
        allAppsInitialFilter.set('settings_memories');
        dispatch('openSettings', {
            settingsPath: 'apps/all',
            direction: 'forward',
            icon: 'app',
            title: $text('settings.app_store.show_all_apps'),
            cameFrom: 'settings_memories',
            cameFromTitle: $text('settings.settings_memories'),
        });
    }
</script>

<SettingsPageContainer maxWidth="wide">
{#if editorView.kind !== 'list'}
    {#if isAuthenticated}
        <MemoriesEditor source="personal" projectId={null} service={memoriesService} view={editorView}
            suggestion={deepLinkSuggestion} onNavigate={navigateMemories} />
    {/if}
{:else}
<div class="settings-memories-hub">
    <p class="encryption-notice">{$text('memories.sources_help')}</p>

    {#if isAuthenticated}
        <div data-testid="settings-memories-private">
            <SettingsSectionHeading title={$text('memories.private_memories')} icon="settings_memories" />
            <MemoriesEditor source="personal" projectId={null} service={memoriesService} view={editorView}
                suggestion={null} onNavigate={navigateMemories} />
        </div>
    {/if}

    {#if appSections.length === 0}
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
                                : entry.published?.title ?? entry.category.id}
                            {@const categoryApp: AppMetadata = {
                                id: entry.app.id,
                                name_translation_key: entry.category.name_translation_key,
                                name: entry.published?.title,
                                description_translation_key: entry.category.description_translation_key,
                                description: entry.published?.description,
                                icon_image: entry.category.icon_image || entry.app.icon_image,
                                icon_colorgradient: entry.app.icon_colorgradient,
                                providers: [],
                                skills: [],
                                focus_modes: []
                            }}
                            <AppStoreCard
                                app={categoryApp}
                                cardIconType="memory"
                                memoryVisibility={entry.published ? 'public' : 'private'}
                                testId={entry.published ? `published-memory-${entry.app.id}-${entry.category.id}` : `private-memory-${entry.app.id}-${entry.category.id}`}
                                onSelect={() => openCategory(entry.app, entry.category.id, categoryName)}
                            />
                        {/each}
                    </div>
                </div>
            </div>
        {/each}
    {/if}

    <!-- Footer: deep link to Apps -->
    <div class="discover-link-section">
        <SettingsItem
            type="submenu"
            icon="app"
            title={$text('settings.app_store.settings_memories.discover_link')}
            onClick={openAppStore}
        />
    </div>
</div>
{/if}
</SettingsPageContainer>

<style>
    .settings-memories-hub {
        padding: 14px;
        width: 100%;
        min-width: 0;
        box-sizing: border-box;
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
        border-top: 1px solid var(--color-grey-20);
    }

    .discover-link-section {
        margin-top: 1.5rem;
        padding-top: 0.5rem;
        border-top: 1px solid var(--color-grey-20);
    }
</style>
