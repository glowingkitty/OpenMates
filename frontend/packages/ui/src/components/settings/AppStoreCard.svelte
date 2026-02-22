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
    import Icon from '../../components/Icon.svelte';
    import ProviderIcon from './ProviderIcon.svelte';
    import type { AppMetadata } from '../../types/apps';
    import { text } from '@repo/ui';
    
    /**
     * Props for AppStoreCard component.
     */
    interface Props {
        app: AppMetadata;
        onSelect: (appId: string) => void;
        /**
         * Optional: Skill-specific providers to display below description.
         * When provided, these will be shown instead of app-level providers.
         * Used when displaying skills in the app details page.
         */
        skillProviders?: string[];
    }
    
    let { app, onSelect, skillProviders }: Props = $props();
    
    // Reference to the app icon container for checking icon existence
    let appIconContainer: HTMLDivElement | null = $state(null);
    
    /**
     * Opacity values for provider icons (decreasing from left to right).
     * Index 0 = first icon (leftmost), index 4 = fifth icon (rightmost).
     */
    const PROVIDER_ICON_OPACITIES = [1, 0.85, 0.7, 0.55, 0.4];
    
    /** Maximum number of provider icons to display */
    const MAX_PROVIDER_ICONS = 5;
    
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
     * If skillProviders prop is provided, use those (for skill cards).
     * Otherwise, checks app-level providers first, then extracts from skills if needed.
     */
    let allProviders = $derived.by(() => {
        // If skillProviders prop is provided, use those (for skill cards in app details)
        if (skillProviders && skillProviders.length > 0) {
            return skillProviders;
        }
        
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
        const extracted = Array.from(providersSet);
        return extracted;
    });
    
    /**
     * Check if this card is displaying a skill (has skillProviders prop).
     * Used to determine if we should show providers below description.
     */
    let isSkillCard = $derived(skillProviders !== undefined && skillProviders.length > 0);
    
    /**
     * Get icon name from icon_image filename.
     * Maps icon_image like "ai.svg" to icon name "ai" for the Icon component.
     * Also handles special cases:
     * - "email.svg" -> "mail" (since the icon file is mail.svg)
     * - "coding.svg" -> "code" (since the app ID is "code" but icon file is coding.svg)
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return 'app';
        // Remove .svg extension and trim whitespace (YAML block scalars add a trailing newline)
        let iconName = iconImage.replace(/\.svg$/, '').trim();
        // Handle special case: email.svg -> mail (since the icon file is mail.svg)
        if (iconName === 'email') {
            iconName = 'mail';
        }
        // Handle special case: coding.svg -> code (since the app ID is "code" but icon file is coding.svg)
        // This ensures the correct CSS variable --color-app-code is used instead of --color-app-coding
        if (iconName === 'coding') {
            iconName = 'code';
        }
        // Handle special case: heart.svg -> health (since the app ID is "health" but icon file is heart.svg)
        // This ensures the correct CSS class app-health and --color-app-health are used instead of app-heart
        if (iconName === 'heart') {
            iconName = 'health';
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
     * Check if a provider icon exists by checking if the CSS variable is defined.
     * 
     * @param providerName - The provider name to check
     * @returns true if icon exists, false otherwise
     */
    function checkProviderIconExists(providerName: string): boolean {
        if (typeof document === 'undefined') return false;
        
        const iconName = getProviderIconName(providerName);
        const cssVarName = `--icon-url-${iconName}`;
        
        // Check if the CSS variable exists by trying to get it from computed styles
        const rootStyles = getComputedStyle(document.documentElement);
        const iconUrl = rootStyles.getPropertyValue(cssVarName).trim();
        
        // If the variable is empty or undefined, the icon is missing
        if (!iconUrl || iconUrl === 'none' || iconUrl === '') {
            return false;
        }
        
        return true;
    }
    
    /**
     * Get valid providers - those that have corresponding icon CSS variables.
     * This is a derived value that automatically updates when allProviders changes.
     * 
     * Note: We check for CSS variables, but if they're not loaded yet, we still return
     * the providers list and let the icons render (they'll show as empty if CSS var missing).
     */
    let validProviders = $derived.by(() => {
        if (allProviders.length === 0) {
            return [];
        }
        
        // If document is not available (SSR), return all providers
        if (typeof document === 'undefined') {
            return allProviders;
        }
        
        // Check which providers have CSS variables available
        const valid: string[] = [];
        for (const provider of allProviders) {
            if (checkProviderIconExists(provider)) {
                valid.push(provider);
            }
        }
        
        // If no valid providers found but we have providers, return them anyway
        // (CSS variables might not be loaded yet, or icon might exist but check failed)
        if (valid.length === 0 && allProviders.length > 0) {
            return allProviders;
        }
        
        return valid;
    });
    
    /**
     * Get ordered providers based on app's provider_display_order configuration.
     * If provider_display_order is defined in the app's app.yml, providers are
     * sorted accordingly. Providers in the display order appear first (in that order),
     * followed by any remaining providers not in the display order.
     */
    let orderedProviders = $derived.by(() => {
        const customOrder = app.provider_display_order;
        
        // If no custom ordering for this app, return providers as-is
        if (!customOrder || customOrder.length === 0) {
            return validProviders;
        }
        
        // Sort providers: those in customOrder first (in that order), then the rest
        const ordered: string[] = [];
        const remaining: string[] = [];
        
        // First, add providers that are in the custom order (preserving custom order)
        for (const provider of customOrder) {
            if (validProviders.includes(provider)) {
                ordered.push(provider);
            }
        }
        
        // Then, add any providers not in the custom order
        for (const provider of validProviders) {
            if (!customOrder.includes(provider)) {
                remaining.push(provider);
            }
        }
        
        return [...ordered, ...remaining];
    });
    
    /**
     * Get the opacity for a provider icon based on its position.
     * Uses the PROVIDER_ICON_OPACITIES array for decreasing opacity.
     * 
     * @param index - The index of the provider icon (0-based)
     * @returns The opacity value (0-1)
     */
    function getProviderIconOpacity(index: number): number {
        if (index < 0 || index >= PROVIDER_ICON_OPACITIES.length) {
            return PROVIDER_ICON_OPACITIES[PROVIDER_ICON_OPACITIES.length - 1];
        }
        return PROVIDER_ICON_OPACITIES[index];
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
        <div class="app-icon-container" bind:this={appIconContainer}>
            <!-- Provider icons behind the app icon - first centered, others to the right (max 5) -->
            <!-- Only show above app icon if NOT a skill card (skill cards show icons next to "via") -->
            <!-- Icons have decreasing opacity from left to right: 1, 0.85, 0.7, 0.55, 0.4 -->
            {#if orderedProviders.length > 0 && !isSkillCard}
                <div class="provider-icons-background">
                    {#each orderedProviders.slice(0, MAX_PROVIDER_ICONS) as provider, index}
                        <div 
                            class="provider-icon-container"
                            class:provider-icon-first={index === 0}
                            style="opacity: {getProviderIconOpacity(index)}"
                        >
                            <ProviderIcon 
                                name={provider}
                                size="30px"
                            />
                        </div>
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
    
    <!-- Skill-specific providers below description (only for skill cards) -->
    <!-- Show provider icons next to "via" text instead of above app icon -->
    <!-- Skill cards show first 4 providers with decreasing opacity, plus a "+N" counter if more exist -->
    {#if isSkillCard && orderedProviders.length > 0}
        {@const maxSkillProviderIcons = 4}
        {@const displayedProviders = orderedProviders.slice(0, maxSkillProviderIcons)}
        {@const remainingCount = orderedProviders.length - maxSkillProviderIcons}
        <div class="skill-providers">
            <span class="via-text">via</span>
            {#each displayedProviders as provider, index}
                <div class="skill-provider-icon" style="opacity: {getProviderIconOpacity(index)}">
                    <ProviderIcon name={provider} size="30px" />
                </div>
            {/each}
            {#if remainingCount > 0}
                <span class="skill-providers-remaining">+{remainingCount}</span>
            {/if}
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
        /* Prevent mobile browsers from misinterpreting taps as scroll gestures
           in horizontally scrollable containers */
        touch-action: manipulation;
        border: 1px solid rgba(255, 255, 255, 0.2);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        display: flex;
        flex-direction: column;
        color: #ffffff;
        position: relative;
        overflow: hidden;
        box-sizing: border-box; /* Ensure padding is included in width/height */
        padding-top: 25px;
    }
    
    /* When displaying a skill card with providers, move content up */
    /* This creates more space at the bottom for the larger 30px provider icons */
    .app-store-card:has(.skill-providers) {
        padding-top: 5px; /* Reduce from 25px to move content up */
    }
    
    .app-store-card:has(.skill-providers) .app-header-row {
        margin-top: 0px; /* Move up from original 6px to create space below */
    }
    
    .app-store-card:has(.skill-providers) .app-card-description {
        margin-top: 0px; /* Move up to create space below for provider icons */
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
    /* Move down slightly to accommodate provider icons above */
    .app-header-row {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.5rem;
        margin-top: 6px; /* Move down to make room for provider icons above */
        flex-shrink: 0;
    }
    
    /* App icon container - 38px x 38px with provider icons above */
    .app-icon-container {
        position: relative;
        width: 38px;
        height: 38px;
        display: flex;
        align-items: flex-end; /* Align content to bottom */
        justify-content: center;
        flex-shrink: 0;
    }
    
    /* Provider icons above the app icon - centered at top of container */
    .provider-icons-background {
        position: absolute;
        top: 0; /* Position at top of container */
        left: 50%;
        transform: translate(-14px, -20px);
        display: flex;
        align-items: center;
        justify-content: center; /* Center the icons */
        gap: 6px;
        z-index: 1; /* Above the app icon */
        pointer-events: none; /* Prevent interaction with background icons */
    }
    
    /* All provider icon containers (wraps ProviderIcon component) */
    /* App cards: provider icons above app icon have reduced opacity */
    .provider-icon-container {
        position: relative;
        flex-shrink: 0;
    }
    
    .app-icon-wrapper {
        position: relative;
        width: 38px;
        height: 38px;
        z-index: 1; /* Below provider icons */
        /* Icon will naturally sit at bottom due to container's align-items: flex-end */
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
        margin-top: 10px;
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
    
    /* Skill providers section - shown below description for skill cards */
    .skill-providers {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-top: 4px;
        font-size: 12px;
        color: rgba(255, 255, 255, 0.8);
        flex-wrap: wrap;
    }
    
    .via-text {
        color: rgba(255, 255, 255, 0.7);
        font-style: italic;
    }
    
    .skill-provider-icon {
        display: flex;
        align-items: center;
        flex-shrink: 0;
        /* Opacity is now set dynamically via inline style for decreasing opacity effect */
    }
    
    /* Remaining provider count shown after the last visible icon (e.g., "+3") */
    .skill-providers-remaining {
        color: rgba(255, 255, 255, 0.7);
        font-size: 13px;
        font-weight: 500;
        white-space: nowrap;
        flex-shrink: 0;
    }
    
</style>

