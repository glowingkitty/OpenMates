<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml

-->
<script lang="ts" module>
    import { writable, type Writable } from 'svelte/store';
    import { text } from '@repo/ui';
    // Use standard browser check for library compatibility (not SvelteKit-specific)
    const browser = typeof window !== 'undefined';
    
    // SSR-safe store initialization - only create stores on the client
    export const teamEnabled: Writable<boolean> = browser ? writable(true) : {
        subscribe: () => () => {},
        set: () => {},
        update: () => {}
    } as Writable<boolean>;
    
    export const settingsMenuVisible: Writable<boolean> = browser ? writable(false) : {
        subscribe: () => () => {},
        set: () => {},
        update: () => {}
    } as Writable<boolean>;
    
    // Removed local isMobileView - using global isMobileView from uiStateStore instead
</script>

<script lang="ts">
    import { onMount, createEventDispatcher, tick } from 'svelte';
    import { fly, fade, slide } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { authStore, isCheckingAuth, logout } from '../stores/authStore'; // Import logout action
    import { isMenuOpen } from '../stores/menuState';
    // import { getWebsiteUrl, routes } from '../config/links'; // Unused - help button disabled
    import { tooltip } from '../actions/tooltip';
    import { isInSignupProcess, isLoggingOut, showSignupFooter } from '../stores/signupState';
    import { userProfile, updateProfile } from '../stores/userProfile';
    import { getProfileImageBlobUrl } from '../services/profileImageService';
    import { getApiUrl } from '../config/api';
    import { settingsDeepLink } from '../stores/settingsDeepLinkStore';
    import { webSocketService } from '../services/websocketService';
    import { notificationStore } from '../stores/notificationStore'; // Import notification store for payment notifications
    import { incognitoMode } from '../stores/incognitoModeStore'; // Import incognito mode store
    import { demoMode } from '../stores/demoModeStore'; // Hide admin-only server/logs entries when demoing
    import { isMobileView } from '../stores/uiStateStore'; // Import global isMobileView store
    import { panelState } from '../stores/panelStateStore'; // Import panelState to sync with isSettingsOpen
    import { pendingMentionStore } from '../stores/pendingMentionStore';
    // Admin status is now read directly from userProfile.is_admin (synced during login)
    import { phasedSyncState } from '../stores/phasedSyncStateStore'; // Import phased sync state store
    import { isRestrictedSession } from '../stores/pairSessionStore'; // Pair session restricted mode
    
    // Import modular components
    import SettingsFooter from './settings/SettingsFooter.svelte';
    import CurrentSettingsPage from './settings/CurrentSettingsPage.svelte';
    import SettingsItem from './SettingsItem.svelte';
    import AppDetailsHeader from './settings/AppDetailsHeader.svelte';
    import SettingsMainHeader from './settings/SettingsMainHeader.svelte';
    
    // Import all settings route definitions and the dynamic wrapper components
    import { baseSettingsViews, AppDetailsWrapper, MateDetailsWrapper, EditPersonalDataEntryWrapper } from './settings/settingsRoutes';
    import AiModelDetailsWrapper from './settings/AiModelDetailsWrapper.svelte';
    import { matesMetadata } from '../data/matesMetadata';
    import { appSkillsStore } from '../stores/appSkillsStore';
    import { appSettingsMemoriesStore } from '../stores/appSettingsMemoriesStore';
    import { modelsMetadata } from '../data/modelsMetadata';
    import { providersMetadata, findProviderByName } from '../data/providersMetadata';
    import { getProviderIconUrl } from '../data/providerIcons';
    import { chatListCache } from '../services/chatListCache';
    import { chatMetadataCache } from '../services/chatMetadataCache';
    import { chatDB } from '../services/db';
    import type { Chat } from '../types/chat';
    import {
        getCategoryGradientColors,
        getFallbackIconForCategory,
        getLucideIcon,
        getValidIconName,
    } from '../utils/categoryUtils';
    import { LOCAL_CHAT_LIST_CHANGED_EVENT } from '../services/drafts/draftConstants';
    
    // Import the normal store instead of the derived one that was causing the error
    import { settingsNavigationStore } from '../stores/settingsNavigationStore';
    

    // Create event dispatcher for forwarding events to parent components
    const dispatch = createEventDispatcher();

    // Variable to store language change event handler
    let languageChangeHandler: () => void;

    // Props using Svelte 5 runes
    // Note: isLoggedIn prop is available but not currently used in this component
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    let { isLoggedIn }: { isLoggedIn?: boolean } = $props();
    
    // State for toggles and menu visibility
    let isMenuVisible = $state(false);
    // Timestamp when settings was last programmatically opened (e.g., via deep link from AppStoreCard click)
    // Used to prevent handleClickOutside from immediately closing settings on the same click event.
    // On mobile, the same tap that opens settings also triggers the document click listener which would close it.
    let lastProgrammaticOpenTime = 0;
    let isTeamEnabled = $state(true);
    // Use incognito mode store instead of local state
    let isIncognitoEnabled = $derived($incognitoMode);
    let isGuestEnabled = $state(false);
    let isOfflineEnabled = $state(false);
    let showSubmenuInfo = $state(false); // New variable to control submenu info visibility
    let navButtonLeft = $state(false);
    let hideNavButton = $state(false); // New variable to control nav button visibility
    
    // Track viewport width for reactive dimmed class logic
    // Settings menu becomes overlay at 1100px, so we need to track this
    let viewportWidth = $state(typeof window !== 'undefined' ? window.innerWidth : 0);

    // Add reference to settings content element
    let settingsContentElement: HTMLElement | undefined = $state();
    let profileContainer: HTMLElement | undefined = $state();
    let profileContainerWrapper: HTMLElement | undefined = $state(); // Add reference for the wrapper

    /**
     * Scroll position memory for the "All Apps" page only.
     * When the user opens an app from the All Apps list and then presses back,
     * we restore the scroll offset so they don't have to scroll down again.
     * All other settings navigation always scrolls to top.
     */
    let allAppsScrollPosition = $state<number>(0);

    // Get help link from routes
    // Note: Help button is currently commented out in template (line ~1452)
    // const baseHelpLink = getWebsiteUrl(routes.docs.userGuide_settings || '/docs/userguide/settings');
    // let currentHelpLink = $state(baseHelpLink);

    /**
     * Dynamically build settingsViews including app detail routes and nested sub-routes.
     * This creates:
     * - app_store/{app_id} routes for each available app
     * - app_store/{app_id}/skill/{skill_id} routes for each skill
     * - app_store/{app_id}/focus/{focus_mode_id} routes for each focus mode
     * - app_store/{app_id}/settings_memories routes for apps with settings/memories
     */
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    function buildSettingsViews(): Record<string, any> {
        const views = { ...baseSettingsViews };
        
        // Add app detail routes dynamically
        const apps = appSkillsStore.getState().apps;
        for (const appId of Object.keys(apps)) {
            const app = apps[appId];
            
            // Main app details route
            const appRoute = `app_store/${appId}`;
            views[appRoute] = AppDetailsWrapper;

            // Reminder app: add create route for the reminder creation settings page
            if (appId === 'reminder') {
                views[`app_store/reminder/create`] = AppDetailsWrapper;
            }

            // Add skill detail routes and their provider sub-routes
            if (app.skills && app.skills.length > 0) {
                for (const skill of app.skills) {
                    const skillRoute = `app_store/${appId}/skill/${skill.id}`;
                    views[skillRoute] = AppDetailsWrapper;

                    // Register provider sub-routes for each provider listed on this skill
                    // skill.providers is an array of display name strings (e.g. ["Anthropic", "Google"])
                    if (skill.providers && skill.providers.length > 0) {
                        for (const providerName of skill.providers) {
                            const providerMeta = findProviderByName(providerName);
                            if (providerMeta) {
                                const providerRoute = `app_store/${appId}/skill/${skill.id}/provider/${providerMeta.id}`;
                                views[providerRoute] = AppDetailsWrapper;
                            }
                        }
                    }
                }
            }
            
            // Add focus mode detail routes
            if (app.focus_modes && app.focus_modes.length > 0) {
                for (const focusMode of app.focus_modes) {
                    const focusRoute = `app_store/${appId}/focus/${focusMode.id}`;
                    views[focusRoute] = AppDetailsWrapper;
                }
            }
            
            // Add settings/memories category routes if app has settings_and_memories
            if (app.settings_and_memories && app.settings_and_memories.length > 0) {
                for (const category of app.settings_and_memories) {
                    const categoryRoute = `app_store/${appId}/settings_memories/${category.id}`;
                    views[categoryRoute] = AppDetailsWrapper;
                    
                    // Add create entry route for each category
                    const createRoute = `app_store/${appId}/settings_memories/${category.id}/create`;
                    views[createRoute] = AppDetailsWrapper;
                }
            }
        }
        
        // Add mates detail routes dynamically (mates/{mateId})
        for (const mate of matesMetadata) {
            views[`mates/${mate.id}`] = MateDetailsWrapper;
        }
        
        return views;
    }
    
    /**
     * Track dynamically added entry detail routes.
     * Entry detail routes have dynamic entry IDs that aren't known at build time,
     * so they need to be added dynamically when navigated to.
     */
    let dynamicEntryRoutes = $state<Set<string>>(new Set());

    /**
     * Track dynamically added personal data edit routes.
     * Pattern: privacy/hide-personal-data/edit-{type}/{entryId}
     */
    let dynamicPersonalDataEditRoutes = $state<Set<string>>(new Set());
    
    // Reactive settingsViews that includes dynamic app routes and entry detail routes
    // Entry detail routes are added dynamically when navigated to (tracked in dynamicEntryRoutes)
    let allSettingsViews = $derived.by(() => {
        const views = buildSettingsViews();
        
        // Add any dynamically registered entry detail routes
        // These are routes like: app_store/{app_id}/settings_memories/{category_id}/entry/{entry_id}
        // or: ai/model/{model_id} (top-level AI settings model detail)
        for (const route of dynamicEntryRoutes) {
            if (/^ai\/model\//.test(route)) {
                views[route] = AiModelDetailsWrapper;
            } else {
                views[route] = AppDetailsWrapper;
            }
        }

        // Add any dynamically registered personal data edit routes
        // These are routes like: privacy/hide-personal-data/edit-name/{entryId}
        for (const route of dynamicPersonalDataEditRoutes) {
            views[route] = EditPersonalDataEntryWrapper;
        }
        
        return views;
    });

    // Payment status - check if payment is enabled (self-hosted mode detection)
    let paymentEnabled = $state(true); // Default to true, will be updated on mount
    let _serverEdition = $state<string | null>(null); // Server edition for display (currently unused but kept for future use)
    let isSelfHosted = $state(false); // Self-hosted status from request-based validation
    
    // Reactive settingsViews that filters out server options for non-admins and payment routes when payment disabled
    // For non-authenticated users, show interface settings (and nested language settings), app store, and share chat
    // This allows them to explore available features like apps and share demo chats
    // Share chat (shared/share) is available for non-authenticated users to share demo chats
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let settingsViews = $derived.by((): Record<string, any> => {
        const isAuthenticated = $authStore.isAuthenticated;
        const restrictedMode = $isRestrictedSession;
        const demoModeOn = $demoMode;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        return Object.entries(allSettingsViews).reduce((filtered: Record<string, any>, [key, component]) => {
            // Demo mode: hide admin "Server" section and the "Logs" entry so screenshots /
            // screen recordings don't expose infrastructure internals. Toggled via
            // window.demo_mode.on() / .off() in the browser console.
            if (demoModeOn && (key === 'logs' || key.startsWith('server'))) {
                return filtered;
            }

            // Filter out payment-related routes if self-hosted (use isSelfHosted from request-based validation)
            // This is more accurate than paymentEnabled alone, as paymentEnabled can be true for localhost in dev mode
            if (isSelfHosted) {
                // Remove billing and gift card routes
                if (key === 'billing' || key.startsWith('billing/') || 
                    key === 'shared/tip') { // Tips also require payment
                    return filtered; // Skip this route
                }
            }

            // In restricted (pair) sessions, hide account settings and settings/memories.
            // The sessions page is still accessible so users can see and manage their sessions.
            // Security sub-pages (passkeys, password, 2FA, recovery-key) are blocked inside SettingsSecurity.
            if (restrictedMode) {
                if (
                    key === 'account' ||
                    (key.startsWith('account/') && key !== 'account/security' && key !== 'account/security/sessions' && !key.startsWith('account/security/sessions/')) ||
                    key === 'settings_memories' ||
                    key === 'billing' || key.startsWith('billing/')
                ) {
                    return filtered; // Hidden in restricted mode
                }
            }
            
            // For non-authenticated users, include interface settings (top-level and nested), 
            // app store (including app details), mates (browse only), share chat (for sharing demo chats),
            // newsletter, support, report issue, and the pricing overview page.
            // App store and mates are read-only for non-authenticated users (browse only, no modifications)
            if (!isAuthenticated) {
                if (key === 'interface' || key.startsWith('interface/') ||
                    key === 'ai' || key.startsWith('ai/') ||
                    key === 'app_store' || key.startsWith('app_store/') ||
                    key === 'mates' || key.startsWith('mates/') ||
                    key === 'shared/share' || key === 'newsletter' ||
                    key === 'support' || key.startsWith('support/') ||
                    key === 'report_issue' || key.startsWith('report_issue/') || key === 'account/delete' ||
                    key === 'pricing') {
                    filtered[key] = component;
                }
            } else {
                // For authenticated users, include all non-server settings, or include server settings if user is admin.
                // Exclude 'pricing' — authenticated users have the full 'billing' section instead.
                // Admin status is read from userProfile.is_admin (synced during login, no separate API call needed)
                if (key !== 'pricing' && (!key.startsWith('server') || $userProfile.is_admin)) {
                    filtered[key] = component;
                }
            }
            return filtered;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        }, {} as Record<string, any>);
    });

    // Track navigation path parts for breadcrumb-style navigation
    let navigationPath: string[] = $state([]);
    // Track the path we navigated from (e.g., 'app_store/all' when opening an app from All Apps).
    // Used to ensure back navigation returns to the correct parent view.
    let cameFromPath = $state<string | null>(null);
    // Optional human-readable title override for the cameFrom path, used in breadcrumb display.
    // When set, replaces the auto-derived label for the cameFrom path segment.
    let cameFromTitleOverride = $state<string | null>(null);
    let breadcrumbLabel = $state($text('common.settings'));
    let fullBreadcrumbLabel = $state('');
    let navButtonElement: HTMLElement | undefined = $state();
    let currentPageInstance: CurrentSettingsPage | null = $state(null); // Reference to child component instance

    // Maximum width for breadcrumb text (in pixels)
    const MAX_BREADCRUMB_WIDTH = 220; // Adjusted to leave space for the back icon

    const HEADER_CHAT_ICON_LIMIT = 8;
    const HEADER_CHAT_ICON_FETCH_LIMIT = 24;
    const HEADER_CHAT_ICON_REFRESH_DEBOUNCE_MS = 120;
    const HEADER_CHAT_ICON_SIDE_TOP_SLOTS: Record<'left' | 'right', number[]> = {
        left: [19, 36, 53, 70],
        right: [25, 42, 59, 76],
    };

    interface RecentHeaderChatIcon {
        chatId: string;
        iconName: string;
        category: string;
    }

    interface HeaderChatDecorIcon {
        key: string;
        iconName: string;
        side: 'left' | 'right';
        topPercent: number;
        insetPx: number;
        rotationDeg: number;
        gradientStart: string;
        gradientEnd: string;
    }

    let headerChatDecorIcons = $state<HeaderChatDecorIcon[]>([]);
    let headerIconRefreshTimer: ReturnType<typeof setTimeout> | null = null;
    let isRefreshingHeaderIcons = false;

    function hashToUnitInterval(seed: string): number {
        let hash = 2166136261;
        for (let i = 0; i < seed.length; i++) {
            hash ^= seed.charCodeAt(i);
            hash = Math.imul(hash, 16777619);
        }
        return (hash >>> 0) / 4294967295;
    }

    function deterministicValue(seed: string, min: number, max: number): number {
        return min + (max - min) * hashToUnitInterval(seed);
    }

    async function loadRecentHeaderChatIcons(): Promise<RecentHeaderChatIcon[]> {
        let chats: Chat[] | null = chatListCache.getCache();
        if (!chats || chats.length === 0) {
            chats = await chatDB.getAllChats(undefined, { limit: HEADER_CHAT_ICON_FETCH_LIMIT });
        }
        if (!chats || chats.length === 0) {
            return [];
        }

        const sortedChats = [...chats]
            .filter((chat) => !chat.is_hidden && !chat.is_hidden_candidate)
            .sort((a, b) => b.last_edited_overall_timestamp - a.last_edited_overall_timestamp)
            .slice(0, HEADER_CHAT_ICON_FETCH_LIMIT);

        const resolved = await Promise.all(sortedChats.map(async (chat) => {
            let rawIcon = chat.icon?.trim() ?? '';
            let category = chat.category?.trim() ?? '';

            if ((!rawIcon || !category) && (chat.encrypted_icon || chat.encrypted_category)) {
                const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
                if (metadata) {
                    rawIcon = rawIcon || (metadata.icon?.trim() ?? '');
                    category = category || (metadata.category?.trim() ?? '');
                }
            }

            if (!category) {
                category = 'general_knowledge';
            }

            const iconName = rawIcon
                ? getValidIconName(rawIcon, category)
                : getFallbackIconForCategory(category);

            return {
                chatId: chat.chat_id,
                iconName,
                category,
            };
        }));

        /* Deduplicate by icon name — each icon should appear at most once. */
        const seen = new Set<string>();
        const unique = resolved.filter((r) => {
            if (seen.has(r.iconName)) return false;
            seen.add(r.iconName);
            return true;
        });

        return unique.slice(0, HEADER_CHAT_ICON_LIMIT);
    }

    function buildHeaderDecorIcons(icons: RecentHeaderChatIcon[]): HeaderChatDecorIcon[] {
        const leftSlots = [...HEADER_CHAT_ICON_SIDE_TOP_SLOTS.left];
        const rightSlots = [...HEADER_CHAT_ICON_SIDE_TOP_SLOTS.right];
        const decor: HeaderChatDecorIcon[] = [];

        for (let index = 0; index < icons.length; index++) {
            const item = icons[index];
            let side: 'left' | 'right' = index % 2 === 0 ? 'left' : 'right';

            if (side === 'left' && leftSlots.length === 0) side = 'right';
            if (side === 'right' && rightSlots.length === 0) side = 'left';
            if ((side === 'left' && leftSlots.length === 0) || (side === 'right' && rightSlots.length === 0)) {
                break;
            }

            const topPercent = side === 'left' ? leftSlots.shift() ?? 50 : rightSlots.shift() ?? 50;
            const insetPx = Math.round(deterministicValue(`${item.chatId}-inset`, 6, 18));
            const rotationDeg = Math.round(deterministicValue(`${item.chatId}-rotation`, -28, 28));
            const gradient = getCategoryGradientColors(item.category) ?? getCategoryGradientColors('general_knowledge');

            decor.push({
                key: `${item.chatId}-${item.iconName}-${side}`,
                iconName: item.iconName,
                side,
                topPercent,
                insetPx,
                rotationDeg,
                gradientStart: gradient?.start ?? '#de1e66',
                gradientEnd: gradient?.end ?? '#ff763b',
            });
        }

        return decor;
    }

    async function refreshHeaderChatDecorIcons(): Promise<void> {
        if (isRefreshingHeaderIcons) return;
        isRefreshingHeaderIcons = true;
        try {
            const recentIcons = await loadRecentHeaderChatIcons();
            headerChatDecorIcons = buildHeaderDecorIcons(recentIcons);
        } catch (error) {
            if (error instanceof Error && error.message?.includes('blocked during logout')) {
                console.debug('[Settings] DB unavailable during cleanup, skipping header icons');
            } else {
                console.error('[Settings] Failed to load recent chat icons for settings header:', error);
            }
        } finally {
            isRefreshingHeaderIcons = false;
        }
    }

    function scheduleHeaderChatDecorIconRefresh(): void {
        if (headerIconRefreshTimer) {
            clearTimeout(headerIconRefreshTimer);
        }
        headerIconRefreshTimer = setTimeout(() => {
            void refreshHeaderChatDecorIcons();
        }, HEADER_CHAT_ICON_REFRESH_DEBOUNCE_MS);
    }

    // Function to calculate the width of text with the correct font
    function getTextWidth(text: string, font = '14px "Lexend Deca Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'): number {
        // Create a canvas element to measure text width
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        context.font = font;
        
        // Apply the font weight if needed for more accurate calculations
        if (window.getComputedStyle) {
            try {
                const style = window.getComputedStyle(document.body);
                const fontWeight = style.getPropertyValue('--font-weight-bold') || '700';
                context.font = `${fontWeight} ${font}`;
            } catch {
                console.warn('Could not get computed style, using default font weight');
            }
        }
        
        const metrics = context.measureText(text);
        return metrics.width;
    }
    
    // Function to create optimal breadcrumb text that fits available space
    function createOptimalBreadcrumb(pathLabels: string[]): string {
        // Save full breadcrumb first
        fullBreadcrumbLabel = pathLabels.join(' / ');
        
        // If full breadcrumb fits, use it
        if (getTextWidth(fullBreadcrumbLabel) <= MAX_BREADCRUMB_WIDTH) {
            return fullBreadcrumbLabel;
        }
        
        // If we only have one or two items, just use ellipsis + last item
        if (pathLabels.length <= 2) {
            return '... / ' + pathLabels[pathLabels.length - 1];
        }
        
        // Try different shortened versions
        let shortened = '';
        // Always include Settings (first element) and current path (last elements)
        // Try adding one more segment from the end each time
        for (let visibleSegments = 2; visibleSegments <= pathLabels.length; visibleSegments++) {
            const endSegments = pathLabels.slice(-visibleSegments);
            const candidateText = '... / ' + endSegments.join(' / ');
            
            if (getTextWidth(candidateText) <= MAX_BREADCRUMB_WIDTH) {
                shortened = candidateText;
            } else {
                // If this version doesn't fit, use previous version
                break;
            }
        }
        
        // If no shortened version fits, just show the last segment
        if (!shortened) {
            shortened = '... / ' + pathLabels[pathLabels.length - 1];
        }
        
        return shortened;
    }

    // Function to update breadcrumb label based on navigation path
    function updateBreadcrumbLabel() {
        if (navigationPath.length <= 0) {
            breadcrumbLabel = $text('common.settings');
            fullBreadcrumbLabel = breadcrumbLabel;
            return;
        }
        
        // Create breadcrumb label with all path segments
        const pathLabels = [];
        
        // Always start with "Settings"
        pathLabels.push($text('common.settings'));
        
        // Track if we've already added the app name for app_store routes
        // This prevents duplicate app names when navigating to app_store/{appId}
        let appNameAdded = false;
        
        // Add each path segment's translated name (except the last one which is current view)
        for (let i = 0; i < navigationPath.length - 1; i++) {
            // Build the full path up to this segment
            const pathUpToSegment = navigationPath.slice(0, i + 1);
            const pathString = pathUpToSegment.join('/');
            
            // For non-authenticated users accessing 'shared/share', skip the 'shared' segment
            // This makes the breadcrumb show just "Settings" instead of "Settings / Shared"
            if (!$authStore.isAuthenticated && pathString === 'shared') {
                continue; // Skip the 'shared' segment for non-authenticated users
            }
            
            // Handle app_store routes specially - use actual app/skill names from metadata
            if (pathString === 'app_store') {
                // If the user arrived via the Settings & Memories hub, replace the full
                // "App Store / {App Name}" chain with just "App Settings & Memories"
                // so the breadcrumb reads: Settings / App Settings & Memories
                if (cameFromPath === 'settings_memories') {
                    // Use the title override if provided, otherwise fall back to the standard key
                    pathLabels.push(cameFromTitleOverride ?? $text('settings.settings_memories'));
                    // Skip all remaining app_store sub-segments — they belong to the old chain
                    break;
                }
                if (cameFromPath === 'ai') {
                    // Arrived from top-level AI settings — show "AI" instead of "App Store / AI"
                    pathLabels.push(cameFromTitleOverride ?? $text('settings.ai'));
                    break;
                }
                // This is the base app_store route - add "App Store" translation
                const translationKey = 'settings.app_store';
                pathLabels.push($text(translationKey));
                // If we navigated here from "All Apps", inject "All Apps" into the breadcrumb
                // so the trail reads: Settings / App Store / All Apps / {App Name}
                if (cameFromPath === 'app_store/all') {
                    pathLabels.push($text('settings.app_store.show_all_apps'));
                }
            } else if (pathString.startsWith('app_store/') && pathString !== 'app_store/all') {
                const pathParts = pathString.replace('app_store/', '').split('/');
                const appId = pathParts[0];
                const app = appSkillsStore.getState().apps[appId];
                
                if (app && !appNameAdded) {
                    // Use translated app name (only add once to prevent duplicates)
                    const appName = app.name_translation_key ? $text(app.name_translation_key) : appId;
                    pathLabels.push(appName);
                    appNameAdded = true;
                }
                
                // Handle nested routes (skill, focus, settings_memories)
                // Only process if this segment contains the nested route info
                if (pathParts.length === 3 && pathParts[1] === 'settings_memories') {
                    // This is the category page segment
                    const categoryId = pathParts[2];
                    const category = app?.settings_and_memories?.find(c => c.id === categoryId);
                    if (category && category.name_translation_key) {
                        pathLabels.push($text(category.name_translation_key));
                    }
                } else if (pathParts.length === 4 && pathParts[1] === 'settings_memories' && pathParts[3] === 'create') {
                    // This is the create page segment - add category name
                    const categoryId = pathParts[2];
                    const category = app?.settings_and_memories?.find(c => c.id === categoryId);
                    if (category && category.name_translation_key) {
                        pathLabels.push($text(category.name_translation_key));
                    }
                } else if ((pathParts.length === 5 || (pathParts.length === 6 && pathParts[5] === 'edit')) && pathParts[1] === 'settings_memories' && pathParts[3] === 'entry') {
                    // This is the entry detail or edit page segment - add category name
                    const categoryId = pathParts[2];
                    const category = app?.settings_and_memories?.find(c => c.id === categoryId);
                    if (category && category.name_translation_key) {
                        pathLabels.push($text(category.name_translation_key));
                    }
                } else if (pathParts.length === 2 && pathParts[0] === 'reminder' && pathParts[1] === 'create') {
                    // Reminder create page: add "Create reminder" to breadcrumb
                    pathLabels.push($text('reminder.settings.create_title'));
                } else if (pathParts.length === 3 && pathParts[1] === 'skill') {
                    const skillId = pathParts[2];
                    const skill = app?.skills?.find(s => s.id === skillId);
                    if (skill && skill.name_translation_key) {
                        pathLabels.push($text(skill.name_translation_key));
                    }
                } else if (pathParts.length === 3 && pathParts[1] === 'focus') {
                    const focusModeId = pathParts[2];
                    const focusMode = app?.focus_modes?.find(f => f.id === focusModeId);
                    if (focusMode && focusMode.name_translation_key) {
                        pathLabels.push($text(focusMode.name_translation_key));
                    }
                }

                if (!app) {
                    // Fallback to translation key if app not found
                    const translationKeyParts = pathUpToSegment.map(segment => segment.replace(/-/g, '_'));
                    const translationKey = `settings.${translationKeyParts.join('.')}`;
                    pathLabels.push($text(translationKey));
                }
            } else {
                // For other routes, use translation keys
                const translationKeyParts = pathUpToSegment.map(segment => segment.replace(/-/g, '_'));
                const translationKey = `settings.${translationKeyParts.join('.')}`;
                pathLabels.push($text(translationKey));
            }
        }
        
        // Create optimal breadcrumb display that fits
        breadcrumbLabel = createOptimalBreadcrumb(pathLabels);
    }
    
    // Update breadcrumb on window resize
    function handleResize() {
        // Only update if we already have a navigation path
        if (navigationPath.length > 0) {
            updateBreadcrumbLabel();
        }
        
        // Update mobile state on resize
        updateMobileState();
    }

    // Reactive variables
    // Show settings icon: ALWAYS visible (simplified from complex conditional logic)
    let showSettingsIcon = $derived(true);
    
    let username = $derived($userProfile.username || '');
    let isInSignupMode = $derived($isInSignupProcess);

    /**
     * Resolved blob URL (or legacy https:// URL) for the user's profile image.
     * Since the new profile images are served by an authenticated API endpoint,
     * we cannot use a direct URL in `<img>` or CSS `background-image` — the browser
     * won't send credentials. This effect fetches via the profileImageService
     * (which handles both legacy public URLs and new proxy paths) and stores a
     * displayable blob URL.
     */
    let resolvedProfileImageBlobUrl = $state<string | null>(null);

    $effect(() => {
        const url = $userProfile.profile_image_url;
        const userId = $userProfile.user_id;
        if (!url || !userId) {
            resolvedProfileImageBlobUrl = null;
            return;
        }
        // Stale-closure guard: if the effect re-runs before the previous fetch
        // resolves (e.g. because an unrelated store field like last_opened changed),
        // we cancel the old .then() so it cannot overwrite the latest state.
        let cancelled = false;
        getProfileImageBlobUrl(url, getApiUrl(), userId).then((resolved) => {
            if (!cancelled) {
                resolvedProfileImageBlobUrl = resolved;
            }
        });
        return () => { cancelled = true; };
    });

    // State to track active submenu view
    let activeSettingsView = $state('main');
    let activeAccountId = $state<string | null>(null);
    let direction = $state('forward');
    let activeSubMenuIcon = $state('');
    let activeSubMenuTitleKey = $state(''); // Store the translation key
    let activeSubMenuTitleRaw = $state(''); // Raw title (used when no translation key, e.g. model name)
    // SVG path for provider icon (e.g. "icons/anthropic.svg") — set when on a model detail page
    let activeSubMenuProviderIconSvg = $state('');
    
    // Reactive translation of the submenu title — falls back to raw title when no key
    let activeSubMenuTitle = $derived(activeSubMenuTitleKey ? $text(activeSubMenuTitleKey) : activeSubMenuTitleRaw);
    
    // True when the header should show a provider icon (model or provider detail pages)
    let isModelDetailPage = $derived(
        // app_store model/provider detail pages
        (activeSettingsView.startsWith('app_store/') &&
        (
            /^app_store\/[^/]+\/skill\/[^/]+\/model\/[^/]+$/.test(activeSettingsView) ||
            /^app_store\/[^/]+\/skill\/[^/]+\/provider\/[^/]+$/.test(activeSettingsView)
        )) ||
        // Top-level AI settings model detail pages (ai/model/{modelId})
        /^ai\/model\/[^/]+$/.test(activeSettingsView)
    );

    // True when the header should show a mate profile image (mate detail pages)
    let isMateDetailPage = $derived(
        activeSettingsView.startsWith('mates/') && activeSettingsView !== 'mates'
    );
    
    // Track if we're in an app store sub-page (not the main app_store or 'all' page)
    // This is used to render the app icon properly in the header
    let isAppStoreSubPage = $derived(
        activeSettingsView.startsWith('app_store/') && 
        activeSettingsView !== 'app_store' && 
        activeSettingsView !== 'app_store/all'
    );

    /**
     * True when we're on the TOP-LEVEL app details page (app_store/{appId} only,
     * NOT deeper sub-pages like skill/focus/settings_memories).
     * Explicitly excludes 'app_store/all' which is the "Show all apps" list view —
     * that page uses the normal submenu-info header, NOT the gradient AppDetailsHeader banner.
     * When true the AppDetailsHeader banner takes over the header area, so:
     *   - The normal settings-header becomes transparent with white text
     *   - The submenu-info block is hidden (the banner shows it instead)
     */
    let isAppTopLevelPage = $derived(
        activeSettingsView !== 'app_store/all' &&
        /^app_store\/[^/]+$/.test(activeSettingsView)
    );

    /**
     * True when we're on a skill, focus, or settings/memories sub-page
     * (but NOT model detail pages, which have their own provider-icon header treatment).
     * When true the AppDetailsHeader banner shows the sub-item (skill/focus/memory) name
     * instead of the top-level app description + capability counts.
     */
    let isAppSubPage = $derived(
        (/^app_store\/[^/]+\/(skill|focus|settings_memories)\//.test(activeSettingsView) ||
         activeSettingsView === 'app_store/reminder/create' ||
         /^app_store\/reminder\/entry\//.test(activeSettingsView)) &&
        !isModelDetailPage &&
        // When arrived from top-level AI settings, use default settings gradient instead of app gradient
        cameFromPath !== 'ai'
    );

    /**
     * True when any gradient banner (top-level or sub-page) should be visible.
     * Used to suppress the normal submenu-info header and shrink the settings-header.
     */
    let isAnyAppBannerPage = $derived(isAppTopLevelPage || isAppSubPage);

    /**
     * True when the user is on a standard settings sub-page (Privacy, Billing, Usage, etc.)
     * that should receive the gradient banner treatment.
     * Excludes: main view, app store pages (handled by AppDetailsHeader in app mode),
     * mate detail pages (have their own header treatment), model detail pages.
     */
    let isStandardSubPage = $derived(
        activeSettingsView !== 'main' &&
        !isAnyAppBannerPage &&
        !isMateDetailPage &&
        !isModelDetailPage
    );

    /**
     * True when ANY gradient banner should be visible (app store OR standard sub-page).
     * Used to suppress the normal submenu-info block and shrink the settings-header.
     */
    let isAnyBannerPage = $derived(isAnyAppBannerPage || isStandardSubPage);

    /**
     * Description translation keys for standard settings pages.
     * These are displayed in the gradient banner for the corresponding route.
     * Keys without a description are intentionally absent (banner shows title only).
     */
    const settingsPageDescriptionKeys: Record<string, string> = {
        'pricing': 'settings.pricing.description',
        'privacy': 'settings.privacy.description',
        'billing': 'settings.billing.description',
        'account': 'settings.account.description',
        'interface': 'settings.interface.description',
        'support': 'settings.support.description',
        'developers': 'settings.developers_description',
        'mates': 'settings.mates.description',
        'ai': 'settings.ai.description',
        'security': 'settings.security.description',
        'newsletter': 'settings.newsletter.description',
        'server': 'settings.server.description',
        'shared': 'settings.shared.description',
        'app_store': 'settings.app_store.description',
        'settings_memories': 'settings.settings_memories.description',
    };

    /**
     * The description string for the currently active standard settings sub-page banner.
     * Uses the top-level segment of the path for lookup (e.g. 'billing' for 'billing/buy-credits').
     * Returns empty string when no description key is registered.
     */
    let activeSubMenuDescription = $derived.by(() => {
        if (!isStandardSubPage) return '';
        // Use the top-level path segment for description lookup
        const topSegment = activeSettingsView.split('/')[0];
        const key = settingsPageDescriptionKeys[topSegment];
        return key ? $text(key) : '';
    });

    /**
     * Aggregate capability stats for the App Store header banner.
     * Shows total apps, skills, focus modes, and settings & memory types across all apps.
     * Only computed when the app_store page is active to avoid unnecessary work.
     */
    let appStoreHeaderStats = $derived.by(() => {
        if (activeSettingsView !== 'app_store' && activeSettingsView !== 'app_store/all') return [];
        const allApps = Object.values(appSkillsStore.getState().apps);
        const totalApps = allApps.length;
        const totalSkills = allApps.reduce((sum, app) => sum + (app.skills?.length ?? 0), 0);
        const totalFocusModes = allApps.reduce((sum, app) => sum + (app.focus_modes?.length ?? 0), 0);
        const totalMemories = allApps.reduce((sum, app) => sum + (app.settings_and_memories?.length ?? 0), 0);
        return [
            { count: totalApps,      iconClass: 'apps' },
            { count: totalSkills,    iconClass: 'skill' },
            { count: totalFocusModes, iconClass: 'focus' },
            { count: totalMemories,  iconClass: 'memory' },
        ];
    });

    /**
     * Data needed to render the AppDetailsHeader for sub-pages (skill/focus/memories).
     * Returns the parent appId and the item-specific data (name, typeLabel, description).
     * Returns null when not on a sub-page.
     */
    let subPageBannerData = $derived.by((): {
        appId: string;
        itemName: string;
        itemTypeLabel: string;
        description: string;
        /** Icon name (without .svg) for the item-specific icon shown in AppDetailsHeader */
        iconName?: string;
        /** Icon gradient type for the item-specific icon */
        iconType?: 'skill' | 'focus' | 'memory';
        /** Mention syntax inserted into MessageInput when clicking the header identity. */
        mentionSyntax?: string;
    } | null => {
        if (!isAppSubPage) return null;

        // Special case: reminder/create page — show "Create reminder" with reminder gradient
        if (activeSettingsView === 'app_store/reminder/create') {
            const appMeta = appSkillsStore.getState().apps['reminder'];
            if (!appMeta) return null;
            const rawIcon = appMeta.icon_image;
            const iconName = rawIcon ? rawIcon.replace(/\.svg$/, '').trim() : undefined;
            return {
                appId: 'reminder',
                itemName: $text('reminder.settings.create_title'),
                itemTypeLabel: '',
                description: '',
                iconName,
                iconType: 'skill',
            };
        }

        // Reminder entry detail/edit page
        if (/^app_store\/reminder\/entry\//.test(activeSettingsView)) {
            const appMeta = appSkillsStore.getState().apps['reminder'];
            if (!appMeta) return null;
            const rawIcon = appMeta.icon_image;
            const iconName = rawIcon ? rawIcon.replace(/\.svg$/, '').trim() : undefined;
            const isEdit = activeSettingsView.endsWith('/edit');
            return {
                appId: 'reminder',
                itemName: isEdit ? $text('common.edit') : $text('apps.reminder.active_reminders.title'),
                itemTypeLabel: '',
                description: '',
                iconName,
                iconType: 'skill',
            };
        }

        // Parse the route: app_store/{appId}/{type}/{itemId}
        const match = activeSettingsView.match(
            /^app_store\/([^/]+)\/(skill|focus|settings_memories)\/([^/]+)/
        );
        if (!match) return null;

        const [, appId, type, itemId] = match;
        const apps = appSkillsStore.getState().apps;
        const appMeta = apps[appId];
        if (!appMeta) return null;

        if (type === 'skill') {
            const skill = appMeta.skills.find(s => s.id === itemId);
            if (!skill) return null;
            // Derive icon name from skill's icon_image (strip .svg); fall back to app icon
            const rawIcon = skill.icon_image || appMeta.icon_image;
            const iconName = rawIcon ? rawIcon.replace(/\.svg$/, '').trim() : undefined;
            return {
                appId,
                itemName: skill.name_translation_key ? $text(skill.name_translation_key) : itemId,
                itemTypeLabel: $text('common.skill'),
                description: skill.description_translation_key
                    ? $text(skill.description_translation_key)
                    : '',
                iconName,
                iconType: 'skill',
                mentionSyntax: `@skill:${appId}:${itemId}`,
            };
        }

        if (type === 'focus') {
            const focus = appMeta.focus_modes.find(f => f.id === itemId);
            if (!focus) return null;
            const rawIcon = focus.icon_image || appMeta.icon_image;
            const iconName = rawIcon ? rawIcon.replace(/\.svg$/, '').trim() : undefined;
            return {
                appId,
                itemName: focus.name_translation_key ? $text(focus.name_translation_key) : itemId,
                itemTypeLabel: $text('settings.app_store.focus_mode'),
                description: focus.description_translation_key
                    ? $text(focus.description_translation_key)
                    : '',
                iconName,
                iconType: 'focus',
                mentionSyntax: `@focus:${appId}:${itemId}`,
            };
        }

        if (type === 'settings_memories') {
            const cat = appMeta.settings_and_memories.find(c => c.id === itemId);
            if (!cat) return null;
            const rawIcon = cat.icon_image || appMeta.icon_image;
            const iconName = rawIcon ? rawIcon.replace(/\.svg$/, '').trim() : undefined;
            
            // Check for deeper sub-routes: create or entry detail
            const subRoute = activeSettingsView.replace(
                `app_store/${appId}/settings_memories/${itemId}`, ''
            );
            const categoryName = cat.name_translation_key ? $text(cat.name_translation_key) : itemId;
            
            if (subRoute === '/create') {
                // Create entry sub-page: show "Add entry" title with category context
                return {
                    appId,
                    itemName: $text('common.add_entry'),
                    itemTypeLabel: categoryName,
                    description: cat.description_translation_key
                        ? $text(cat.description_translation_key)
                        : '',
                    iconName,
                    iconType: 'memory',
                    mentionSyntax: `@memory:${appId}:${itemId}:${cat.type}`,
                };
            }
            
            if (subRoute.startsWith('/entry/')) {
                // Entry detail sub-page: show entry title on line 1, category name on line 2.
                // The typeLabel is the category name (e.g. "Trips"), not "Settings & Memories Entry".
                // Clicking the header copies a @memory-entry mention for real entries (or @memory for examples).
                const rawEntryId = subRoute.replace('/entry/', '').replace('/edit', '');
                const entryId = rawEntryId;
                let entryTitle = categoryName;
                let mentionSyntax = `@memory:${appId}:${itemId}:${cat.type}`;
                
                if (entryId.startsWith('example_')) {
                    // Example entry: get title from example_translation_keys or example_entries
                    const exIdx = parseInt(entryId.replace('example_', ''), 10);
                    const exEntries = cat.example_entries ?? [];
                    const exKeys = cat.example_translation_keys ?? [];
                    
                    if (exEntries[exIdx]) {
                        // Try to get title from example_entries (use is_title field)
                        const titleField = cat.schema_definition?.properties
                            ? Object.entries(cat.schema_definition.properties).find(
                                ([, p]) => p.is_title
                            )?.[0]
                            : undefined;
                        if (titleField && exEntries[exIdx][titleField] !== undefined) {
                            const titleVal = exEntries[exIdx][titleField];
                            // Resolve translation key if applicable
                            if (typeof titleVal === 'string' && titleVal.includes('.') && !titleVal.includes(' ') && !titleVal.startsWith('http')) {
                                const resolved = $text(titleVal);
                                entryTitle = resolved !== titleVal ? resolved : String(titleVal);
                            } else {
                                entryTitle = String(titleVal);
                            }
                        }
                    } else if (exKeys[exIdx]) {
                        // Fallback to legacy title-only key
                        entryTitle = $text(exKeys[exIdx]);
                    }
                    // Examples use category-level mention (no real entry ID to reference)
                    mentionSyntax = `@memory:${appId}:${itemId}:${cat.type}`;
                } else {
                    // Real entry: look up title from the store (already decrypted in entriesByApp).
                    // appSettingsMemoriesStore state is a plain Svelte store — read via $appSettingsMemoriesStore.
                    const storeState = $appSettingsMemoriesStore;
                    const appEntriesByGroup = storeState.entriesByApp.get(appId) || {};
                    const categoryEntries = appEntriesByGroup[itemId] ?? [];
                    const found = categoryEntries.find((e: { id: string }) => e.id === entryId);
                    if (found) {
                        // Find is_title field to display as entry title
                        const titleField = cat.schema_definition?.properties
                            ? Object.entries(cat.schema_definition.properties).find(
                                ([, p]) => p.is_title
                            )?.[0]
                            : undefined;
                        const entryValue = (found as { item_value?: Record<string, unknown> }).item_value;
                        if (titleField && entryValue?.[titleField]) {
                            entryTitle = String(entryValue[titleField]);
                        } else if (entryValue) {
                            // Fallback: use first non-internal string value
                            for (const [key, value] of Object.entries(entryValue)) {
                                if (!key.startsWith('_') && key !== 'settings_group' && typeof value === 'string' && value.trim()) {
                                    entryTitle = value;
                                    break;
                                }
                            }
                        }
                    }
                    // Real entry uses @memory-entry mention for direct reference
                    mentionSyntax = `@memory-entry:${appId}:${itemId}:${entryId}`;
                }
                
                return {
                    appId,
                    itemName: entryTitle,
                    // Line 2 in header = category name (e.g. "Trips"), not "Settings & Memories Entry"
                    itemTypeLabel: categoryName,
                    description: cat.description_translation_key
                        ? $text(cat.description_translation_key)
                        : '',
                    iconName,
                    iconType: 'memory',
                    mentionSyntax,
                };
            }
            
            // Default: category list page
            return {
                appId,
                itemName: categoryName,
                itemTypeLabel: $text('settings.app_store.settings_memories'),
                description: cat.description_translation_key
                    ? $text(cat.description_translation_key)
                    : '',
                iconName,
                iconType: 'memory',
                mentionSyntax: `@memory:${appId}:${itemId}:${cat.type}`,
            };
        }

        return null;
    });

    /**
     * The app ID for the current top-level app page, e.g. "audio".
     * Also used for sub-pages when subPageBannerData is active.
     */
    let currentAppId = $derived(
        isAppTopLevelPage ? activeSettingsView.replace('app_store/', '') :
        isAppSubPage ? (subPageBannerData?.appId ?? '') :
        ''
    );

    /** AppMetadata for the current top-level or sub-page, used by AppDetailsHeader */
    let currentAppMetadata = $derived(
        currentAppId ? appSkillsStore.getState().apps[currentAppId] : undefined
    );

    /**
     * Current scroll position of .settings-content-wrapper.
     * Updated on scroll events and passed to AppDetailsHeader for the collapse animation.
     */
    let contentScrollTop = $state(0);

    /** Reset scroll tracking on every navigation (the banner components start expanded).
     *  We reset whenever the active view changes (banner or not). */
    $effect(() => {
        // Access activeSettingsView to trigger the effect on navigation changes.
        // eslint-disable-next-line @typescript-eslint/no-unused-expressions
        activeSettingsView;
        contentScrollTop = 0;
    });

    function handleContentScroll(e: Event) {
        // Track scroll for all banner pages: app store pages, standard sub-pages, and main
        if (isAnyBannerPage || activeSettingsView === 'main') {
            contentScrollTop = (e.target as HTMLElement).scrollTop;
        }
    }

    /**
     * Insert the current sub-page mention (skill/focus/memory category) into MessageInput
     * and close settings so the user can continue typing immediately.
     */
    function handleSubPageBannerMentionClick() {
        const mentionSyntax = subPageBannerData?.mentionSyntax;
        if (!mentionSyntax) return;
        pendingMentionStore.set(mentionSyntax);
        panelState.closeSettings();
    }

    /** Decorative header icon opacity: fade out on scroll and on menu close. */
    let headerDecorScrollOpacity = $derived(Math.max(0, 1 - contentScrollTop / 40));
    let headerDecorMenuOpacity = $derived(isMenuVisible ? 1 : 0);
    let headerDecorOpacity = $derived(headerDecorScrollOpacity * headerDecorMenuOpacity);

    // Add reference for content height calculation
    let menuItemsCount = $state(0);

    // Function to set active settings view with transitions
    async function handleOpenSettings(event: { detail: { settingsPath: string; direction: string; icon: string; title: string; cameFrom?: string; cameFromTitle?: string } } | CustomEvent<{ settingsPath: string; direction: string; icon: string; title: string; cameFrom?: string; cameFromTitle?: string }>) {
        const detail = 'detail' in event ? event.detail : event;
        let { settingsPath, direction: newDirection, icon, cameFrom, cameFromTitle } = detail;
        direction = newDirection;

        // --- AI app redirect ---
        // The AI app no longer has its own page in the app store. Intercept any navigation
        // to app_store/ai (from sub-components like AppSettingsMemoriesCategory.goBack())
        // and redirect to the top-level AI settings page.
        if (settingsPath === 'app_store/ai') {
            settingsPath = 'ai';
            icon = 'ai';
        }

        // --- Scroll position memory (All Apps only) ---
        // Save the scroll offset when leaving "All Apps" going forward, so pressing
        // back restores the position. All other pages always scroll to top on navigation.
        if (newDirection === 'forward' && activeSettingsView === 'app_store/all' && settingsContentElement) {
            allAppsScrollPosition = settingsContentElement.scrollTop;
        }
        
        // Track the originating path so back navigation can return to it.
        // Only set when explicitly provided (e.g., navigating from 'app_store/all').
        // When navigating backward through an intermediate app_store page, cameFrom is passed
        // explicitly to preserve the chain, so we accept it from both directions.
        if (cameFrom) {
            cameFromPath = cameFrom;
            if (cameFromTitle !== undefined) {
                cameFromTitleOverride = cameFromTitle;
            }
        } else if (newDirection === 'backward') {
            // Clear cameFromPath when arriving at the destination that was the cameFrom source,
            // or when leaving the app_store section entirely (back to app_store root or main).
            const isReturningToSource = settingsPath === cameFromPath;
            const isLeavingAppStore = settingsPath === 'app_store' || !settingsPath.startsWith('app_store');
            if (isReturningToSource || isLeavingAppStore) {
                cameFromPath = null;
                cameFromTitleOverride = null;
            }
            // Otherwise (e.g., going from skill → app details), cameFromPath is preserved
        } else if (newDirection === 'forward' && !cameFrom) {
            // Forward navigation without explicit cameFrom clears the previous source
            cameFromPath = null;
            cameFromTitleOverride = null;
        }

        // Reset active account ID
        activeAccountId = null;

        // Handle account deletion with account_id
        if (settingsPath.startsWith('account/delete/')) {
            const parts = settingsPath.split('/');
            if (parts.length > 2) {
                activeAccountId = parts[2];
                settingsPath = 'account/delete';
                icon = 'delete';
            }
        }

        // Check if this is a dynamic entry detail route that needs to be registered
        // Pattern: app_store/{app_id}/settings_memories/{category_id}/entry/{entry_id}[/edit]
        const entryDetailPattern = /^app_store\/[^/]+\/settings_memories\/[^/]+\/entry\/[^/]+(\/edit)?$/;
        if (entryDetailPattern.test(settingsPath) && !dynamicEntryRoutes.has(settingsPath)) {
            // Add this entry detail route dynamically
            dynamicEntryRoutes.add(settingsPath);
            // Trigger reactivity by reassigning the Set
            dynamicEntryRoutes = new Set(dynamicEntryRoutes);
            // Dynamically registered entry detail route: settingsPath
        }
        
        // Check if this is a dynamic AI model detail route that needs to be registered
        // Pattern: app_store/{app_id}/skill/{skill_id}/model/{model_id}
        const modelDetailPattern = /^app_store\/[^/]+\/skill\/[^/]+\/model\/[^/]+$/;
        if (modelDetailPattern.test(settingsPath) && !dynamicEntryRoutes.has(settingsPath)) {
            // Add this model detail route dynamically
            dynamicEntryRoutes.add(settingsPath);
            // Trigger reactivity by reassigning the Set
            dynamicEntryRoutes = new Set(dynamicEntryRoutes);
            // Dynamically registered model detail route: settingsPath
        }

        // Check if this is a top-level AI model detail route that needs to be registered
        // Pattern: ai/model/{model_id} (from SettingsAI page)
        const aiModelDetailPattern = /^ai\/model\/[^/]+$/;
        if (aiModelDetailPattern.test(settingsPath) && !dynamicEntryRoutes.has(settingsPath)) {
            dynamicEntryRoutes.add(settingsPath);
            dynamicEntryRoutes = new Set(dynamicEntryRoutes);
        }

        // Check if this is a dynamic reminder entry route that needs to be registered
        // Pattern: app_store/reminder/entry/{reminder_id}[/edit]
        const reminderEntryPattern = /^app_store\/reminder\/entry\/[^/]+(\/edit)?$/;
        if (reminderEntryPattern.test(settingsPath) && !dynamicEntryRoutes.has(settingsPath)) {
            dynamicEntryRoutes.add(settingsPath);
            dynamicEntryRoutes = new Set(dynamicEntryRoutes);
        }

        // Check if this is a dynamic personal data edit route that needs to be registered
        // Pattern: privacy/hide-personal-data/edit-{name|address|birthday|custom}/{entryId}
        const personalDataEditPattern = /^privacy\/hide-personal-data\/edit-(name|address|birthday|custom)\/[^/]+$/;
        if (personalDataEditPattern.test(settingsPath) && !dynamicPersonalDataEditRoutes.has(settingsPath)) {
            dynamicPersonalDataEditRoutes.add(settingsPath);
            dynamicPersonalDataEditRoutes = new Set(dynamicPersonalDataEditRoutes);
        }

        // Set active view for both authenticated and non-authenticated users
        activeSettingsView = settingsPath;
        
        // Handle app detail pages (app_store/{appId}) specially
        // Use the app icon and translated app name from apps.yml
        if (settingsPath.startsWith('app_store/') && settingsPath !== 'app_store' && settingsPath !== 'app_store/all') {
            // Extract appId from path (e.g., "app_store/ai/skill/search" -> "ai")
            const pathParts = settingsPath.replace('app_store/', '').split('/');
            const appId = pathParts[0];
            const app = appSkillsStore.getState().apps[appId];
            
            if (app) {
                // Use app icon from icon_image or appId as fallback
                if (app.icon_image) {
                    // Convert icon_image like "web.svg" to icon name "web"
                    let iconName = app.icon_image.replace(/\.svg$/, '');
                    // Handle special cases for icon name -> app ID mapping
                    // These ensure the correct CSS color variable is used (e.g., --color-app-code, not --color-app-coding)
                    if (iconName === 'email') {
                        iconName = 'mail';
                    } else if (iconName === 'coding') {
                        // coding.svg -> code (app ID is "code", icon file is "coding.svg")
                        iconName = 'code';
                    } else if (iconName === 'heart') {
                        // heart.svg -> health (app ID is "health", icon file is "heart.svg")
                        iconName = 'health';
                    }
                    activeSubMenuIcon = iconName;
                } else {
                    activeSubMenuIcon = appId;
                }
                
                // Reset provider icon state — will be re-set below if this is a model detail page
                activeSubMenuProviderIconSvg = '';
                activeSubMenuTitleRaw = '';
                
                // Check if this is a model detail route (app_store/{appId}/skill/{skillId}/model/{modelId})
                if (pathParts.length === 5 && pathParts[1] === 'skill' && pathParts[3] === 'provider') {
                    // Provider detail route — show provider icon and provider name in header
                    const providerId = pathParts[4];
                    const providerMeta = providersMetadata[providerId];
                    activeSubMenuProviderIconSvg = providerMeta?.logo_svg ?? '';
                    activeSubMenuTitleKey = ''; // No translation key — use raw title (provider name)
                    activeSubMenuTitleRaw = detail.title ?? (providerMeta?.name ?? providerId);
                } else if (pathParts.length === 5 && pathParts[1] === 'skill' && pathParts[3] === 'model') {
                    // Model detail route — show provider icon and model name in header
                    const modelId = pathParts[4];
                    const modelMeta = modelsMetadata.find(m => m.id === modelId);
                    activeSubMenuProviderIconSvg = modelMeta?.logo_svg ?? '';
                    activeSubMenuTitleKey = ''; // No translation key — use raw title (model name)
                    activeSubMenuTitleRaw = detail.title ?? (modelMeta?.name ?? modelId);
                } else if (pathParts.length === 3 && pathParts[1] === 'skill') {
                    // Skill route (app_store/{appId}/skill/{skillId})
                    const skillId = pathParts[2];
                    const skill = app.skills?.find(s => s.id === skillId);
                    if (skill && skill.name_translation_key) {
                        // Use skill name translation key directly (not a placeholder)
                        activeSubMenuTitleKey = skill.name_translation_key;
                    } else {
                        // Fallback to app name if skill not found
                        activeSubMenuTitleKey = `apps.${appId}`;
                    }
                } else if (pathParts.length === 3 && pathParts[1] === 'focus') {
                    // Focus mode route
                    const focusModeId = pathParts[2];
                    const focusMode = app.focus_modes?.find(f => f.id === focusModeId);
                    if (focusMode && focusMode.name_translation_key) {
                        activeSubMenuTitleKey = focusMode.name_translation_key;
                    } else {
                        activeSubMenuTitleKey = `apps.${appId}`;
                    }
                } else if (pathParts.length === 3 && pathParts[1] === 'settings_memories') {
                    // Settings/memories category route
                    const categoryId = pathParts[2];
                    const category = app.settings_and_memories?.find(c => c.id === categoryId);
                    if (category && category.name_translation_key) {
                        activeSubMenuTitleKey = category.name_translation_key;
                    } else {
                        activeSubMenuTitleKey = `apps.${appId}`;
                    }
                } else if (pathParts.length === 4 && pathParts[1] === 'settings_memories' && pathParts[3] === 'create') {
                    // Settings/memories create entry route
                    // Note: category lookup removed as it's not currently used
                    // Use "Add entry" translation for the create page
                    activeSubMenuTitleKey = 'settings.app_settings_memories.add_entry';
                } else if (pathParts.length === 5 && pathParts[1] === 'settings_memories' && pathParts[3] === 'entry') {
                    // Settings/memories entry detail route
                    // The title is passed from the category page, use it directly
                    // The title is already set in the event detail.title
                    activeSubMenuTitleKey = ''; // Will be set from title below
                } else {
                    // Regular app details route
                    activeSubMenuTitleKey = `apps.${appId}`;
                }
            } else {
                // Fallback if app not found
                activeSubMenuIcon = icon || appId;
                activeSubMenuTitleKey = `apps.${appId}`;
            }
        } else if (/^ai\/model\/[^/]+$/.test(settingsPath)) {
            // Top-level AI model detail route: ai/model/{modelId}
            // Show provider icon and model name in header (same as app_store model detail)
            const aiModelId = settingsPath.replace('ai/model/', '');
            const modelMeta = modelsMetadata.find(m => m.id === aiModelId);
            activeSubMenuIcon = 'ai';
            activeSubMenuProviderIconSvg = modelMeta?.logo_svg ?? '';
            activeSubMenuTitleKey = '';
            activeSubMenuTitleRaw = detail.title ?? (modelMeta?.name ?? aiModelId);
        } else if (settingsPath.startsWith('mates/') && settingsPath !== 'mates') {
            // Mate detail route: mates/{mateId}
            // Show the mate's profile image (via mate-profile CSS class) and the mate's name.
            const mateId = settingsPath.replace('mates/', '').split('/')[0];
            const mate = matesMetadata.find(m => m.id === mateId);
            activeSubMenuProviderIconSvg = '';
            activeSubMenuTitleRaw = '';
            // Use mate-profile CSS class approach: icon = mate id so CSS .mate-profile.{id} renders
            activeSubMenuIcon = mateId;
            if (mate?.name_translation_key) {
                activeSubMenuTitleKey = mate.name_translation_key;
            } else {
                activeSubMenuTitleKey = `mates.${mateId}`;
            }
        } else {
            // For other routes, use the provided icon and build translation key from path
            activeSubMenuProviderIconSvg = '';
            activeSubMenuTitleRaw = '';
            activeSubMenuIcon = icon || '';
            // Store the translation key instead of the translated text
            // Special handling for security sub-routes - skip "security" segment in translation key
            if (settingsPath === 'account/security/passkeys') {
                activeSubMenuTitleKey = 'settings.account.passkeys';
            } else if (settingsPath === 'account/security/2fa') {
                // Use security.yml translations for 2FA
                activeSubMenuTitleKey = 'settings.security.tfa_title';
            } else if (settingsPath === 'account/security/password') {
                // Use account.yml translations for password
                activeSubMenuTitleKey = 'settings.account.password';
            } else if (settingsPath === 'account/security/recovery-key') {
                // Use security.yml translations for recovery key
                activeSubMenuTitleKey = 'settings.security.recovery_key_title';
            } else if (settingsPath === 'shared/share') {
                // Special case: 'shared/share' uses 'settings.share' (share is at root level, not nested)
                activeSubMenuTitleKey = 'settings.share';
            } else if (settingsPath === 'server/software-update') {
                // Software update page — use the existing root-level key (not settings.server.software_update)
                activeSubMenuTitleKey = 'settings.software_updates';
            } else if (settingsPath.startsWith('account/storage/')) {
                // Storage category sub-pages: account/storage/<category>
                // Use the storage category label keys (e.g. storage_category_images)
                // instead of the auto-generated settings.account.storage.<category> key which doesn't exist.
                const storageCategoryKeyMap: Record<string, string> = {
                    images:   'settings.storage.storage_category_images',
                    videos:   'settings.storage.storage_category_videos',
                    audio:    'settings.storage.storage_category_audio',
                    pdf:      'settings.storage.storage_category_pdf',
                    code:     'settings.storage.storage_category_code',
                    docs:     'settings.storage.storage_category_docs',
                    sheets:   'settings.storage.storage_category_sheets',
                    archives: 'settings.storage.storage_category_archives',
                    other:    'settings.storage.storage_category_other',
                };
                const storageCategory = settingsPath.split('/').pop() ?? '';
                activeSubMenuTitleKey = storageCategoryKeyMap[storageCategory] ?? 'settings.storage.storage_category_other';
            } else {
                // Build the translation key from the path
                const translationKeyParts = settingsPath.split('/').map(segment => segment.replace(/-/g, '_'));
                activeSubMenuTitleKey = `settings.${translationKeyParts.join('.')}`;
            }
        }

        // Split the view path for breadcrumb navigation
        if (settingsPath !== 'main') {
            navigationPath = settingsPath.split('/');
            updateBreadcrumbLabel();
        } else {
            navigationPath = [];
            breadcrumbLabel = $text('common.settings');
        }

        // Reset submenu info visibility
        showSubmenuInfo = false;
        navButtonLeft = false;

            // Update help link based on the active settings view (commented out - help button disabled)
        if (settingsPath !== 'main') {
            // Handle nested paths in help links (replace / with -)
            // const helpPath = settingsPath.replace('/', '-');
            // currentHelpLink = `${baseHelpLink}/${helpPath}`;
            navButtonLeft = true;

            // Show left navigation and submenu info immediately for smooth transition
            showSubmenuInfo = true;
        }
        
        if (profileContainer) {
            profileContainer.classList.add('submenu-active');
        }
        
        // Wait for the DOM to update with the new page content before scrolling.
        await tick();
        if (settingsContentElement) {
            if (newDirection === 'backward' && settingsPath === 'app_store/all' && allAppsScrollPosition > 0) {
                // Restore the All Apps scroll position so the user lands back where they were.
                // Instant scroll (no animation) feels like returning, not jumping.
                settingsContentElement.scrollTo({
                    top: allAppsScrollPosition,
                    behavior: 'instant'
                });
                allAppsScrollPosition = 0;
            } else {
                // All other navigation (forward or backward) always scrolls to top.
                settingsContentElement.scrollTo({
                    top: 0,
                    behavior: 'instant'
                });
            }
        }
    }

    // Enhanced back navigation - handle both main and nested views
    async function backToMainView(event?: MouseEvent) {
        // Prevent event bubbling to avoid closing the menu
        if (event) {
            event.stopPropagation();
        }
        
        if (navigationPath.length > 1) {
            // Check if we're on a nested app_store route (skill, focus, settings_memories)
            // If so, go back to the app details page (app_store/{appId}) instead of just removing the last segment
            const currentPath = navigationPath.join('/');
            
            // Special handling for non-authenticated users on 'shared/share' - go directly to main
            if (!$authStore.isAuthenticated && currentPath === 'shared/share') {
                direction = 'backward';
                activeSettingsView = 'main';
                showSubmenuInfo = false;
                navButtonLeft = false;
                navigationPath = [];
                breadcrumbLabel = $text('common.settings');
                // currentHelpLink = baseHelpLink; // Help button disabled
                
                if (profileContainer) {
                    profileContainer.classList.remove('submenu-active');
                }
                
                // Wait for DOM to update, then scroll to top
                await tick();
                if (settingsContentElement) {
                    settingsContentElement.scrollTop = 0;
                }
                return;
            }
            
            let previousPath = '';
            let previousPathSegments = [];
            
            if (currentPath.startsWith('app_store/') && currentPath !== 'app_store' && currentPath !== 'app_store/all') {
                const pathParts = currentPath.replace('app_store/', '').split('/');
                const appId = pathParts[0];
                
                // Check if this is an entry detail route - go back to category page
                if (pathParts.length === 5 && pathParts[1] === 'settings_memories' && pathParts[3] === 'entry') {
                    // This is the entry detail route - go back to the category page
                    previousPath = `app_store/${appId}/settings_memories/${pathParts[2]}`;
                    previousPathSegments = ['app_store', appId, 'settings_memories', pathParts[2]];
                } else if (pathParts.length === 5 && pathParts[1] === 'skill' && pathParts[3] === 'model') {
                    // Model detail route - go back to the skill settings page
                    previousPath = `app_store/${appId}/skill/${pathParts[2]}`;
                    previousPathSegments = ['app_store', appId, 'skill', pathParts[2]];
                } else if (pathParts.length === 4 && pathParts[1] === 'settings_memories' && pathParts[3] === 'create') {
                    // This is the create entry route - go back to the category page
                    previousPath = `app_store/${appId}/settings_memories/${pathParts[2]}`;
                    previousPathSegments = ['app_store', appId, 'settings_memories', pathParts[2]];
                } else if (pathParts.length >= 3 && (pathParts[1] === 'skill' || pathParts[1] === 'focus' || pathParts[1] === 'settings_memories')) {
                    // This is a nested route (category page, skill, focus).
                    // If the user arrived here from the Settings & Memories hub, go back there.
                    // Otherwise go back to the app details page.
                    if (pathParts[1] === 'settings_memories' && cameFromPath === 'settings_memories') {
                        previousPath = 'settings_memories';
                        previousPathSegments = ['settings_memories'];
                    } else if (cameFromPath === 'ai') {
                        // Arrived from top-level AI settings — go back there, not to app_store/ai
                        previousPath = 'ai';
                        previousPathSegments = ['ai'];
                    } else {
                        previousPath = `app_store/${appId}`;
                        previousPathSegments = ['app_store', appId];
                    }
                } else {
                    // Regular app details page — if we arrived from "All Apps", go back there.
                    // Otherwise, go back one level normally (to app_store root).
                    if (cameFromPath === 'app_store/all') {
                        previousPath = 'app_store/all';
                        previousPathSegments = ['app_store', 'all'];
                    } else {
                        previousPath = navigationPath.slice(0, -1).join('/');
                        previousPathSegments = navigationPath.slice(0, -1);
                    }
                }
            } else if (navigationPath.join('/') === 'incognito/info') {
                // 'incognito/info' is the only incognito route — there is no bare 'incognito' route.
                // Pressing back should return to the main settings page, not try to navigate to
                // a non-existent 'incognito' route.
                direction = 'backward';
                activeSettingsView = 'main';
                showSubmenuInfo = false;
                navButtonLeft = false;
                navigationPath = [];
                breadcrumbLabel = $text('common.settings');
                if (profileContainer) {
                    profileContainer.classList.remove('submenu-active');
                }
                await tick();
                if (settingsContentElement) {
                    settingsContentElement.scrollTop = 0;
                }
                return;
            } else {
                // For non-app_store routes, go back one level normally
                previousPath = navigationPath.slice(0, -1).join('/');
                previousPathSegments = navigationPath.slice(0, -1);
            }
            
            // Build the correct icon and title for the previous view
            // For nested paths, use the last segment as the icon (e.g., "security" for "account/security")
            // For top-level paths, use the first segment
            let icon = previousPathSegments.length > 1 
                ? previousPathSegments[previousPathSegments.length - 1] 
                : previousPathSegments[0];
            let title = '';

            // Handle app_store routes specially
            if (previousPath.startsWith('app_store/') && previousPath !== 'app_store' && previousPath !== 'app_store/all') {
                const pathParts = previousPath.replace('app_store/', '').split('/');
                const appId = pathParts[0];
                const app = appSkillsStore.getState().apps[appId];
                
                if (app) {
                    // Use app icon from icon_image or appId as fallback
                    if (app.icon_image) {
                        let iconName = app.icon_image.replace(/\.svg$/, '');
                        // Handle special cases for icon name -> app ID mapping
                        // These ensure the correct CSS color variable is used (e.g., --color-app-code, not --color-app-coding)
                        if (iconName === 'email') {
                            iconName = 'mail';
                        } else if (iconName === 'coding') {
                            // coding.svg -> code (app ID is "code", icon file is "coding.svg")
                            iconName = 'code';
                        } else if (iconName === 'heart') {
                            // heart.svg -> health (app ID is "health", icon file is "heart.svg")
                            iconName = 'health';
                        }
                        icon = iconName;
                    } else {
                        icon = appId;
                    }
                    
                    // Check if this is a nested route to get the correct title
                    if (pathParts.length === 3 && pathParts[1] === 'skill') {
                        // Settings memories category route - use category name
                        const skillId = pathParts[2];
                        const skill = app.skills?.find(s => s.id === skillId);
                        if (skill && skill.name_translation_key) {
                            title = $text(skill.name_translation_key);
                        } else {
                            title = app.name_translation_key ? $text(app.name_translation_key) : appId;
                        }
                    } else if (pathParts.length === 3 && pathParts[1] === 'focus') {
                        // Focus mode route - use focus mode name
                        const focusModeId = pathParts[2];
                        const focusMode = app.focus_modes?.find(f => f.id === focusModeId);
                        if (focusMode && focusMode.name_translation_key) {
                            title = $text(focusMode.name_translation_key);
                        } else {
                            title = app.name_translation_key ? $text(app.name_translation_key) : appId;
                        }
                    } else if (pathParts.length === 3 && pathParts[1] === 'settings_memories') {
                        // Settings memories category route - use category name
                        const categoryId = pathParts[2];
                        const category = app.settings_and_memories?.find(c => c.id === categoryId);
                        if (category && category.name_translation_key) {
                            title = $text(category.name_translation_key);
                        } else {
                            title = app.name_translation_key ? $text(app.name_translation_key) : appId;
                        }
                    } else {
                        // Regular app details route - use app name
                        title = app.name_translation_key ? $text(app.name_translation_key) : appId;
                    }
                } else {
                    icon = appId;
                    title = $text(`apps.${appId}`);
                }
            } else {
                // For nested billing paths, determine the correct icon
                if (previousPath === 'billing/buy-credits') {
                    icon = 'coins';
                } else if (previousPath === 'billing/auto-topup') {
                    icon = 'reload';
                } else if (previousPath === 'billing/auto-topup/low-balance') {
                    icon = 'reload';
                } else if (previousPath === 'billing/auto-topup/monthly') {
                    icon = 'calendar';
                } else if (previousPath === 'billing/gift-cards') {
                    icon = 'icon_gift';
                } else if (previousPath === 'billing/gift-cards/buy') {
                    icon = 'icon_gift';
                } else if (previousPath === 'app_store') {
                    icon = 'app_store';
                } else if (previousPath === 'app_store/all') {
                    // "All Apps" view — use the app icon and the "Show all apps" translation
                    icon = 'app';
                    title = $text('settings.app_store.show_all_apps');
                }
                // For other nested paths (like account/security), icon is already set to last segment above
                
                if (!title) {
                    // Build the translation key for the previous view's title
                    const translationKeyParts = previousPathSegments.map(segment => segment.replace(/-/g, '_'));
                    const titleKey = `settings.${translationKeyParts.join('.')}`;
                    const translatedTitle = $text(titleKey);
                    title = translatedTitle;
                }
            }
            
            direction = 'backward';
            handleOpenSettings(new CustomEvent('openSettings', {
                detail: {
                    settingsPath: previousPath,
                    direction: 'backward',
                    icon: icon,
                    title: title,
                    // Preserve cameFromPath (and title) when going backward to an intermediate app page
                    // so the breadcrumb and next back step still reference the original source.
                    cameFrom: (previousPath.startsWith('app_store/') && previousPath !== 'app_store/all' && cameFromPath)
                        ? cameFromPath
                        : undefined,
                    cameFromTitle: (previousPath.startsWith('app_store/') && previousPath !== 'app_store/all' && cameFromTitleOverride)
                        ? cameFromTitleOverride
                        : undefined
                }
            }));
        } else {
            // If we're at the first level, go back to main
            direction = 'backward';
            activeSettingsView = 'main';
            showSubmenuInfo = false;
            navButtonLeft = false;
            navigationPath = [];
            breadcrumbLabel = $text('common.settings');
            
            if (profileContainer) {
                profileContainer.classList.remove('submenu-active');
            }
            
            // Wait for the DOM to update with the main view content before scrolling.
            await tick();
            if (settingsContentElement) {
                settingsContentElement.scrollTo({ top: 0, behavior: 'instant' });
            }
        }
    }

    // No more docking/undocking - we use two separate containers instead
   
    // Handler for profile click to show menu
    function toggleMenu() {
        isMenuVisible = !isMenuVisible;
        settingsMenuVisible.set(isMenuVisible);
        
        // CRITICAL: Sync with panelState to prevent conflicts
        // When user explicitly toggles menu, update panelState accordingly
        if (isMenuVisible) {
            panelState.openSettings();
        } else {
            panelState.closeSettings();
        }

        // If menu is being closed, reset scroll position and view state
        if (!isMenuVisible && settingsContentElement) {
        	
        	// CRITICAL: Remove mobile-overlay class when closing the menu.
        	// This class sets z-index: 1006 which is ABOVE the profile-container-wrapper (1005).
        	// If left on after close, the invisible settings menu intercepts taps on the
        	// profile button on iOS (where pointer events respect stacking order even for
        	// visibility:hidden elements). This is the root cause of the iOS settings tap bug.
        	const menuElement = document.querySelector('.settings-menu');
        	if (menuElement) {
        		menuElement.classList.remove('mobile-overlay');
        	}

        	// Reset the active view to main when closing the menu
        	activeSettingsView = 'main';
        	navigationPath = [];
        	breadcrumbLabel = $text('common.settings');
        	showSubmenuInfo = false;
        	navButtonLeft = false;
        	hideNavButton = false; // Reset hide nav button flag

        	// Reset help link to base
        	// currentHelpLink = baseHelpLink; // Help button disabled

        	// Remove submenu-active class from profile container
        	if (profileContainer) {
        		profileContainer.classList.remove('submenu-active');
        	}

        	// Reset scroll position and clear the All Apps scroll memory so a
        	// stale position doesn't persist into the next time the menu is opened.
        	allAppsScrollPosition = 0;
        	setTimeout(() => {
        		settingsContentElement.scrollTop = 0;
        	}, 300);
        }
    }

    // Handler for quicksettings menu item clicks
    function handleQuickSettingClick(event: CustomEvent<{ toggleName: string }>) {
        const { toggleName } = event.detail;
        
        switch(toggleName) {
            case 'team':
                isTeamEnabled = !isTeamEnabled;
                teamEnabled.set(isTeamEnabled);
                break;
            case 'incognito':
                // No-op: CurrentSettingsPage.svelte manages incognito state directly.
                // When disabling: it calls incognitoMode.set(false) before dispatching this event.
                // When enabling: it navigates to the info screen; SettingsIncognitoInfo.svelte
                // calls incognitoMode.set(true) on confirmation.
                // Calling incognitoMode.toggle() here would double-toggle and immediately
                // reverse the state that CurrentSettingsPage just set.
                break;
            case 'guest':
                isGuestEnabled = !isGuestEnabled;
                break;
            case 'offline':
                isOfflineEnabled = !isOfflineEnabled;
                break;
        }
    }

    // Handle window resize - update viewportWidth for reactive dimmed class logic
    // Settings menu becomes overlay at 1100px, so we track viewport width
    function updateMobileState() {
        if (typeof window !== 'undefined') {
            viewportWidth = window.innerWidth;
        }
    }

    // Click outside handler
    function handleClickOutside(event: MouseEvent) {
	    // Close on outside-click only when settings is rendered as an overlay.
	    // In side-by-side mode (>1100px), outside clicks should not close the panel.
	    const isOverlayMode = viewportWidth <= 1100;
	    if (!isMenuVisible || !isOverlayMode) {
	    	return;
	    }

	    // CRITICAL: Skip closing if settings was just opened programmatically (e.g., from AppStoreCard click).
	    // The same tap/click event can bubble to document and would otherwise immediately close the panel.
	    if (Date.now() - lastProgrammaticOpenTime < 300) {
	    	return;
	    }

	    const settingsMenu = document.querySelector('.settings-menu');
	    const profileWrapper = document.querySelector('.profile-container-wrapper');
	    const closeButton = document.querySelector('.close-icon-container');

	    const isClickInsideMenu = settingsMenu && settingsMenu.contains(event.target as Node);
	    const isClickInsideProfile = profileWrapper && profileWrapper.contains(event.target as Node);
	    const isClickInsideCloseButton = closeButton && closeButton.contains(event.target as Node);

	    // Mirror close button behavior so the same close/reset animation path is used.
	    if (!isClickInsideMenu && !isClickInsideProfile && !isClickInsideCloseButton) {
	    	toggleMenu();
	    }
    }

    // Setup listeners
    onMount(() => {
        // Check server status to determine if payment is enabled (async, fire and forget)
        (async () => {
            try {
                const { getApiEndpoint } = await import('../config/api');
                const response = await fetch(getApiEndpoint('/v1/settings/server-status'));
                if (response.ok) {
                    const status = await response.json();
                    // Use is_self_hosted from request-based validation (more accurate than paymentEnabled)
                    // This correctly identifies localhost and other self-hosted instances
                    isSelfHosted = status.is_self_hosted || false;
                    // CRITICAL: If self-hosted, payment is ALWAYS disabled
                    // This overrides any environment-based logic that might enable payment for localhost in dev mode
                    if (isSelfHosted) {
                        paymentEnabled = false;
                    } else {
                        paymentEnabled = status.payment_enabled || false;
                    }
                    // Use server_edition from request-based validation (includes "development" for dev subdomains)
                    // server_edition can be: "production" | "development" | "self_hosted"
                    _serverEdition = status.server_edition || null;
                    // Payment settings loaded: paymentEnabled, serverEdition, isSelfHosted
                } else {
                    console.warn('[Settings] Failed to fetch server status, defaulting to payment enabled');
                    paymentEnabled = true; // Default to enabled if check fails
                }
            } catch (error) {
                console.error('[Settings] Error checking server status:', error);
                paymentEnabled = true; // Default to enabled if check fails
            }
        })();
        updateMobileState();
        window.addEventListener('resize', handleResize);
        document.addEventListener('click', handleClickOutside);

        // Listen for programmatic close requests from child components
        // (e.g., SettingsIncognitoInfo calls this after activating incognito mode).
        // This is more reliable than setting stores because it calls toggleMenu()
        // directly, which properly syncs all three visibility sources
        // (isMenuVisible, settingsMenuVisible store, panelState).
        const handleCloseSettingsMenu = () => {
            if (isMenuVisible) {
                toggleMenu();
            }
        };
        window.addEventListener('closeSettingsMenu', handleCloseSettingsMenu);

        // Listen for forced close during forced logout (e.g., missing master key).
        // Unlike closeSettingsMenu (toggle), this unconditionally closes AND resets
        // the view to 'main' so the user never lands on an auth-only sub-page.
        const handleForceCloseSettings = () => {
            if (isMenuVisible) {
                // Close and sync all visibility sources
                isMenuVisible = false;
                settingsMenuVisible.set(false);
                panelState.closeSettings();

                // Reset to main settings page — mirrors toggleMenu() close logic
                activeSettingsView = 'main';
                navigationPath = [];
                breadcrumbLabel = $text('common.settings');
                showSubmenuInfo = false;
                navButtonLeft = false;
                hideNavButton = false;
                allAppsScrollPosition = 0;

                if (profileContainer) {
                    profileContainer.classList.remove('submenu-active');
                }
                const menuElement = document.querySelector('.settings-menu');
                if (menuElement) {
                    menuElement.classList.remove('mobile-overlay');
                }
                if (settingsContentElement) {
                    settingsContentElement.scrollTop = 0;
                }
                // Force-closed settings and reset to main page (forced logout)
            }
        };
        window.addEventListener('forceCloseSettings', handleForceCloseSettings);

        // Listen for requests to re-open the settings panel — dispatched by SettingsReportIssue
        // after the DOM element picker captures or cancels. Symmetric to closeSettingsMenu.
        // If the event carries a returnTo path (e.g. 'report_issue'), navigate there after
        // opening because toggleMenu() resets activeSettingsView to 'main' when closing.
        const handleOpenSettingsMenu = (e: Event) => {
            const returnTo = (e as CustomEvent<{ returnTo?: string }>).detail?.returnTo;
            if (!isMenuVisible) {
                toggleMenu();
            }
            // Navigate to the requested sub-page after the panel opens.
            // Use a short delay to let the panel visibility change settle before navigating.
            if (returnTo && returnTo !== 'main') {
                setTimeout(() => {
                    handleOpenSettings(new CustomEvent('openSettings', {
                        detail: {
                            settingsPath: returnTo,
                            direction: 'forward',
                            icon: returnTo,
                            title: ''
                        }
                    }));
                }, 50);
            }
        };
        window.addEventListener('openSettingsMenu', handleOpenSettingsMenu);
        
        // Add listener for language changes
        languageChangeHandler = () => {
            // Update breadcrumbs when language changes
            updateBreadcrumbLabel();
        };
        window.addEventListener('language-changed', languageChangeHandler);

        const handleLocalChatListChanged = () => {
            if (isMenuVisible) {
                scheduleHeaderChatDecorIconRefresh();
            }
        };
        window.addEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleLocalChatListChanged);

        // Prime decorative icons on mount to avoid empty first paint.
        scheduleHeaderChatDecorIconRefresh();

        const handleCreditUpdate = (payload: { credits: number }) => {
            const newCredits = payload.credits;
            if (typeof newCredits === 'number') {
                updateProfile({ credits: newCredits });
            }
        };

        // Listen for admin status updates via WebSocket
        // This handles cases where admin privileges are granted/revoked while user is on settings page
        const handleAdminStatusUpdate = (payload: { is_admin: boolean }) => {
            // Received user_admin_status_updated notification via WebSocket
            if (typeof payload.is_admin === 'boolean') {
                updateProfile({ is_admin: payload.is_admin });
                // Updated user profile admin status
            }
        };

        // Listen for payment completion notifications via WebSocket
        // This handles cases where payment completes after user has moved on from payment screen
        // NOTE: Only register payment handlers if NOT in signup mode, as Payment.svelte already handles them during signup
        // This prevents duplicate handler registrations during signup flow
        const handlePaymentCompleted = (payload: { order_id: string, credits_purchased: number, current_credits: number }) => {
            // Received payment_completed notification via WebSocket
            
            // CRITICAL: Suppress notifications during signup - Payment.svelte already handles them
            // Also suppress when user is on the buy-credits payment/confirmation flow,
            // because SettingsBuyCreditsPayment.svelte handles the WebSocket event directly
            // and navigates to the confirmation screen (showing duplicate toasts is confusing).
            const isOnBuyCreditsPath = activeSettingsView.startsWith('billing/buy-credits');
            if (!$isInSignupProcess && !isOnBuyCreditsPath) {
                // Show success notification popup (using Notification.svelte component)
                notificationStore.success(
                    `Payment completed! ${payload.credits_purchased.toLocaleString()} credits have been added to your account.`,
                    5000
                );
            } else {
                // Suppressing payment_completed notification during signup or buy credits flow
            }
            
            // Always update credits in user profile if available (even during signup)
            if (payload.current_credits !== undefined) {
                updateProfile({ credits: payload.current_credits });
            }
        };

        // Listen for payment failure notifications via WebSocket
        // This handles cases where payment fails minutes after user has moved on from payment screen
        const handlePaymentFailed = (payload: { order_id: string, message: string }) => {
            // Received payment_failed notification via WebSocket
            // Show error notification popup (using Notification.svelte component)
            notificationStore.error(
                payload.message || 'Payment failed. Please try again or use a different payment method.',
                10000 // Show for 10 seconds since this is important
            );
        };

        webSocketService.on('user_credits_updated', handleCreditUpdate);
        webSocketService.on('user_admin_status_updated', handleAdminStatusUpdate);
        
        // Only register payment handlers if NOT in signup mode
        // During signup, Payment.svelte component already handles these events
        // This prevents duplicate handler registrations that cause warnings
        // Store the signup state at registration time for proper cleanup
        const wasInSignupProcess = $isInSignupProcess;
        if (!wasInSignupProcess) {
            webSocketService.on('payment_completed', handlePaymentCompleted);
            webSocketService.on('payment_failed', handlePaymentFailed);
        }
        
        return () => {
            window.removeEventListener('resize', handleResize);
            document.removeEventListener('click', handleClickOutside);
            window.removeEventListener('closeSettingsMenu', handleCloseSettingsMenu);
            window.removeEventListener('forceCloseSettings', handleForceCloseSettings);
            window.removeEventListener('openSettingsMenu', handleOpenSettingsMenu);
            window.removeEventListener('language-changed', languageChangeHandler);
            window.removeEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleLocalChatListChanged);
            if (headerIconRefreshTimer) {
                clearTimeout(headerIconRefreshTimer);
                headerIconRefreshTimer = null;
            }
            webSocketService.off('user_credits_updated', handleCreditUpdate);
            webSocketService.off('user_admin_status_updated', handleAdminStatusUpdate);
            // Only unregister payment handlers if they were registered
            if (!wasInSignupProcess) {
                webSocketService.off('payment_completed', handlePaymentCompleted);
                webSocketService.off('payment_failed', handlePaymentFailed);
            }
        };
    });

    $effect(() => {
        if (isMenuVisible) {
            scheduleHeaderChatDecorIconRefresh();
        }
    });

    // Update DOM elements opacity and classes based on menu state
    // CRITICAL: Settings menu becomes an overlay at 1100px (see CSS @media (max-width: 1100px))
    // We need to dim the background when settings is an overlay, not just on mobile (< 730px)
    // So we check if viewport <= 1100px (overlay mode) rather than just $isMobileView (< 730px)
    // The effect reacts to both isMenuVisible and viewportWidth changes (reactive to resize)
    $effect(() => {
        if (typeof window !== 'undefined') {
            const activeChatContainer = document.querySelector('.active-chat-container');
            if (activeChatContainer) {
                // Check if settings menu is in overlay mode (viewport <= 1100px)
                // This matches the CSS breakpoint where settings becomes an overlay
                // Use reactive viewportWidth so effect re-runs on resize
                const isOverlayMode = viewportWidth <= 1100;
                if (isOverlayMode && isMenuVisible) {
                    activeChatContainer.classList.add('dimmed');
                } else {
                    activeChatContainer.classList.remove('dimmed');
                }
            }
            
            const chatContainer = document.querySelector('.chat-container');
            if (chatContainer) {
                if (isMenuVisible) {
                    chatContainer.classList.add('menu-open');
                } else {
                    chatContainer.classList.remove('menu-open');
                }
            }
        }
    });

    async function handleLogout() {
        try {
            isLoggingOut.set(true);
            isInSignupProcess.set(false);

            await logout({ // Call the imported logout action directly
                // Use the new callback names from LogoutCallbacks
                beforeLocalLogout: () => {
                    // Actions to take before local state is reset (e.g., UI adjustments)
                    isCheckingAuth.set(false); // Keep this if relevant before state reset
                },
                afterLocalLogout: async () => {
                    // Actions after local state is reset but before server cleanup starts
                    // CRITICAL: Clear chats and load demo chat BEFORE database deletion
                    // Dispatch event to clear user chats and load demo chat
                    // Dispatching userLoggingOut event to clear chats and load demo
                    window.dispatchEvent(new CustomEvent('userLoggingOut'));

                     // CRITICAL: Force ActiveChat to load demo-for-everyone by setting activeChatStore directly
                     // This ensures demo-for-everyone loads even if event handlers have timing issues
                     // Small delay to ensure auth state changes are processed first
                     // OG image mode (?og=1): skip demo-for-everyone so the welcome screen stays visible
                     const isOgMode = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('og') === '1';
                     if (!isOgMode) {
                         await new Promise(resolve => setTimeout(resolve, 50));
                         const { activeChatStore } = await import('@repo/ui');
                         activeChatStore.setActiveChat('demo-for-everyone');
                         // Directly set activeChatStore to demo-for-everyone during logout

                         // CRITICAL: Ensure URL hash is set to demo-for-everyone
                         if (typeof window !== 'undefined') {
                             window.location.hash = 'chat-id=demo-for-everyone';
                             // Set URL hash to demo-for-everyone during logout
                         }
                     } else {
                         // Skipping demo-for-everyone redirect during logout - og=1 mode
                     }
                    
                    // CRITICAL: Mark phased sync as completed for non-authenticated users
                    // This prevents "Loading chats..." from showing after logout
                    phasedSyncState.markSyncCompleted();
                    // Marked phased sync as completed after logout (non-auth user)
                    
                    // Reset scroll position
                 	if (settingsContentElement) {
                 		settingsContentElement.scrollTop = 0;
                 	}
                 	// Close the settings menu visually
                 	isMenuVisible = false;
                 	settingsMenuVisible.set(false);
                 	// CRITICAL: Also close via panelState to keep state in sync
                 	panelState.closeSettings();
                    // Small delay to allow settings menu to close visually and state to clear
                 	await new Promise(resolve => setTimeout(resolve, 200)); // Slightly longer to ensure state is cleared
                },
                afterServerCleanup: async () => {
                    // Actions after server logout and DB cleanup are complete (runs async)
                    // CRITICAL: Keep chats panel open during logout - don't close it
                    // The panel should remain open to show demo chats after logout
                    // Only close settings menu
                 	isMenuOpen.set(false);

                     // CRITICAL: Ensure URL hash is set to demo-for-everyone after logout
                     // This ensures consistent behavior where logout always redirects to demo-for-everyone
                     // OG image mode (?og=1): skip so the welcome screen stays visible
                     if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('og') !== '1') {
                         window.location.hash = 'chat-id=demo-for-everyone';
                         // Set URL hash to demo-for-everyone after logout
                     }

                    // Small delay to allow sidebar animation if needed
                 	await new Promise(resolve => setTimeout(resolve, 100));
                }
                // onError callback can be added if specific error handling is needed here
            });

            isLoggingOut.set(false);
        } catch (error) {
            console.error('Error during logout:', error);
            // Even on error, ensure we exit signup mode properly
            isInSignupProcess.set(false);
            logout(); // Call the imported logout function directly, likely without callbacks in error case
        }
    }

    // Subscribe to both text and navigation store to handle language updates
    // Note: breadcrumbs functionality removed - can be re-added if needed in the future
    // Breadcrumbs are available via $settingsNavigationStore.breadcrumbs if needed

    // Make breadcrumbLabel reactive to text store changes
    $effect(() => {
        if ($text) {
            updateBreadcrumbLabel();
        }
    });

    // Handle deep link requests from other components
    // NOTE: Non-authenticated users can access app_store and interface settings
    $effect(() => {
        if ($settingsDeepLink) {
            const settingsPath = $settingsDeepLink;
            
            // For non-authenticated users, only allow app_store, interface, share settings, newsletter, support, report_issue, account deletion, and mates
            // Share settings are allowed so users can share demo chats
            // Newsletter is allowed so anyone can subscribe
            // Support is allowed so anyone can sponsor the project
            // Report issue is allowed so anyone can report bugs/issues
            // Account deletion is allowed for uncompleted accounts via email link
            // Mates is allowed so unauthenticated users (e.g. example/public chat) can open mate settings deep links
            if (!$authStore.isAuthenticated) {
                const allowedPaths = ['app_store', 'interface', 'interface/language', 'shared/share', 'newsletter', 'support', 'report_issue', 'account/delete', 'mates'];
                const isAllowedPath = allowedPaths.includes(settingsPath) ||
                                     settingsPath.startsWith('app_store/') ||
                                     settingsPath.startsWith('interface/') ||
                                     settingsPath.startsWith('shared/share') ||
                                     settingsPath.startsWith('support/') ||
                                     settingsPath.startsWith('report_issue/') ||
                                     settingsPath.startsWith('account/delete/') ||
                                     settingsPath.startsWith('mates/');
                
                if (!isAllowedPath) {
                    // Clear the deep link if path is not allowed for non-authenticated users
                    // Clearing deep link - path not allowed for non-authenticated users
                    settingsDeepLink.set(null);
                    return;
                }
            }

            // Reset the deep link store immediately to prevent multiple triggers
            settingsDeepLink.set(null);

            // Scroll to top of the page
            if (typeof window !== 'undefined') {
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }

            // Open the settings menu if it's not already open
            if (!isMenuVisible) {
                isMenuVisible = true;
                settingsMenuVisible.set(true);
                // CRITICAL: Record the programmatic open time so handleClickOutside doesn't
                // immediately close the panel on mobile. On mobile, the tap that triggers a
                // deep link (e.g. badge click) bubbles to document and fires handleClickOutside
                // within milliseconds. The 300ms grace period prevents this race condition.
                lastProgrammaticOpenTime = Date.now();

                // Force z-index update to ensure proper overlay on mobile
                setTimeout(() => {
                    const menuElement = document.querySelector('.settings-menu');
                    if (menuElement && $isMobileView) {
                        menuElement.classList.add('mobile-overlay');
                    }
                }, 50);
            }

            // After a brief delay to ensure menu is open, navigate to the requested settings path
            setTimeout(() => {
                // Strip deep-link parameters (e.g. "&usage") from the path before routing.
                // The parameters remain in window.location.hash for sub-components to read.
                const cleanPath = settingsPath.split('&')[0];

                // Set window flag for deep-link parameters so sub-components can read them
                // after the hash is cleaned. SettingsUsage reads __openmates_usage_deeplink.
                if (settingsPath.includes('&usage')) {
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    (window as any).__openmates_usage_deeplink = true;
                }

                // Determine the icon and title based on the path
                // For nested paths like 'shared/share', use the last segment for icon
                const pathParts = cleanPath.split('/');
                const icon = pathParts.length > 1 ? pathParts[pathParts.length - 1] : pathParts[0];
                
                // Build translation key from full path
                // Special case: 'shared/share' uses 'settings.share' (share is at root level, not nested)
                let translationKey;
                if (cleanPath === 'shared/share') {
                    translationKey = 'settings.share';
            } else if (cleanPath === 'incognito/info') {
                // Incognito info page: use the incognito icon and the top-level "Incognito" title.
                // The path 'incognito/info' would otherwise auto-generate 'settings.incognito.info'
                // which does not exist in translations.
                activeSubMenuIcon = 'incognito';
                activeSubMenuTitleKey = 'settings.incognito';
            } else if (cleanPath.startsWith('account/storage/')) {
                    // Storage category pages use the storage_category_* keys in storage.yml
                    const deepLinkStorageCategoryKeyMap: Record<string, string> = {
                        images:   'settings.storage.storage_category_images',
                        videos:   'settings.storage.storage_category_videos',
                        audio:    'settings.storage.storage_category_audio',
                        pdf:      'settings.storage.storage_category_pdf',
                        code:     'settings.storage.storage_category_code',
                        docs:     'settings.storage.storage_category_docs',
                        sheets:   'settings.storage.storage_category_sheets',
                        archives: 'settings.storage.storage_category_archives',
                        other:    'settings.storage.storage_category_other',
                    };
                    const deepLinkCategory = cleanPath.split('/').pop() ?? '';
                    translationKey = deepLinkStorageCategoryKeyMap[deepLinkCategory] ?? 'settings.storage.storage_category_other';
                } else {
                    const translationKeyParts = cleanPath.split('/').map(segment => segment.replace(/-/g, '_'));
                    translationKey = `settings.${translationKeyParts.join('.')}`;
                }
                const title = $text(translationKey);

                handleOpenSettings(new CustomEvent('openSettings', {
                    detail: {
                        settingsPath: cleanPath,
                        direction: 'forward',
                        icon,
                        title
                    }
                }));
            }, 300);
        }
    });

    // Track previous navigation path to avoid duplicate navigation
    let previousNavigationPath = $state<string | null>(null);
    
    // Watch settingsNavigationStore to handle navigation from nested components
    // This allows components like SettingsDevelopers to navigate to sub-pages
    $effect(() => {
        const currentPath = $settingsNavigationStore.currentPath;
        
        // Only update if the path is different from current view, not 'settings' (main), and actually changed
        if (currentPath && 
            currentPath !== activeSettingsView && 
            currentPath !== 'settings' &&
            currentPath !== previousNavigationPath) {
            
            // Update tracked path to prevent duplicate calls
            previousNavigationPath = currentPath;
            
            // Find the breadcrumb for this path to get icon and title
            const breadcrumb = $settingsNavigationStore.breadcrumbs.find(crumb => crumb.path === currentPath);
            
            if (breadcrumb) {
                // Ensure settings menu is open
                if (!isMenuVisible) {
                    isMenuVisible = true;
                    settingsMenuVisible.set(true);
                }
                
                // Determine direction (forward if going deeper, backward if going back)
                const currentDepth = activeSettingsView ? activeSettingsView.split('/').length : 0;
                const newDepth = currentPath.split('/').length;
                const navDirection = newDepth > currentDepth ? 'forward' : 'backward';
                
                // Get title from breadcrumb or translation
                const title = breadcrumb.translationKey 
                    ? $text(breadcrumb.translationKey)
                    : breadcrumb.title;
                
                handleOpenSettings(new CustomEvent('openSettings', {
                    detail: {
                        settingsPath: currentPath,
                        direction: navDirection,
                        icon: breadcrumb.icon || currentPath.split('/').pop() || '',
                        title: title
                    }
                }));
            }
        }
    });

    // Watch settingsMenuVisible store to handle external close requests
    $effect(() => {
    	// If store value changes from true to false and our local state is still true
    	if (!$settingsMenuVisible && isMenuVisible) {
    		isMenuVisible = false;
   
    		// Remove mobile overlay class when closing
    		const menuElement = document.querySelector('.settings-menu');
    		if (menuElement) {
    			menuElement.classList.remove('mobile-overlay');
    		}

    		// CRITICAL: Reset settings view to main page when externally closed (e.g., forced logout)
    		// This prevents users from landing on an auth-only sub-page next time they open settings.
    		// Mirrors the reset logic in toggleMenu() when the menu is closed.
    		activeSettingsView = 'main';
    		navigationPath = [];
    		breadcrumbLabel = $text('common.settings');
    		showSubmenuInfo = false;
    		navButtonLeft = false;
    		hideNavButton = false;
    		allAppsScrollPosition = 0;

    		if (profileContainer) {
    			profileContainer.classList.remove('submenu-active');
    		}

    		if (settingsContentElement) {
    			settingsContentElement.scrollTop = 0;
    		}
   
    		// Don't call toggleMenu again, just update state
    	} else if ($settingsMenuVisible && !isMenuVisible) {
    		// If store value changes from false to true and our local state is still false
    		isMenuVisible = true;
   
    		// Add mobile overlay class when opening on mobile
    		setTimeout(() => {
    			const menuElement = document.querySelector('.settings-menu');
    			if (menuElement && $isMobileView) {
    				menuElement.classList.add('mobile-overlay');
    			}
    		}, 50);
    	}
    });

    // CRITICAL: Sync isMenuVisible with panelState.isSettingsOpen
    // This ensures that when panelState.openSettings() is called (e.g., from share button),
    // the Settings component's isMenuVisible state is updated correctly
    // This fixes the issue where the menu might not open when share button is clicked
    // NOTE: We only sync FROM panelState TO local state, not the reverse
    // The reverse sync (local -> panelState) is handled by toggleMenu() and other close handlers
    $effect(() => {
    	// If panelState says settings should be open but our local state says closed
    	// This handles external opens (e.g., from share button, AppStoreCard clicks)
    	if ($panelState.isSettingsOpen && !isMenuVisible) {
    		isMenuVisible = true;
    		settingsMenuVisible.set(true); // Also update the store for consistency
    		// Record the programmatic open time so handleClickOutside doesn't immediately close
    		// the panel on mobile (where the same tap event bubbles to document)
    		lastProgrammaticOpenTime = Date.now();

    		// Add mobile overlay class when opening on mobile
    		setTimeout(() => {
    			const menuElement = document.querySelector('.settings-menu');
    			if (menuElement && $isMobileView) {
    				menuElement.classList.add('mobile-overlay');
    			}
    		}, 50);
    	}
    	// NOTE: We don't sync panelState -> local when closing, because:
    	// 1. User-initiated closes (toggleMenu, click outside) already update panelState
    	// 2. External closes via settingsMenuVisible store are handled by the other effect
    	// 3. This prevents conflicts where panelState.closeSettings() would fight with user actions
    });
