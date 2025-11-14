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
    import type { AppMetadata, SkillMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    
    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();
    
    // Get app ID from the current path
    // The path will be like "app_store/ai" or "app_store/web"
    // We need to extract the app ID from the activeSettingsView
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
            memory_fields: []
        };
    }
    
    /**
     * Handle skill card selection (currently no-op, but can be extended).
     */
    function handleSkillSelect(skillAppId: string) {
        // Could navigate to skill details in the future
        // For now, do nothing
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
        
        <!-- Skills section -->
        <div class="skills-section">
            <h2>Skills</h2>
            {#if skills.length === 0}
                <div class="no-skills">
                    <p>No skills available for this app.</p>
                    <p class="hint">Skills are added as they reach production stage.</p>
                </div>
            {:else}
                <div class="skills-scroll-container">
                    <div class="skills-scroll">
                        {#each skills as skill (skill.id)}
                            {@const skillApp = skillToAppMetadata(skill, appId, app)}
                            <AppStoreCard app={skillApp} onSelect={handleSkillSelect} />
                        {/each}
                    </div>
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .app-details {
        padding: 2rem;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .app-header {
        margin-bottom: 2rem;
    }
    
    .app-description {
        margin: 0;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
    }
    
    .skills-section {
        margin-top: 2rem;
    }
    
    .skills-section h2 {
        margin: 0 0 1.5rem 0;
        font-size: 1.5rem;
        font-weight: 600;
        color: var(--text-primary, #000000);
    }
    
    .no-skills,
    .error {
        padding: 3rem;
        text-align: center;
        color: var(--text-secondary, #666666);
    }
    
    .error {
        color: var(--error-color, #dc3545);
    }
    
    .hint {
        margin-top: 0.5rem;
        font-size: 0.9rem;
        color: var(--text-secondary, #666666);
    }
    
    .skills-scroll-container {
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 0.5rem;
        /* Match settings menu scrollbar style */
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }
    
    .skills-scroll-container:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }
    
    .skills-scroll-container::-webkit-scrollbar {
        height: 8px;
    }
    
    .skills-scroll-container::-webkit-scrollbar-track {
        background: transparent;
    }
    
    .skills-scroll-container::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid var(--color-grey-20);
        transition: background-color 0.2s ease;
    }
    
    .skills-scroll-container:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }
    
    .skills-scroll-container::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }
    
    .skills-scroll {
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

