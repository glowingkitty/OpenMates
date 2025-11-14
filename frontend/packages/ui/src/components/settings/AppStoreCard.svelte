<!-- frontend/packages/ui/src/components/settings/AppStoreCard.svelte
     Reusable app card component for the App Store.
     
     This component displays an app card with:
     - Provider icons above the app icon (if available)
     - 38px x 38px app icon with white border
     - App name and description at 16px font size
     - Gradient background based on app ID
     
     Used in:
     - SettingsAppStore.svelte (horizontal scrollable categories)
     - SettingsAllApps.svelte (vertical grid layout)
-->

<script lang="ts">
    // @ts-expect-error - Svelte components are default exports
    import Icon from '../../components/Icon.svelte';
    import type { AppMetadata } from '../../types/apps';
    import { text } from '@repo/ui';
    
    /**
     * Props for AppStoreCard component.
     */
    interface Props {
        app: AppMetadata;
        onSelect: (appId: string) => void;
    }
    
    let { app, onSelect }: Props = $props();
    
    /**
     * Get the translated app name.
     * Uses name_translation_key if available, otherwise falls back to name.
     */
    let appName = $derived(
        app.name_translation_key 
            ? $text(app.name_translation_key)
            : (app.name || app.id)
    );
    
    /**
     * Get the translated app description.
     * Uses description_translation_key if available, otherwise falls back to description.
     */
    let appDescription = $derived(
        app.description_translation_key 
            ? $text(app.description_translation_key)
            : (app.description || '')
    );
    
    /**
     * Get all providers for this app.
     * Checks app-level providers first, then extracts from skills if needed.
     */
    let allProviders = $derived.by(() => {
        // First check if app has providers at the app level
        if (app.providers && app.providers.length > 0) {
            return app.providers;
        }
        
        // Fallback: extract providers from skills
        const providersSet = new Set<string>();
        if (app.skills) {
            for (const skill of app.skills) {
                if (skill.providers && skill.providers.length > 0) {
                    skill.providers.forEach(provider => providersSet.add(provider));
                }
            }
        }
        return Array.from(providersSet);
    });
    
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
     * Handle card click or keyboard interaction.
     */
    function handleInteraction(e: KeyboardEvent | MouseEvent) {
        if (e.type === 'keydown') {
            const keyEvent = e as KeyboardEvent;
            if (keyEvent.key === 'Enter' || keyEvent.key === ' ') {
                keyEvent.preventDefault();
                onSelect(app.id);
            }
        } else {
            onSelect(app.id);
        }
    }
</script>

<div 
    class="app-store-card" 
    role="button"
    tabindex="0"
    onclick={handleInteraction}
    onkeydown={handleInteraction}
    style={`background: ${getAppGradient(app.id)}`}
>
    <!-- App icon and name side by side -->
    <div class="app-header-row">
        <!-- App icon container - 38px x 38px with provider icons behind it -->
        <div class="app-icon-container">
            <!-- Provider icons behind the app icon - 30x30px -->
            {#if allProviders.length > 0}
                <div class="provider-icons-background">
                    {#each allProviders.slice(0, 3) as provider}
                        <Icon 
                            name={getProviderIconName(provider)}
                            type="provider"
                            size="30px"
                            className="provider-icon-bg"
                        />
                    {/each}
                </div>
            {/if}
            
            <!-- Main app icon with white border (on top) -->
            {#if app.icon_image}
                <div class="app-icon-wrapper">
                    <Icon 
                        name={getIconName(app.icon_image)}
                        type="app"
                        size="38px"
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
        
        <!-- App name aligned right next to the icon -->
        <h3 class="app-card-name">{appName}</h3>
    </div>
    
    <!-- App description below -->
    <p class="app-card-description">{appDescription}</p>
    
    <!-- Provider icons section -->
    {#if allProviders.length > 0}
        <div class="providers-section">
            {#each allProviders.slice(0, 3) as provider}
                <div class="provider-icon-container">
                    <Icon 
                        name={getProviderIconName(provider)}
                        type="app"
                        size="24px"
                        className="provider-app-icon"
                        borderColor="#ffffff"
                    />
                </div>
            {/each}
        </div>
    {/if}
</div>

<style>
    .app-store-card {
        width: 223px;
        height: 129px;
        min-width: 223px;
        min-height: 129px;
        max-width: 223px;
        max-height: 129px;
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
        box-sizing: border-box; /* Ensure padding is included in width/height */
    }
    
    .app-store-card:focus {
        outline: 2px solid rgba(255, 255, 255, 0.8);
        outline-offset: 2px;
    }
    
    .app-store-card:hover {
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
        transform: translateY(-2px);
    }
    
    /* App header row - icon and name side by side */
    .app-header-row {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.5rem;
        flex-shrink: 0;
    }
    
    /* App icon container - 38px x 38px with provider icons behind */
    .app-icon-container {
        position: relative;
        width: 38px;
        height: 38px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }
    
    /* Provider icons behind the app icon - 30x30px */
    .provider-icons-background {
        position: absolute;
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 2px;
        opacity: 0.5;
        z-index: 0;
    }
    
    .provider-icon-bg {
        width: 30px;
        height: 30px;
    }
    
    .app-icon-wrapper {
        position: relative;
        width: 38px;
        height: 38px;
        z-index: 1; /* Ensure app icon is above provider icons */
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
        width: 38px;
        height: 38px;
        border: 2px solid #ffffff;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        box-sizing: border-box;
        z-index: 1; /* Ensure gradient icon is above provider icons */
    }
    
    .app-card-name {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
        color: #ffffff;
        line-height: 1.2;
        flex: 1;
    }
    
    .app-card-description {
        margin: 0;
        color: rgba(255, 255, 255, 0.9);
        font-size: 14px;
        line-height: 1.4;
        /* Remove text truncation - show full description */
        overflow: visible;
        flex-grow: 1;
    }
    
    /* Provider icons section - displayed as app icons */
    .providers-section {
        display: flex;
        gap: 0.5rem;
        align-items: center;
        margin-top: 0.5rem;
        flex-shrink: 0;
    }
    
    .provider-icon-container {
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .provider-app-icon {
        border: 1.5px solid rgba(255, 255, 255, 0.6) !important;
        border-radius: 6px;
        box-sizing: border-box;
    }
</style>

