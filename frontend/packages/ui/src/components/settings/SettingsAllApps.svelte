<!-- frontend/packages/ui/src/components/settings/SettingsAllApps.svelte
     All Apps view - shows all apps in a vertical list layout, sorted by date.
     
     This is a submenu of the App Store that displays all available apps
     in a vertical grid layout instead of horizontal scrollable categories.
-->

<script lang="ts">
    import { appSkillsStore } from '../../stores/appSkillsStore';
    // @ts-expect-error - Svelte components are default exports
    import Icon from '../../components/Icon.svelte';
    import type { AppMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    
    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();
    
    // Use $state() for reactive state (Svelte 5)
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
     * Get icon name from icon_image filename.
     * Maps icon_image like "ai.svg" to icon name "ai" for the Icon component.
     * Also handles special cases like "email.svg" -> "mail" (since the icon file is mail.svg).
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return 'app';
        // Remove .svg extension and return the name
        let iconName = iconImage.replace(/\.svg$/, '');
        // Handle special case: email.svg -> mail (since the icon file is mail.svg)
        if (iconName === 'email') {
            iconName = 'mail';
        }
        return iconName;
    }
    
    /**
     * Get provider icon name from provider name.
     * Maps provider names like "Brave" to icon names like "brave".
     */
    function getProviderIconName(providerName: string): string {
        // Convert to lowercase and handle special cases
        const normalized = providerName.toLowerCase()
            .replace(/\s+/g, '_')
            .replace(/\./g, '');
        return normalized;
    }
    
    /**
     * Get app gradient from theme.css based on app id.
     * Constructs CSS variable name directly from app ID: var(--color-app-{appId})
     * 
     * **Note**: CSS variables in theme.css now match app IDs exactly (using underscores).
     * This eliminates the need for a hardcoded mapping that must be kept in sync.
     * 
     * @param appId - The app ID (e.g., 'web', 'life_coaching', 'pcb_design', 'mail')
     * @returns CSS variable reference (e.g., 'var(--color-app-web)')
     */
    function getAppGradient(appId: string): string {
        // Construct CSS variable name directly from app ID
        // CSS variables in theme.css now match app IDs exactly (e.g., --color-app-life_coaching)
        return `var(--color-app-${appId})`;
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
            <p>No apps available.</p>
        </div>
    {:else}
        <!-- Vertical grid layout for all apps -->
        <div class="apps-grid">
            {#each allAppsSorted as app (app.id)}
                <div 
                    class="app-card" 
                    role="button"
                    tabindex="0"
                    {...{onclick: () => selectApp(app.id), onkeydown: (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            selectApp(app.id);
                        }
                    }}}
                    style={`background: ${getAppGradient(app.id)}`}
                >
                    <!-- App icon with provider icons behind it -->
                    <div class="app-icon-container">
                        <!-- Provider icons (behind app icon) -->
                        {#if app.providers && app.providers.length > 0}
                            <div class="provider-icons-background">
                                {#each app.providers.slice(0, 3) as provider}
                                    <Icon 
                                        name={getProviderIconName(provider)}
                                        type="provider"
                                        size="20px"
                                        className="provider-icon-bg"
                                    />
                                {/each}
                            </div>
                        {/if}
                        
                        <!-- Main app icon (on top) with white border -->
                        {#if app.icon_image}
                            <div class="app-icon-wrapper">
                                <Icon 
                                    name={getIconName(app.icon_image)}
                                    type="app"
                                    size="48px"
                                    className="app-icon-main no-fade"
                                    borderColor="#ffffff"
                                />
                            </div>
                        {:else}
                            <div 
                                class="app-icon-gradient" 
                                style={`background: ${getAppGradient(app.id)}`}
                            ></div>
                        {/if}
                    </div>
                    
                    <!-- App name and description -->
                    <h3 class="app-card-name">{app.name}</h3>
                    <p class="app-card-description">{app.description}</p>
                </div>
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
    }
    
    .app-card {
        width: 223px;
        height: 129px;
        min-width: 223px;
        min-height: 129px;
        border-radius: 12px;
        padding: 1rem;
        cursor: pointer;
        transition: all 0.2s ease;
        outline: none;
        border: 1px solid rgba(255, 255, 255, 0.2);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        display: flex;
        flex-direction: column;
        color: #ffffff;
        position: relative;
        overflow: hidden;
    }
    
    .app-card:focus {
        outline: 2px solid rgba(255, 255, 255, 0.8);
        outline-offset: 2px;
    }
    
    .app-card:hover {
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
        transform: translateY(-2px);
    }
    
    .app-icon-container {
        position: relative;
        width: 48px;
        height: 48px;
        margin-bottom: 0.5rem;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }
    
    .provider-icons-background {
        position: absolute;
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 3px;
        opacity: 0.4;
        filter: blur(1.5px);
        z-index: 0;
    }
    
    .provider-icon-bg {
        width: 20px;
        height: 20px;
    }
    
    .app-icon-wrapper {
        position: relative;
        z-index: 1;
        width: 48px;
        height: 48px;
    }
    
    .app-icon-main {
        border: 2px solid #ffffff !important;
        border-radius: 8px;
        box-sizing: border-box;
    }
    
    /* Remove fade-in animation for app icons */
    :global(.app-icon-main.no-fade),
    :global(.app-icon-main.no-fade .icon) {
        opacity: 1 !important;
        animation: none !important;
        animation-delay: 0 !important;
    }
    
    .app-icon-gradient {
        position: relative;
        z-index: 1;
        width: 48px;
        height: 48px;
        border: 2px solid #ffffff;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        box-sizing: border-box;
    }
    
    .app-card-name {
        margin: 0 0 0.25rem 0;
        font-size: 1rem;
        font-weight: 600;
        color: #ffffff;
        line-height: 1.2;
    }
    
    .app-card-description {
        margin: 0;
        color: rgba(255, 255, 255, 0.9);
        font-size: 0.75rem;
        line-height: 1.4;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        flex-grow: 1;
    }
</style>

