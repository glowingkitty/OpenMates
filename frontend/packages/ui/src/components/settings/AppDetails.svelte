<!-- frontend/packages/ui/src/components/settings/AppDetails.svelte
     Component for displaying details of a specific app, including its skills.
     
     This component is used for the app_store/{app_id} nested route.
     
     **Backend Implementation**:
     - Data source: Static appsMetadata.ts (generated at build time)
     - Store: frontend/packages/ui/src/stores/appSkillsStore.ts
     - Types: frontend/packages/ui/src/types/apps.ts
-->

<script lang="ts">
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { authStore } from '../../stores/authStore';
    import AppStoreCard from './AppStoreCard.svelte';
    import AppEmbedsPanel from './appSettings/AppEmbedsPanel.svelte';
    import SettingsItem from '../SettingsItem.svelte';
    import type { AppMetadata, SkillMetadata, FocusModeMetadata, MemoryFieldMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    
    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();
    
    // Get app ID from the current path
    // The path will be like "app_store/ai" or "app_store/web"
    // This will be passed as a prop from Settings.svelte
    
    interface Props {
        appId: string;
    }
    
    let { appId }: Props = $props();
    
    // Get store state reactively (Svelte 5)
    let storeState = $state(appSkillsStore.getState());
    
    // Check if user is authenticated (for read-only mode)
    let isAuthenticated = $derived($authStore.isAuthenticated);
    
    // Get app metadata from store
    let app = $derived<AppMetadata | undefined>(storeState.apps[appId]);
    let skills = $derived(app?.skills || []);
    let focusModes = $derived(app?.focus_modes || []);
    let memoryFields = $derived(app?.settings_and_memories || []);
    
    /**
     * Get the translated app name.
     * Uses name_translation_key if available, otherwise falls back to name.
     */
    let appName = $derived(
        app?.name_translation_key 
            ? $text(app.name_translation_key)
            : (app?.name || appId)
    );
    
    /**
     * Get the translated app description.
     * Uses description_translation_key if available, otherwise falls back to description.
     */
    let appDescription = $derived(
        app?.description_translation_key 
            ? $text(app.description_translation_key)
            : (app?.description || '')
    );
    
    /**
     * Convert a skill to an app-like metadata object for AppStoreCard.
     * This allows us to reuse AppStoreCard to display skills.
     * 
     * Note: We use the appId (not skill.id) for the id field so that AppStoreCard
     * uses the correct gradient color from the app.
     */
    function skillToAppMetadata(skill: SkillMetadata, appId: string, app: AppMetadata): AppMetadata {
        return {
            id: appId, // Use appId so gradient matches the app
            name_translation_key: skill.name_translation_key,
            description_translation_key: skill.description_translation_key,
            icon_image: app.icon_image,
            icon_colorgradient: app.icon_colorgradient,
            providers: skill.providers || [],
            skills: [],
            focus_modes: [],
            settings_and_memories: []
        };
    }
    
    /**
     * Get icon name from icon_image filename.
     * Maps icon_image like "ai.svg" to icon name "ai" for the Icon component.
     * Also handles special cases:
     * - "coding.svg" -> "code" (since the app ID is "code" but icon file is coding.svg)
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        // Remove .svg extension and return the name
        let iconName = iconImage.replace(/\.svg$/, '');
        // Handle special case: coding.svg -> code (since the app ID is "code" but icon file is coding.svg)
        // This ensures the correct CSS variable --color-app-code is used instead of --color-app-coding
        if (iconName === 'coding') {
            iconName = 'code';
        }
        return iconName;
    }
    
    /**
     * Handle skill card selection - navigate to skill details sub-page.
     */
    function handleSkillSelect(skillId: string) {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/skill/${skillId}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: $text(skills.find(s => s.id === skillId)?.name_translation_key || skillId)
        });
    }
    
    /**
     * Handle focus mode selection - navigate to focus mode details sub-page.
     */
    function handleFocusModeSelect(focusModeId: string) {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/focus/${focusModeId}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: $text(focusModes.find(f => f.id === focusModeId)?.name_translation_key || focusModeId)
        });
    }
    
    /**
     * Handle settings & memories category selection - navigate to category details page.
     */
    function handleSettingsMemoriesCategorySelect(categoryId: string) {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/settings_memories/${categoryId}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: $text(memoryFields.find(c => c.id === categoryId)?.name_translation_key || categoryId)
        });
    }
    
    /**
     * Navigate back to app store.
     */
    function goBack() {
        dispatch('openSettings', {
            settingsPath: 'app_store',
            direction: 'back',
            icon: 'app_store',
            title: 'App Store'
        });
    }
</script>