</script>

{#if showSettingsIcon}
    <div
    	class="profile-container-wrapper"
    	class:signup-footer-mode={$showSignupFooter}
    	in:fly={{ y: -window.innerHeight/2 + 60, x: 0, duration: 800, easing: cubicOut }}
    	out:fade
    >
    <div bind:this={profileContainerWrapper}> <!-- Bind the wrapper -->
    	<div
			id="settings-menu-toggle"
     		class="profile-container"
    		data-testid="profile-container"
    		class:menu-open={isMenuVisible}
    		data-action={isMenuVisible ? 'close-settings' : 'open-settings'}
    		onclick={toggleMenu}
    		onkeydown={e => e.key === 'Enter' && toggleMenu()}
    		role="button"
    		tabindex="0"
    		aria-label={$text('settings.open_settings_menu')}
    		bind:this={profileContainer}
    	>
            <!-- Show language icon when not logged in and menu is closed, user icon when menu is open -->
            <!-- Show profile picture when user is logged in -->
            {#if !$authStore.isAuthenticated}
                <div class="profile-picture language-icon-container">
                    <div class="clickable-icon" class:icon_settings={!isMenuVisible} class:icon_user={isMenuVisible}></div>
                </div>
            {:else}
                <!-- Use resolvedProfileImageBlobUrl (fetched with credentials) so the
                     new encrypted proxy endpoint works. Legacy https:// URLs are also
                     passed through by the profileImageService unchanged. -->
                <div class="profile-picture" data-testid="profile-picture" class:profile-picture-img={!!resolvedProfileImageBlobUrl}>
                    {#if resolvedProfileImageBlobUrl}
                        <img class="profile-picture-avatar" src={resolvedProfileImageBlobUrl} alt="Profile" />
                    {:else}
                        <div class="default-user-icon"></div>
                    {/if}
                </div>
            {/if}
    	</div>
    </div>

        <div class="close-icon-container" class:visible={isMenuVisible}>
            <button
                class="icon-button"
                data-testid="icon-button-close"
                aria-label={$text('settings.close_settings_menu')}
                onclick={toggleMenu}
            >
                <div class="clickable-icon icon_close"></div>
            </button>
        </div>
    </div>
{/if}

<!-- Dummy element to make linter recognize mobile-overlay class as used -->
<div class="settings-menu mobile-overlay" style="display: none;"></div>

<div
    class="settings-menu"
    data-testid="settings-menu"
    class:visible={isMenuVisible}
    class:overlay={isMenuVisible}
    class:mobile={$isMobileView}
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
    role="presentation"
>
    <div
        class="settings-header"
        class:submenu-active={activeSettingsView !== 'main' && showSubmenuInfo && !isAnyBannerPage}
        class:app-top-level={isAnyBannerPage || activeSettingsView === 'main'}
        onclick={(e) => e.stopPropagation()}
        onkeydown={(e) => e.stopPropagation()}
        role="presentation"
    >
        <div class="header-content">
            {#if !hideNavButton}
                <button
					id="settings-back-button"
                    class="nav-button"
                    class:left={navButtonLeft}
                    class:left-aligned={activeSettingsView !== 'main'}
                    onclick={activeSettingsView !== 'main' ? (e) => backToMainView(e) : null}
                    aria-disabled={activeSettingsView === 'main'}
                    bind:this={navButtonElement}
                    use:tooltip
                >
                    <div class="clickable-icon icon_back" class:visible={activeSettingsView !== 'main'}></div>
                    <span>{breadcrumbLabel}</span>
                </button>
            {/if}
            
            <!-- TODO Show help button again once docs are implemented -->
            <!-- <a 
                href={currentHelpLink} 
                target="_blank" 
                use:tooltip
                rel="noopener noreferrer" 
                class="help-button-container" 
                aria-label={$text('documentation.open_documentation')}
            >
                <div class="help-button"></div>
            </a> -->
        </div>
        
        {#if activeSettingsView !== 'main' && showSubmenuInfo && !isAnyBannerPage}
            <div
                class="submenu-info"
                class:reduced-padding={hideNavButton}
                transition:slide={{ duration: 300, easing: cubicOut }}
            >
                {#if isModelDetailPage && activeSubMenuProviderIconSvg}
                    <!-- Model detail page: show provider icon + model name instead of app icon -->
                    <div class="model-detail-header-item">
                        <div class="model-detail-provider-icon">
                            <img
                                src={getProviderIconUrl(activeSubMenuProviderIconSvg)}
                                alt=""
                                class="model-detail-provider-img"
                            />
                        </div>
                        <strong class="model-detail-title">{activeSubMenuTitle}</strong>
                    </div>
                {:else if isMateDetailPage}
                    <!-- Mate detail page: show the mate's circular profile image + name.
                         Uses the same .mate-profile CSS class system as the chat header
                         (mates.css sets background-image per mate id class). -->
                    <div class="mate-detail-header-item">
                        <div class="mate-profile {activeSubMenuIcon} mate-profile-header"></div>
                        <strong class="model-detail-title">{activeSubMenuTitle}</strong>
                    </div>
                {:else}
                    <!-- App store sub-pages render icon SVG with app-specific gradient (no bg square) -->
                    <!-- Focus mode details pages now use the same icon+title header as skills -->
                    <SettingsItem
                        type="heading"
                        icon={activeSubMenuIcon}
                        title={activeSubMenuTitle}
                        iconBackground={isAppStoreSubPage ? 'none' : 'primary'}
                        iconColor={isAppStoreSubPage ? `var(--color-app-${activeSubMenuIcon})` : undefined}
                    />
                {/if}
            </div>
        {/if}
    </div>
    
    <!-- Main settings page gradient banner — shown only on the root settings menu.
         Displays the user's avatar + username and a clickable credits count.
         Placed outside the content-wrapper so sticky positioning works correctly. -->
    {#if activeSettingsView === 'main'}
        <div class="settings-banner-shell">
            {#if headerChatDecorIcons.length > 0}
                <div
                    class="header-chat-icons-layer on-banner"
                    class:menu-open={isMenuVisible}
                    aria-hidden="true"
                    style="opacity: {headerDecorOpacity}"
                >
                    {#each headerChatDecorIcons as decor, index (decor.key)}
                        {@const IconComponent = getLucideIcon(decor.iconName)}
                        <div
                            class="header-chat-icon {decor.side}"
                            style="top: {decor.topPercent}%; --header-chat-icon-inset: {decor.insetPx}px; --header-chat-icon-rotation: {decor.rotationDeg}deg; --deco-rotate: {decor.rotationDeg}deg; --float-rx: 6px; --float-ry: 7px; animation-delay: {-index * 2}s;"
                        >
                            <IconComponent size={22} color="rgba(255, 255, 255, 0.45)" />
                        </div>
                    {/each}
                </div>
            {/if}
            <SettingsMainHeader
                {username}
                profileImageUrl={resolvedProfileImageBlobUrl ?? ''}
                isAuthenticated={$authStore.isAuthenticated}
                credits={$userProfile.credits ?? 0}
                {paymentEnabled}
                scrollTop={contentScrollTop}
                onBillingClick={() => handleOpenSettings({ detail: { settingsPath: 'billing', direction: 'forward', icon: 'billing', title: $text('settings.billing') } } as CustomEvent<{ settingsPath: string; direction: string; icon: string; title: string; cameFrom?: string }>)}
                onAvatarClick={() => handleOpenSettings({ detail: { settingsPath: 'account/profile-picture', direction: 'forward', icon: 'profile-picture', title: $text('settings.account.profile_picture') } } as CustomEvent<{ settingsPath: string; direction: string; icon: string; title: string; cameFrom?: string }>)}
                onUsernameClick={() => handleOpenSettings({ detail: { settingsPath: 'account/username', direction: 'forward', icon: 'username', title: $text('settings.account.username') } } as CustomEvent<{ settingsPath: string; direction: string; icon: string; title: string; cameFrom?: string }>)}
            />
        </div>
    {/if}

    <!-- App details gradient banner — shown on:
         1. app_store/{appId} top-level pages (full description + capability counts)
         2. app_store/{appId}/skill|focus|settings_memories/{itemId} sub-pages
            (same gradient, but shows item name + type label instead of description/counts)
         Placed outside the content-wrapper so it's not clipped by the slider's overflow:hidden.
         sticky positioning works here because this element is a direct flex child of .settings-menu. -->
    {#if isAnyAppBannerPage && currentAppMetadata}
        <div class="settings-banner-shell">
            <AppDetailsHeader
                appId={currentAppId}
                app={currentAppMetadata}
                scrollTop={contentScrollTop}
                breadcrumbLabel={breadcrumbLabel}
                fullBreadcrumbLabel={fullBreadcrumbLabel}
                onBack={() => backToMainView()}
                subItem={subPageBannerData ? {
                    name: subPageBannerData.itemName,
                    typeLabel: subPageBannerData.itemTypeLabel,
                    description: subPageBannerData.description,
                    iconName: subPageBannerData.iconName,
                    iconType: subPageBannerData.iconType,
                } : undefined}
                onSubItemMention={subPageBannerData?.mentionSyntax ? handleSubPageBannerMentionClick : undefined}
            />
        </div>
    {/if}

    <!-- Standard settings sub-page gradient banner — shown on Privacy, Billing, Usage, etc.
         Uses the openmates gradient with the page icon and title.
         Placed outside the content-wrapper for the same sticky-positioning reason. -->
    {#if isStandardSubPage}
        <div class="settings-banner-shell">
            <AppDetailsHeader
                scrollTop={contentScrollTop}
                breadcrumbLabel={breadcrumbLabel}
                fullBreadcrumbLabel={fullBreadcrumbLabel}
                onBack={() => backToMainView()}
                settingsPage={{
                    title: activeSubMenuTitle,
                    icon: activeSubMenuIcon,
                    description: activeSubMenuDescription,
                    stats: appStoreHeaderStats,
                }}
            />
        </div>
    {/if}

    <div
        class="settings-content-wrapper"
        bind:this={settingsContentElement}
        onscroll={handleContentScroll}
        onclick={(e) => e.stopPropagation()}
        onkeydown={(e) => e.stopPropagation()}
        role="presentation"
    >
        <!-- Show settings menu for both authenticated and non-authenticated users -->
        <!-- For non-authenticated users, only language settings are available -->
        <CurrentSettingsPage
        	bind:this={currentPageInstance}
        	{activeSettingsView}
            accountId={activeAccountId}
        	{direction}
        	{username}
            {isInSignupMode}
            {settingsViews}
            {isMenuVisible}
            {paymentEnabled}
            showProfileHeader={false}
            resolvedProfileImageUrl={resolvedProfileImageBlobUrl}
            bind:isIncognitoEnabled
            bind:isGuestEnabled
            bind:isOfflineEnabled
            bind:menuItemsCount
            on:openSettings={handleOpenSettings}
            on:navigateBack={() => backToMainView()}
            on:quickSettingClick={handleQuickSettingClick}
            on:logout={handleLogout}
            on:chatSelected={(e) => {
                // Forward chatSelected event from sub-pages (e.g. SettingsUsage) to +page.svelte
                dispatch('chatSelected', e.detail);
            }}
            on:closeSettings={() => {
                // Close settings when a sub-page (e.g. SettingsUsage) requests it
                isMenuVisible = false;
                settingsMenuVisible.set(false);
                panelState.closeSettings();
            }}
        />

        <!-- Show footer for both authenticated and non-authenticated users -->
        <!-- This displays social links and legal information -->
        <!-- isSelfHosted prop hides legal docs for self-hosted (personal/internal team use doesn't need them) -->
        <SettingsFooter
            {isSelfHosted}
            on:chatSelected={(e) => {
                // Forward chatSelected event to parent (+page.svelte)
                dispatch('chatSelected', e.detail);
            }}
            on:closeSettings={() => {
                // Close settings menu when a legal chat is opened
                isMenuVisible = false;
                settingsMenuVisible.set(false);
                // CRITICAL: Also close via panelState to keep state in sync
                panelState.closeSettings();
            }}
        />
    </div>
</div>

<style>
    .profile-container-wrapper {
        position: fixed;
        top: 8px;
        /* Logical property: avatar pinned to inline-end corner (top-right in LTR, top-left in RTL) */
        inset-inline-end: 10px;
        width: 50px;
        height: 50px;
        z-index: var(--z-index-popover-above);
        transition: opacity var(--duration-slow) var(--easing-default), top var(--duration-slow) var(--easing-default), position var(--duration-slow) var(--easing-default);
    }

    .profile-container-wrapper.signup-footer-mode {
        position: absolute;
        top: 8px;
        /* Use calc to ensure it doesn't extend beyond viewport */
        inset-inline-start: calc(100% - 67px); /* 57px width + 10px margin */
        inset-inline-end: auto;
    }

    .profile-container {
        position: absolute;
        top: 0;
        /* Logical property: anchored to inline-end corner */
        inset-inline-end: 0;
        width: 50px;
        height: 50px;
        border-radius: 50%;
        cursor: pointer;
        /* Fade out when menu opens, fade in when menu closes */
        transition: opacity var(--duration-normal) var(--easing-default);
        opacity: 1;
    }

    .profile-container.menu-open {
        opacity: 0;
        pointer-events: none;
    }
   
    .close-icon-container {
        position: absolute;
        top: 0;
        /* Logical property: anchored to inline-end corner */
        inset-inline-end: 0;
        width: 50px;
        height: 50px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        visibility: hidden;
        transition: all var(--duration-slow) var(--easing-default);
    }

    .close-icon-container.visible {
        opacity: 1;
        visibility: visible;
    }

    .close-icon-container button.icon-button {
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: none;
        border: none;
        padding: 0;
        cursor: pointer;
    }

    .close-icon-container .clickable-icon {
        width: 25px;
        height: 25px;
    }

    .profile-picture {
        border-radius: 50%;
        width: 100%;
        height: 100%;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-color: var(--color-grey-20);
        box-shadow: var(--shadow-xs);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    /* When a profile image blob URL is available, clip <img> to the circle */
    .profile-picture-img {
        overflow: hidden;
    }

    .profile-picture-avatar {
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: 50%;
        display: block;
    }

    .language-icon-container {
        background-color: var(--color-grey-20);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .language-icon-container .clickable-icon {
        width: 25px;
        height: 25px;
        background-color: white;
    }
    
    .default-user-icon {
        width: 32px;
        height: 32px;
        -webkit-mask-image: url('@openmates/ui/static/icons/user.svg');
        -webkit-mask-size: contain;
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-image: url('@openmates/ui/static/icons/user.svg');
        mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
        background-color: var(--color-grey-60);
    }

    .settings-menu {
        background-color: var(--color-grey-20);
        height: 100%;
        width: 0px;
        border-radius: 17px;
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transition: width var(--duration-slow) var(--easing-default);
        z-index: var(--z-index-modal-above);
    }

    @media (max-width: 1100px) {
        .settings-menu {
            position: fixed;
            /* Logical property: panel anchored to inline-end edge (right in LTR, left in RTL) */
            inset-inline-end: 20px;
            top: 65px;
            bottom: 18px;
            height: auto;
            z-index: var(--z-index-modal);
            /* Override desktop width animation — keep full width, slide with GPU-accelerated transform */
            width: 323px;
            transition: transform var(--duration-slow) var(--easing-default), visibility var(--duration-slow) var(--easing-default);
            transform: translateX(calc(100% + 40px));
            visibility: hidden;
            will-change: transform;
        }

        .settings-menu.visible {
            transform: translateX(0);
            visibility: visible;
        }

        :global([dir="rtl"]) .settings-menu:not(.visible) {
            transform: translateX(calc(-100% - 40px));
        }

        .settings-menu.overlay {
            box-shadow: -4px 0 12px rgba(0, 0, 0, 0.15);
        }
        
        /* Add mobile overlay style for higher z-index */
        /* This class is added dynamically via JavaScript - see lines 636, 669, 682 */
        /* svelte-ignore css_unused_selector */
        .settings-menu.mobile-overlay {
            z-index: var(--z-index-popover-above-2) !important; /* Higher than profile-container-wrapper */
        }
    }

    @media (max-width: 730px) {
        .settings-menu {
            inset-inline-end: 10px;
            bottom: 10px;
            transform: translateX(calc(100% + 20px));
        }

        :global([dir="rtl"]) .settings-menu:not(.visible) {
            transform: translateX(calc(-100% - 20px));
        }

        .settings-menu.visible {
            transform: translateX(0);
        }
    }

    .settings-menu.visible {
        width: 323px;
        visibility: visible;
    }

    .settings-header,
    .settings-content-wrapper,
    :global(.app-details-header) {
        opacity: 0;
        transition: opacity var(--duration-slow) var(--easing-default);
    }

    .settings-menu.visible .settings-header,
    .settings-menu.visible .settings-content-wrapper,
    .settings-menu.visible :global(.app-details-header) {
        opacity: 1;
        transition: opacity var(--duration-slow) var(--easing-default);
    }

    .settings-header {
        background-color: var(--color-grey-20);
        padding-bottom: var(--spacing-6);
        position: sticky;
        top: 0;
        z-index: var(--z-index-dropdown-1);
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        display: flex;
        flex-direction: column;
        border-bottom: 1px solid var(--color-grey-30);
        position: relative;
        min-height: 30px;
    }

    .header-chat-icons-layer {
        position: absolute;
        inset: 0;
        overflow: hidden;
        pointer-events: none;
        z-index: var(--z-index-base);
        transition: opacity 0.28s ease;
    }

    .header-chat-icons-layer.on-banner {
        border-radius: 0 0 14px 14px;
    }

    .header-chat-icon {
        position: absolute;
        display: flex;
        align-items: center;
        justify-content: center;
        transform: translateY(-50%) rotate(var(--header-chat-icon-rotation));
        opacity: 0;
        transition: opacity 0.28s ease;
        /* Orbital float — each icon drifts in a small circle. Per-icon phase
           offset set via negative animation-delay in the inline style so all
           8 icons orbit independently (staggered by 2s each). */
        animation: decoFloat 16s linear infinite;
    }

    .header-chat-icons-layer.menu-open .header-chat-icon {
        opacity: 1;
        transition-delay: 0.2s;
    }

    @media (prefers-reduced-motion: reduce) {
        .header-chat-icon { animation: none; }
    }

    .header-chat-icon.left {
        left: var(--header-chat-icon-inset);
    }

    .header-chat-icon.right {
        right: var(--header-chat-icon-inset);
    }

    .header-content {
        width: 100%;
        position: relative;
        z-index: var(--z-index-raised);
        transition: all var(--duration-slow) var(--easing-default);
    }

    .settings-banner-shell {
        position: relative;
        width: 100%;
    }

    .settings-banner-shell :global(.app-details-header) {
        position: relative;
        z-index: var(--z-index-raised);
    }

    .settings-header.submenu-active {
        padding-bottom: var(--spacing-10); /* Space for submenu info */
        transition: padding-bottom var(--duration-slow) var(--easing-default); /* Smooth padding transition */
    }

    /*
     * When the app top-level page is active, the AppDetailsHeader inside the
     * content wrapper takes full ownership of the header area — it contains its
     * own back arrow, breadcrumb, and close button on the gradient.
     *
     * We completely hide the normal .settings-header (collapse to 0 height) so
     * there's no double-header and the gradient banner appears right at the top.
     * We use height + overflow rather than display:none so the opacity transition
     * still works cleanly when switching pages.
     */
    .settings-header.app-top-level {
        height: 0 !important;
        min-height: 0 !important;
        padding: 0 !important;
        border-bottom: none !important;
        box-shadow: none !important;
        overflow: hidden;
        transition: height var(--duration-normal) var(--easing-default), padding var(--duration-normal) var(--easing-default);
    }


    .nav-button {
        all: unset;
        font-size: var(--font-size-small);
        color: var(--color-grey-60);
        cursor: default;
        display: flex;
        align-items: center;
        position: absolute;
        left: 110px;
        top: 10px;
        padding: 4px 0;
        transition: all var(--duration-slow) var(--easing-default);
        pointer-events: none; /* Disable click interactions by default */
        max-width: 290px; /* Set maximum width */
    }
    
    /* Add a span inside button to handle text overflow */
    .nav-button span {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        display: block;
    }

    .nav-button.left {
        cursor: pointer;
        left: 10px;
        pointer-events: all; /* Enable click interactions when in submenu */
    }

    .nav-button[aria-disabled="true"]:hover {
        cursor: default;
    }
    
    .nav-button[aria-disabled="false"]:hover {
        cursor: pointer;
    }

    .submenu-info {
        padding-top: var(--spacing-20);
        margin-bottom: -10px;
        overflow: hidden;
    }
    
    .submenu-info.reduced-padding {
        padding-top: var(--spacing-5);
    }

    /* Model detail header: provider icon + model name */
    .model-detail-header-item {
        display: flex;
        align-items: center;
        gap: var(--spacing-6);
        padding: var(--spacing-2) var(--spacing-8) var(--spacing-2) var(--spacing-6);
    }

    /* Mate detail header: circular profile image + mate name */
    .mate-detail-header-item {
        display: flex;
        align-items: center;
        gap: var(--spacing-6);
        padding: var(--spacing-2) var(--spacing-8) var(--spacing-2) var(--spacing-6);
    }

    /*
     * Size the mate profile image in the settings header.
     * The base .mate-profile class (mates.css) sets 60px — we want 38px here
     * to match the model provider icon size and suppress the AI badge pseudo-elements.
     */
    :global(.mate-profile.mate-profile-header) {
        width: 38px;
        height: 38px;
        flex-shrink: 0;
    }

    :global(.mate-profile.mate-profile-header::before),
    :global(.mate-profile.mate-profile-header::after) {
        display: none;
    }

    .model-detail-provider-icon {
        flex-shrink: 0;
        width: 38px;
        height: 38px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: var(--radius-4);
        background: var(--color-grey-10);
        overflow: hidden;
    }

    .model-detail-provider-img {
        width: 28px;
        height: 28px;
        object-fit: contain;
    }

    .model-detail-title {
        font-size: 1rem;
        font-weight: 600;
        color: var(--color-grey-100);
        line-height: 1.2;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .settings-content-wrapper {
        display: flex;
        flex-direction: column;
        flex: 1;
        overflow-y: auto;
        padding-bottom: var(--spacing-8);
        position: relative; /* Ensure positioned context for absolutely positioned children */
    }

    .nav-button:hover {
        background: none;
    }
    
    .clickable-icon.icon_back {
        opacity: 0;
        width: 0px;
        visibility: hidden;
    }
    
    .clickable-icon.icon_back.visible {
        opacity: 1;
        width: 25px;
        visibility: visible;
    }

    :global(.active-chat-container) {
        transition: opacity var(--duration-slow) var(--easing-default);
    }

    :global(.active-chat-container.dimmed) {
        opacity: 0.3;
    }

    /* Hide icon grids from Login/Signup components when embedded in settings menu */
    .settings-content-wrapper :global(.login-container) {
        display: flex;
        flex-direction: column;
        justify-content: center;
    }

    .settings-content-wrapper :global(.login-container > .icon-grid) {
        display: none;
    }


</style>
