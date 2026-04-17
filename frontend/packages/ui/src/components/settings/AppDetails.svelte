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
    import ActiveRemindersList from './appSettings/ActiveRemindersList.svelte';
    import SettingsItem from '../SettingsItem.svelte';
    import { SettingsSectionHeading } from './elements';
    import type { AppMetadata, SkillMetadata } from '../../types/apps';
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
     * Convert a skill to an app-like metadata object for AppStoreCard.
     * This allows us to reuse AppStoreCard to display skills.
     *
     * Note: We use the appId (not skill.id) for the id field so that AppStoreCard
     * uses the correct app gradient for the card background.
     * When the skill has its own icon_image, that is used instead of the app icon,
     * so AppStoreCard renders the skill-specific icon with the grey skill gradient.
     */
    function skillToAppMetadata(skill: SkillMetadata, appId: string, app: AppMetadata): AppMetadata {
        return {
            id: appId, // Use appId so card background gradient matches the app
            name_translation_key: skill.name_translation_key,
            description_translation_key: skill.description_translation_key,
            // Use skill's own icon_image if available; fall back to app icon
            icon_image: skill.icon_image || app.icon_image,
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
        // Handle special case: heart.svg -> health (since the app ID is "health" but icon file is heart.svg)
        // This ensures the correct CSS variable --color-app-health is used instead of --color-app-heart
        if (iconName === 'heart') {
            iconName = 'health';
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
     * Handle memories category selection - navigate to category details page.
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
            title: 'Apps'
        });
    }
</script>

<div class="app-details">
    {#if !app}
        <div class="error">
            <p>App not found.</p>
            <button class="back-button" onclick={goBack}>← Back to Apps</button>
        </div>
    {:else}
        <!-- Skills section - only show if skills exist -->
        {#if skills.length > 0}
            <div class="section">
                <SettingsSectionHeading title={$text('settings.app_store.skills.title')} icon="skill" />
                <p class="section-description">{$text('settings.app_store.skills.section_description')}</p>
                <div class="items-scroll-container">
                    <div class="items-scroll">
                        {#each skills as skill (skill.id)}
                            {@const skillApp = skillToAppMetadata(skill, appId, app)}
                            <AppStoreCard
                                app={skillApp}
                                cardIconType="skill"
                                skillProviders={skill.providers}
                                onSelect={() => handleSkillSelect(skill.id)}
                            />
                        {/each}
                    </div>
                </div>
            </div>
        {/if}

        <!-- Memories section - always show cards for each category -->
        {#if memoryFields.length > 0}
            <div class="section">
                <SettingsSectionHeading title={$text('settings.app_store.settings_memories.title')} icon="settings" />
                <p class="section-description">{$text('settings.app_store.settings_memories.section_description')}</p>
                <div class="items-scroll-container">
                    <div class="items-scroll">
                        {#each memoryFields as category (category.id)}
                            {@const categoryApp: AppMetadata = {
                                id: appId,
                                name_translation_key: category.name_translation_key,
                                description_translation_key: category.description_translation_key,
                                // Use category's own icon_image if available; fall back to app icon
                                icon_image: category.icon_image || app.icon_image,
                                icon_colorgradient: app.icon_colorgradient,
                                providers: [],
                                skills: [],
                                focus_modes: [],
                                settings_and_memories: []
                            }}
                            <AppStoreCard
                                app={categoryApp}
                                cardIconType="memory"
                                onSelect={() => handleSettingsMemoriesCategorySelect(category.id)}
                            />
                        {/each}
                    </div>
                </div>
            </div>
        {/if}
        
        <!-- Focus Modes section - only show if focus modes exist -->
        {#if focusModes.length > 0}
            <div class="section">
                <SettingsSectionHeading title={$text('settings.app_store.focus_modes.title')} icon="focus" />
                <p class="section-description">{$text('settings.app_store.focus_modes.section_description')}</p>
                <div class="items-scroll-container">
                    <div class="items-scroll">
                        {#each focusModes as focusMode (focusMode.id)}
                            {@const focusModeApp: AppMetadata = {
                                id: appId,
                                name_translation_key: focusMode.name_translation_key,
                                description_translation_key: focusMode.description_translation_key,
                                // Use focus mode's own icon_image if available; fall back to app icon
                                icon_image: focusMode.icon_image || app.icon_image,
                                icon_colorgradient: app.icon_colorgradient,
                                providers: [],
                                skills: [],
                                focus_modes: [],
                                settings_and_memories: []
                            }}
                            <AppStoreCard
                                app={focusModeApp}
                                cardIconType="focus"
                                onSelect={() => handleFocusModeSelect(focusMode.id)}
                            />
                        {/each}
                    </div>
                </div>
            </div>
        {/if}
        
        <!-- Active Reminders section - only shown for reminder app, authenticated users -->
        {#if isAuthenticated && appId === 'reminder'}
            <div class="section">
                <SettingsSectionHeading title={$text('apps.reminder.active_reminders.title')} icon="reminder" />
                <ActiveRemindersList on:openSettings={(e) => dispatch('openSettings', e.detail)} />
            </div>
        {/if}
        
        <!-- My Embeds section - show all embeds generated by this app -->
        {#if isAuthenticated}
            <div class="section">
                <SettingsSectionHeading title={'My embeds'} icon="embed" />
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
    
    .section {
        margin-top: 2rem;
        padding-left: 0;
    }

    /* Description text shown under section headings (Skills / Focus Modes / Memories) */
    .section-description {
        margin: 0.35rem 0 0.5rem 0;
        padding: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: var(--color-font-secondary);
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
        border-radius: var(--radius-3);
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
        transition: scrollbar-color var(--duration-normal) var(--easing-default);
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
        border-radius: var(--radius-1);
        border: 2px solid var(--color-grey-20);
        transition: background-color var(--duration-normal) var(--easing-default);
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
        border-radius: var(--radius-2);
        padding: 0.5rem 1rem;
        margin-top: 1rem;
        cursor: pointer;
        font-size: 0.9rem;
        color: var(--text-primary, #000000);
        transition: background var(--duration-normal) var(--easing-default);
    }
    
    .back-button:hover {
        background: var(--button-hover-background, #e0e0e0);
    }
</style>

