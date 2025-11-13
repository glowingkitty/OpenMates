<!-- frontend/packages/ui/src/components/settings/SettingsAppStore.svelte
     App Store component for browsing and discovering available apps.
     
     **Design**: Horizontal scrollable sections organized by category, with app cards
     featuring gradient backgrounds and provider icons.
     
     **Backend Implementation**:
     - Data source: Static appsMetadata.ts (generated at build time)
     - Store: frontend/packages/ui/src/stores/appSkillsStore.ts
     - Types: frontend/packages/ui/src/types/apps.ts
-->

<script lang="ts">
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { authStore } from '../../stores/authStore';
    import { userProfile } from '../../stores/userProfile';
    import { mostUsedAppsStore } from '../../stores/mostUsedAppsStore';
    import Icon from '../../components/Icon.svelte';
    import SettingsItem from '../SettingsItem.svelte';
    import type { AppMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    
    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();
    
    // Use $state() for reactive state (Svelte 5)
    let storeState = $state(appSkillsStore.getState());
    
    // Subscribe to most used apps store (fetched on app load in +page.svelte)
    // In Svelte 5, stores are reactive when using $ prefix
    let mostUsedAppsState = $mostUsedAppsStore;
    
    // Check if user is authenticated (for read-only mode)
    let isAuthenticated = $derived($authStore.isAuthenticated);
    
    // Reactive derived values
    let apps = $derived(storeState.apps);
    let appsList = $derived(Object.values(apps));
    
    // State for random explore apps (persisted for a day)
    let cachedRandomApps = $state<AppMetadata[] | null>(null);
    let cachedRandomAppsTimestamp = $state<number | null>(null);
    
    /**
     * Initialize random apps from user profile on mount and handle generation when needed.
     * This effect handles all state mutations to keep derived values pure.
     */
    $effect(() => {
        const profile = $userProfile;
        const now = Date.now();
        const oneDayMs = 24 * 60 * 60 * 1000; // 24 hours in milliseconds
        
        // First, try to load from user profile if available
        if (profile.random_explore_apps && profile.random_explore_apps_timestamp) {
            const age = now - profile.random_explore_apps_timestamp;
            
            if (age < oneDayMs) {
                // Use cached apps if still valid
                const existingApps = profile.random_explore_apps
                    .map(appId => apps[appId])
                    .filter(Boolean)
                    .slice(0, 5);
                
                if (existingApps.length >= 3) {
                    cachedRandomApps = existingApps;
                    cachedRandomAppsTimestamp = profile.random_explore_apps_timestamp;
                    return; // We have valid cached apps, no need to generate
                }
            }
        }
        
        // Check if we need to generate new random apps
        // This happens when:
        // 1. We don't have cached apps, OR
        // 2. Cached apps are expired (older than 24 hours), OR
        // 3. Cached apps have invalid entries (apps that no longer exist)
        let needsGeneration = false;
        if (!cachedRandomApps || !cachedRandomAppsTimestamp) {
            needsGeneration = true;
        } else {
            const age = now - cachedRandomAppsTimestamp;
            const validApps = cachedRandomApps.filter(app => apps[app.id]);
            needsGeneration = age >= oneDayMs || validApps.length < 3;
        }
        
        if (needsGeneration && appsList.length > 0) {
            // Generate new random apps
            const shuffled = [...appsList].sort(() => Math.random() - 0.5);
            const newRandomApps = shuffled.slice(0, 5);
            const newRandomAppIds = newRandomApps.map(app => app.id);
            
            // Update cache (this mutation is safe in $effect)
            cachedRandomApps = newRandomApps;
            cachedRandomAppsTimestamp = now;
            
            // Store new random apps with current timestamp (async, fire and forget)
            import('../../stores/userProfile').then(({ updateProfile }) => {
                updateProfile({
                    random_explore_apps: newRandomAppIds,
                    random_explore_apps_timestamp: now
                });
            });
        }
    });
    
    /**
     * Get top recommended apps for the user.
     * Uses personalized recommendations if available, otherwise falls back to random apps
     * that persist for a day.
     * 
     * **Important**: This derived value is completely pure - it only reads state and never mutates it.
     * All mutations are handled in the $effect above.
     */
    let topRecommendedApps = $derived.by(() => {
        const profile = $userProfile;
        
        // Only show personalized picks for authenticated users
        if (!isAuthenticated) {
            // Return cached random apps if available, otherwise empty array
            // The $effect above will generate them if needed
            if (cachedRandomApps && cachedRandomApps.length > 0) {
                const validApps = cachedRandomApps.filter(app => apps[app.id]);
                if (validApps.length >= 3) {
                    return validApps.slice(0, 5);
                }
            }
            return [];
        }
        
        // Use personalized recommendations if available
        if (profile.top_recommended_apps && profile.top_recommended_apps.length > 0) {
            const recommended = profile.top_recommended_apps
                .map(appId => apps[appId])
                .filter(Boolean) // Remove any apps that don't exist
                .slice(0, 5);
            
            // If we have at least 3 recommendations, use them
            if (recommended.length >= 3) {
                return recommended;
            }
        }
        
        // Fallback: random apps for new users (persist for a day)
        // Return cached random apps if available, otherwise empty array
        // The $effect above will generate them if needed
        if (cachedRandomApps && cachedRandomApps.length > 0) {
            const validApps = cachedRandomApps.filter(app => apps[app.id]);
            if (validApps.length >= 3) {
                return validApps.slice(0, 5);
            }
        }
        return [];
    });
    
    /**
     * Get most used apps as AppMetadata objects.
     * Uses the global mostUsedAppsStore (fetched on app load in +page.svelte).
     */
    let mostUsedApps = $derived.by(() => {
        return mostUsedAppsState.appIds
            .map(appId => apps[appId])
            .filter(Boolean) // Remove any apps that don't exist
            .slice(0, 5); // Limit to top 5
    });
    
    /**
     * Get translated category name for display.
     * Category keys are internal identifiers, translations are used for display.
     */
    function getCategoryDisplayName(categoryKey: string): string {
        const translationMap: Record<string, string> = {
            'top_picks': 'settings.app_store.categories.explore_discover.text',
            'most_used': 'settings.app_store.categories.most_used.text',
            'new_apps': 'settings.app_store.categories.new_apps.text',
            'for_work': 'settings.app_store.categories.for_work.text',
            'for_everyday_life': 'settings.app_store.categories.for_everyday_life.text'
        };
        const translationKey = translationMap[categoryKey] || 'settings.app_store.categories.other.text';
        return $text(translationKey);
    }
    
    /**
     * Map category keys to icon names for category headers.
     * Icons are located in frontend/packages/ui/static/icons/
     */
    function getCategoryIcon(categoryKey: string): string {
        const iconMap: Record<string, string> = {
            'top_picks': 'reload',
            'most_used': 'heart',
            'new_apps': 'create',
            'for_work': 'business',
            'for_everyday_life': 'home'
        };
        return iconMap[categoryKey] || 'app';
    }
    
    /**
     * Get app gradient from theme.css based on app id.
     * Maps app IDs to CSS variable names defined in theme.css.
     */
    function getAppGradient(appId: string): string {
        // Map app IDs to theme.css gradient variables
        const gradientMap: Record<string, string> = {
            'ai': 'var(--color-app-ai)',
            'health': 'var(--color-app-health)',
            'travel': 'var(--color-app-travel)',
            'tv': 'var(--color-app-tv)',
            'videos': 'var(--color-app-videos)',
            'web': 'var(--color-app-web)',
            'email': 'var(--color-app-mail)',
            'mail': 'var(--color-app-mail)',
            'code': 'var(--color-app-code)',
            'study': 'var(--color-app-study)',
            'plants': 'var(--color-app-plants)',
            'books': 'var(--color-app-books)',
            'nutrition': 'var(--color-app-nutrition)',
            'fitness': 'var(--color-app-fitness)',
            'life_coaching': 'var(--color-app-lifecoaching)',
            'images': 'var(--color-app-photos)',
            'pcb_design': 'var(--color-app-pcbdesign)'
        };
        return gradientMap[appId] || 'var(--color-primary)';
    }
    
    /**
     * Categorize apps into sections (duplicates allowed across categories).
     * 
     * **Categorization Logic:**
     * - Apps are assigned to categories: top_picks → most_used → new_apps → for_work → for_everyday_life
     * - Apps can appear in multiple categories (duplicates allowed)
     * - Maximum 5 apps per category
     * - "Top picks for you": Personalized recommendations (or random fallback)
     * - "Most used": Apps from API based on 30-day usage statistics
     * - "New apps": Apps with last_updated field, sorted by date (newest first)
     * - "For work": Apps with category: "work"
     * - "For everyday life": Apps with category: "personal"
     */
    function categorizeApps(apps: AppMetadata[]): Record<string, AppMetadata[]> {
        // Use internal category keys (not translated names)
        const categories: Record<string, AppMetadata[]> = {
            'top_picks': [],
            'most_used': [],
            'new_apps': [],
            'for_work': [],
            'for_everyday_life': []
        };
        
        const MAX_APPS_PER_CATEGORY = 5;
        
        // Priority 1: "Top picks for you" - Use personalized recommendations
        const topPicks = topRecommendedApps.length > 0 
            ? topRecommendedApps 
            : apps.slice(0, Math.min(MAX_APPS_PER_CATEGORY, apps.length));
        
        for (const app of topPicks) {
            if (categories['top_picks'].length < MAX_APPS_PER_CATEGORY) {
                categories['top_picks'].push(app);
            }
        }
        
        // Priority 2: "Most used" - Apps from API based on 30-day usage statistics
        for (const app of mostUsedApps) {
            if (categories['most_used'].length < MAX_APPS_PER_CATEGORY) {
                categories['most_used'].push(app);
            }
        }
        
        // Priority 3: "New apps" - Apps with last_updated, sorted by date (newest first)
        const appsWithDate = apps
            .filter(app => app.last_updated)
            .map(app => ({
                app,
                date: new Date(app.last_updated!).getTime()
            }))
            .sort((a, b) => b.date - a.date); // Sort newest first
        
        const ninetyDaysAgo = Date.now() - (90 * 24 * 60 * 60 * 1000);
        const recentApps = appsWithDate
            .filter(({ date }) => date >= ninetyDaysAgo)
            .slice(0, MAX_APPS_PER_CATEGORY)
            .map(({ app }) => app);
        
        for (const app of recentApps) {
            if (categories['new_apps'].length < MAX_APPS_PER_CATEGORY) {
                categories['new_apps'].push(app);
            }
        }
        
        // If not enough recent apps, fill with newest overall
        if (categories['new_apps'].length < MAX_APPS_PER_CATEGORY) {
            for (const { app } of appsWithDate) {
                if (categories['new_apps'].length < MAX_APPS_PER_CATEGORY) {
                    categories['new_apps'].push(app);
                }
            }
        }
        
        // Priority 4: "For work" - Apps with category: "work"
        const workApps = apps
            .filter(app => app.category === 'work')
            .slice(0, MAX_APPS_PER_CATEGORY);
        
        for (const app of workApps) {
            if (categories['for_work'].length < MAX_APPS_PER_CATEGORY) {
                categories['for_work'].push(app);
            }
        }
        
        // Priority 5: "For everyday life" - Apps with category: "personal"
        const everydayApps = apps
            .filter(app => app.category === 'personal')
            .slice(0, MAX_APPS_PER_CATEGORY);
        
        for (const app of everydayApps) {
            if (categories['for_everyday_life'].length < MAX_APPS_PER_CATEGORY) {
                categories['for_everyday_life'].push(app);
            }
        }
        
        // Filter out empty categories
        const filtered: Record<string, AppMetadata[]> = {};
        for (const [key, value] of Object.entries(categories)) {
            if (value.length > 0) {
                filtered[key] = value;
            }
        }
        
        return filtered;
    }
    
    /**
     * Get all apps sorted by last_updated date (newest first).
     * Used for "Show all apps" submenu.
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
    
    /**
     * Navigate to "Show all apps" submenu.
     * This dispatches an event to the parent Settings component to navigate to apps/all.
     */
    function showAllApps() {
        dispatch('openSettings', {
            settingsPath: 'apps/all',
            direction: 'forward',
            icon: 'app',
            title: $text('settings.app_store.show_all_apps.text')
        });
    }
    
    // Categorize apps for display
    let categorizedApps = $derived(categorizeApps(appsList));
    let categoryEntries = $derived(Object.entries(categorizedApps));
</script>

<div class="settings-apps">
    {#if appsList.length === 0}
        <div class="no-apps">
            <p>{$text('settings.app_store.no_apps_available')}</p>
        </div>
    {:else}
        <!-- Horizontal scrollable sections for each category -->
        {#each categoryEntries as [categoryName, categoryApps]}
            <div class="category-section">
                <!-- Category header with icon (matching SettingsItem heading style) -->
                <SettingsItem 
                    type="heading"
                    icon={getCategoryIcon(categoryName)}
                    title={getCategoryDisplayName(categoryName)}
                />
                
                <div class="apps-scroll-container">
                    <div class="apps-scroll">
                        {#each categoryApps as app (app.id)}
                            <div 
                                class="app-card" 
                                role="button"
                                tabindex="0"
                                onclick={() => selectApp(app.id)}
                                onkeydown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        selectApp(app.id);
                                    }
                                }}
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
                </div>
            </div>
        {/each}
        
        <!-- "Show all apps" button at the bottom -->
        <div class="show-all-apps-section">
            <SettingsItem 
                type="submenu"
                icon="app"
                title={$text('settings.app_store.show_all_apps.text')}
                onClick={showAllApps}
            />
        </div>
    {/if}
</div>

<style>
    .settings-apps {
        padding: 1rem 0 3rem 0;
        max-width: 1400px;
        margin: 0 auto;
        min-height: fit-content;
        height: 100%;
        overflow-y: auto;
        overflow-x: hidden;
        /* Match settings menu scrollbar style */
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }
    
    .settings-apps:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }
    
    .settings-apps::-webkit-scrollbar {
        width: 8px;
    }
    
    .settings-apps::-webkit-scrollbar-track {
        background: transparent;
    }
    
    .settings-apps::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid var(--color-grey-20);
        transition: background-color 0.2s ease;
    }
    
    .settings-apps:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }
    
    .settings-apps::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }
    
    .no-apps {
        padding: 3rem;
        text-align: center;
        color: var(--text-secondary, #666666);
    }
    
    .category-section {
        margin-bottom: 10px;
    }
    
    .show-all-apps-section {
        margin-top: 2rem;
        margin-bottom: 1rem;
    }
    
    .apps-scroll-container {
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 0.5rem;
        padding-left: 10px;
        margin-top: 0.5rem;
        /* Match settings menu scrollbar style */
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }
    
    .apps-scroll-container:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }
    
    .apps-scroll-container::-webkit-scrollbar {
        height: 8px;
    }
    
    .apps-scroll-container::-webkit-scrollbar-track {
        background: transparent;
    }
    
    .apps-scroll-container::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid var(--color-grey-20);
        transition: background-color 0.2s ease;
    }
    
    .apps-scroll-container:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }
    
    .apps-scroll-container::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }
    
    .apps-scroll {
        display: flex;
        gap: 1rem;
        padding-right: 1rem;
        min-width: min-content;
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
    
    /* Remove fade-in animation for app icons in app store */
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