<div class="app-details">
    {#if !app}
        <div class="error">
            <p>App not found.</p>
            <button class="back-button" onclick={goBack}>← Back to App Store</button>
        </div>
    {:else}
        <!-- App description -->
        <div class="app-header">
            <p class="app-description">{appDescription}</p>
        </div>
        
        <!-- Settings & Memories section - always show cards for each category -->
        {#if memoryFields.length > 0}
            <div class="section">
                <SettingsItem
                    type="heading"
                    icon="settings"
                    title={$text('settings.app_store.settings_memories.title.text')}
                />
                <div class="items-scroll-container">
                    <div class="items-scroll">
                        {#each memoryFields as category (category.id)}
                            {@const categoryApp: AppMetadata = {
                                id: appId,
                                name_translation_key: category.name_translation_key,
                                description_translation_key: category.description_translation_key,
                                icon_image: app.icon_image,
                                icon_colorgradient: app.icon_colorgradient,
                                providers: [],
                                skills: [],
                                focus_modes: [],
                                settings_and_memories: []
                            }}
                            <AppStoreCard app={categoryApp} onSelect={() => handleSettingsMemoriesCategorySelect(category.id)} />
                        {/each}
                    </div>
                </div>
            </div>
        {/if}
        
        <!-- Skills section - only show if skills exist -->
        {#if skills.length > 0}
            <div class="section">
                <SettingsItem 
                    type="heading"
                    icon="skill"
                    title={$text('settings.app_store.skills.title.text')}
                />
                <div class="items-scroll-container">
                    <div class="items-scroll">
                        {#each skills as skill (skill.id)}
                            {@const skillApp = skillToAppMetadata(skill, appId, app)}
                            <AppStoreCard 
                                app={skillApp} 
                                skillProviders={skill.providers}
                                onSelect={() => handleSkillSelect(skill.id)} 
                            />
                        {/each}
                    </div>
                </div>
            </div>
        {/if}
        
        <!-- Focus Modes section - only show if focus modes exist -->
        {#if focusModes.length > 0}
            <div class="section">
                <SettingsItem 
                    type="heading"
                    icon="focus"
                    title={$text('settings.app_store.focus_modes.title.text')}
                />
                <div class="items-scroll-container">
                    <div class="items-scroll">
                        {#each focusModes as focusMode (focusMode.id)}
                            {@const focusModeApp: AppMetadata = {
                                id: appId,
                                name_translation_key: focusMode.name_translation_key,
                                description_translation_key: focusMode.description_translation_key,
                                icon_image: app.icon_image,
                                icon_colorgradient: app.icon_colorgradient,
                                providers: [],
                                skills: [],
                                focus_modes: [],
                                settings_and_memories: []
                            }}
                            <AppStoreCard app={focusModeApp} onSelect={() => handleFocusModeSelect(focusMode.id)} />
                        {/each}
                    </div>
                </div>
            </div>
        {/if}
        
        <!-- My Embeds section - show all embeds generated by this app -->
        {#if isAuthenticated}
            <div class="section">
                <SettingsItem
                    type="heading"
                    icon="embed"
                    title={'My embeds'}
                />
                <div class="embeds-preview">
                    <AppEmbedsPanel appId={appId} />
                </div>
            </div>
        {/if}
    {/if}
</div>

<style>
    .app-details {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .app-header {
        margin-bottom: 2rem;
        padding-left: 0;
    }
    
    .app-description {
        margin: 0;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
        text-align: left;
    }
    
    .section {
        margin-top: 2rem;
        padding-left: 0;
    }
    
    /* Ensure SettingsItem headings align with description text */
    .section :global(.menu-item.heading) {
        padding-left: 0;
        padding-right: 0;
    }
    
    /* Ensure items scroll container aligns with description */
    .section :global(.items-scroll-container) {
        margin-left: 0;
    }

    .embeds-preview {
        margin-top: 0.5rem;
        padding: 1rem;
        background: var(--color-grey-10);
        border-radius: 8px;
        border: 1px solid var(--color-grey-20);
    }

    .error {
        padding: 2rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
    
    .items-scroll-container {
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 0.5rem;
        padding-left: 0;
        margin-top: 0.5rem;
        /* Match settings menu scrollbar style */
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }
    
    .items-scroll-container:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }
    
    .items-scroll-container::-webkit-scrollbar {
        height: 8px;
    }
    
    .items-scroll-container::-webkit-scrollbar-track {
        background: transparent;
    }
    
    .items-scroll-container::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid var(--color-grey-20);
        transition: background-color 0.2s ease;
    }
    
    .items-scroll-container:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }
    
    .items-scroll-container::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }
    
    .items-scroll {
        display: flex;
        gap: 1rem;
        padding-right: 1rem;
        min-width: min-content;
    }
    
    .back-button {
        background: var(--button-background, #f0f0f0);
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: 6px;
        padding: 0.5rem 1rem;
        margin-top: 1rem;
        cursor: pointer;
        font-size: 0.9rem;
        color: var(--text-primary, #000000);
        transition: background 0.2s ease;
    }
    
    .back-button:hover {
        background: var(--button-hover-background, #e0e0e0);
    }
</style>

