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
    import Icon from '../../components/Icon.svelte';
    import SkillCard from './SkillCard.svelte';
    import type { AppMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    
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
     * Get icon name from icon_image filename.
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return 'app';
        return iconImage.replace(/\.svg$/, '');
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
        <!-- App header with icon and info -->
        <div class="app-header">
            <div class="app-header-content">
                <div 
                    class="app-header-icon-container"
                    style={app.icon_colorgradient 
                        ? `background: linear-gradient(135deg, ${app.icon_colorgradient.start}, ${app.icon_colorgradient.end})`
                        : ''
                    }
                >
                    {#if app.icon_image}
                        <Icon 
                            name={getIconName(app.icon_image)}
                            type="app"
                            size="80px"
                            className="app-header-icon"
                        />
                    {:else if app.icon_colorgradient}
                        <div 
                            class="app-icon-gradient" 
                            style="background: linear-gradient(135deg, {app.icon_colorgradient.start}, {app.icon_colorgradient.end})"
                        ></div>
                    {/if}
                </div>
                <div class="app-header-text">
                    <h1>{app.name}</h1>
                    <p class="app-description">{app.description}</p>
                    {#if app.providers && app.providers.length > 0}
                        <div class="app-providers">
                            <span class="providers-label">Providers:</span>
                            <div class="providers-list">
                                {#each app.providers as provider}
                                    <span class="provider-badge">{provider}</span>
                                {/each}
                            </div>
                        </div>
                    {/if}
                </div>
            </div>
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
                <div class="skills-grid">
                    {#each skills as skill (skill.id)}
                        <SkillCard {skill} {appId} />
                    {/each}
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .app-details {
        padding: 2rem;
        max-width: 1200px;
        margin: 0 auto;
    }
    
    .app-header {
        margin-bottom: 3rem;
    }
    
    .app-header-content {
        display: flex;
        gap: 2rem;
        align-items: flex-start;
    }
    
    .app-header-icon-container {
        width: 120px;
        height: 120px;
        border-radius: 20px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }
    
    .app-header-icon {
        width: 80px;
        height: 80px;
    }
    
    .app-icon-gradient {
        width: 80px;
        height: 80px;
        border-radius: 12px;
    }
    
    .app-header-text {
        flex: 1;
    }
    
    .app-header-text h1 {
        margin: 0 0 0.5rem 0;
        font-size: 2rem;
        font-weight: 700;
        color: var(--text-primary, #000000);
    }
    
    .app-description {
        margin: 0 0 1rem 0;
        color: var(--text-secondary, #666666);
        font-size: 1.1rem;
        line-height: 1.6;
    }
    
    .app-providers {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex-wrap: wrap;
    }
    
    .providers-label {
        font-size: 0.9rem;
        color: var(--text-secondary, #666666);
        font-weight: 500;
    }
    
    .providers-list {
        display: flex;
        gap: 0.5rem;
        flex-wrap: wrap;
    }
    
    .provider-badge {
        background: var(--button-background, #f0f0f0);
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: 6px;
        padding: 0.25rem 0.75rem;
        font-size: 0.85rem;
        color: var(--text-primary, #000000);
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
    
    .skills-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 1.5rem;
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

