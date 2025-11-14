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
    // @ts-expect-error - Svelte components are default exports
    import SettingsItem from '../SettingsItem.svelte';
    // @ts-expect-error - Svelte components are default exports
    import AppStoreCard from './AppStoreCard.svelte';
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
     * 
     * **Important**: Uses guards to prevent infinite loops by only updating state when values actually change.
     */
    $effect(() => {
        const profile = $userProfile;
        const currentApps = apps;
        const currentAppsList = appsList;
        const now = Date.now();
        const oneDayMs = 24 * 60 * 60 * 1000; // 24 hours in milliseconds
        
        // First, try to load from user profile if available
        if (profile.random_explore_apps && profile.random_explore_apps_timestamp) {
            const age = now - profile.random_explore_apps_timestamp;
            
            if (age < oneDayMs) {
                // Use cached apps if still valid
                const existingApps = profile.random_explore_apps
                    .map(appId => currentApps[appId])
                    .filter(Boolean)
                    .slice(0, 5);
                
                if (existingApps.length >= 3) {
                    // Only update if the value actually changed to prevent infinite loops
                    const existingAppIds = existingApps.map(app => app.id).sort().join(',');
                    const currentAppIds = cachedRandomApps?.map(app => app.id).sort().join(',') || '';
                    
                    if (existingAppIds !== currentAppIds) {
                        cachedRandomApps = existingApps;
                        cachedRandomAppsTimestamp = profile.random_explore_apps_timestamp;
                    }
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
            const validApps = cachedRandomApps.filter(app => currentApps[app.id]);
            needsGeneration = age >= oneDayMs || validApps.length < 3;
        }
        
        if (needsGeneration && currentAppsList.length > 0) {
            // Generate new random apps
            const shuffled = [...currentAppsList].sort(() => Math.random() - 0.5);
            const newRandomApps = shuffled.slice(0, 5);
            const newRandomAppIds = newRandomApps.map(app => app.id);
            
            // Only update if the value actually changed to prevent infinite loops
            const newAppIds = newRandomAppIds.sort().join(',');
            const currentAppIds = cachedRandomApps?.map(app => app.id).sort().join(',') || '';
            
            if (newAppIds !== currentAppIds) {
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
     * Categorize apps into sections (duplicates allowed across categories).
     * 
     * **Categorization Logic:**
     * - Apps are assigned to categories: top_picks → most_used → new_apps → for_work → for_everyday_life
     * - Apps can appear in multiple categories (duplicates allowed across categories)
     * - Within each category, apps must be unique (no duplicate app.id)
     * - Maximum 5 apps per category
     * - "Top picks for you": Personalized recommendations (or random fallback)
     * - "Most used": Apps from API based on 30-day usage statistics
     * - "New apps": Apps with last_updated field, sorted by date (newest first)
     * - "For work": Apps with category: "work"
     * - "For everyday life": Apps with category: "personal"
     * 
     * **Important**: This function is pure and accepts all dependencies as parameters
     * to avoid reactive dependency issues that could cause infinite loops.
     */
    function categorizeApps(
        apps: AppMetadata[],
        topRecommended: AppMetadata[],
        mostUsed: AppMetadata[]
    ): Record<string, AppMetadata[]> {
        // Use internal category keys (not translated names)
        const categories: Record<string, AppMetadata[]> = {
            'top_picks': [],
            'most_used': [],
            'new_apps': [],
            'for_work': [],
            'for_everyday_life': []
        };
        
        const MAX_APPS_PER_CATEGORY = 5;
        
        /**
         * Helper function to safely add an app to a category.
         * Ensures no duplicate app.id within the same category.
         */
        function addAppToCategory(categoryKey: string, app: AppMetadata): void {
            const category = categories[categoryKey];
            // Check if app already exists in this category (by id)
            const alreadyExists = category.some(existingApp => existingApp.id === app.id);
            if (!alreadyExists && category.length < MAX_APPS_PER_CATEGORY) {
                category.push(app);
            }
        }
        
        // Priority 1: "Top picks for you" - Use personalized recommendations
        const topPicks = topRecommended.length > 0 
            ? topRecommended 
            : apps.slice(0, Math.min(MAX_APPS_PER_CATEGORY, apps.length));
        
        for (const app of topPicks) {
            addAppToCategory('top_picks', app);
        }
        
        // Priority 2: "Most used" - Apps from API based on 30-day usage statistics
        for (const app of mostUsed) {
            addAppToCategory('most_used', app);
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
        
        // Add recent apps first
        for (const app of recentApps) {
            addAppToCategory('new_apps', app);
        }
        
        // If not enough recent apps, fill with newest overall (avoiding duplicates)
        if (categories['new_apps'].length < MAX_APPS_PER_CATEGORY) {
            for (const { app } of appsWithDate) {
                addAppToCategory('new_apps', app);
                // Stop if we've reached the max
                if (categories['new_apps'].length >= MAX_APPS_PER_CATEGORY) {
                    break;
                }
            }
        }
        
        // Priority 4: "For work" - Apps with category: "work"
        const workApps = apps
            .filter(app => app.category === 'work')
            .slice(0, MAX_APPS_PER_CATEGORY);
        
        for (const app of workApps) {
            addAppToCategory('for_work', app);
        }
        
        // Priority 5: "For everyday life" - Apps with category: "personal"
        const everydayApps = apps
            .filter(app => app.category === 'personal')
            .slice(0, MAX_APPS_PER_CATEGORY);
        
        for (const app of everydayApps) {
            addAppToCategory('for_everyday_life', app);
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
     * This dispatches an event to the parent Settings component to navigate to app_store/all.
     */
    function showAllApps() {
        dispatch('openSettings', {
            settingsPath: 'app_store/all',
            direction: 'forward',
            icon: 'app',
            title: $text('settings.app_store.show_all_apps.text')
        });
    }
    
    /**
     * Categorize apps for display.
     * Uses $derived.by() to ensure all reactive dependencies (topRecommendedApps, mostUsedApps, appsList)
     * are properly tracked within the derived context to prevent infinite loops.
     * 
     * **Important**: All reactive dependencies must be accessed within this callback
     * so Svelte can properly track them and prevent infinite loops.
     * By passing them as parameters to categorizeApps, we ensure they're accessed
     * within the reactive context and avoid circular dependencies.
     */
    let categorizedApps = $derived.by(() => {
        // Access all reactive dependencies within the derived context
        // This ensures Svelte tracks them properly and prevents infinite loops
        const currentTopRecommended = topRecommendedApps;
        const currentMostUsed = mostUsedApps;
        const currentAppsList = appsList;
        
        // Call categorizeApps with all dependencies as parameters
        // This makes the function pure and prevents reactive dependency issues
        return categorizeApps(currentAppsList, currentTopRecommended, currentMostUsed);
    });
    
    /**
     * Convert categorized apps to entries for iteration.
     * This is a simple derived value that depends on categorizedApps.
     */
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
                            <AppStoreCard {app} onSelect={selectApp} />
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
    
</style>

