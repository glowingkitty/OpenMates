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
    import { browser } from '$app/environment';
    
    // SSR-safe store initialization - only create stores on the client
    export const teamEnabled: Writable<boolean> = browser ? writable(true) : {
        subscribe: () => () => {},
        set: () => {},
        update: () => {}
    } as any;
    
    export const settingsMenuVisible: Writable<boolean> = browser ? writable(false) : {
        subscribe: () => () => {},
        set: () => {},
        update: () => {}
    } as any;
    
    export const isMobileView: Writable<boolean> = browser ? writable(false) : {
        subscribe: () => () => {},
        set: () => {},
        update: () => {}
    } as any;
</script>

<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { fly, fade, slide } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { authStore, isCheckingAuth, logout } from '../stores/authStore'; // Import logout action
    import { isMenuOpen } from '../stores/menuState';
    import { getWebsiteUrl, routes } from '../config/links';
    import { tooltip } from '../actions/tooltip';
    import { isSignupSettingsStep, isInSignupProcess, isLoggingOut, currentSignupStep, showSignupFooter } from '../stores/signupState';
    import { userProfile, updateProfile } from '../stores/userProfile';
    import { settingsDeepLink } from '../stores/settingsDeepLinkStore';
    import { webSocketService } from '../services/websocketService';
    
    // Import modular components
    import SettingsFooter from './settings/SettingsFooter.svelte';
    import CurrentSettingsPage from './settings/CurrentSettingsPage.svelte';
    
    // Import all settings components
    import SettingsInterface from './settings/SettingsInterface.svelte';
    import SettingsPrivacy from './settings/SettingsPrivacy.svelte';
    import SettingsUser from './settings/SettingsUser.svelte';
    import SettingsUsage from './settings/SettingsUsage.svelte';
    import SettingsBilling from './settings/SettingsBilling.svelte';
    import SettingsAppStore from './settings/SettingsAppStore.svelte';
    import SettingsAllApps from './settings/SettingsAllApps.svelte';
    import AppDetailsWrapper from './settings/AppDetailsWrapper.svelte';
    import SettingsMates from './settings/SettingsMates.svelte';
    import SettingsShared from './settings/SettingsShared.svelte';
    import SettingsMessengers from './settings/SettingsMessengers.svelte';
    import SettingsDevelopers from './settings/SettingsDevelopers.svelte';
    import SettingsServer from './settings/SettingsServer.svelte';
    import SettingsItem from './SettingsItem.svelte';
    import SettingsLanguage from './settings/interface/SettingsLanguage.svelte';
    import SettingsSoftwareUpdate from './settings/server/SettingsSoftwareUpdate.svelte';
    import { appSkillsStore } from '../stores/appSkillsStore';
    
    // Import billing sub-components
    import SettingsBuyCredits from './settings/billing/SettingsBuyCredits.svelte';
    import SettingsBuyCreditsPayment from './settings/billing/SettingsBuyCreditsPayment.svelte';
    import SettingsBuyCreditsConfirmation from './settings/billing/SettingsBuyCreditsConfirmation.svelte';
    import SettingsAutoTopUp from './settings/billing/SettingsAutoTopUp.svelte';
    import SettingsLowBalanceAutotopup from './settings/billing/autotopup/SettingsLowBalanceAutotopup.svelte';
    import SettingsMonthlyAutotopup from './settings/billing/autotopup/SettingsMonthlyAutotopup.svelte';
    
    // Import the normal store instead of the derived one that was causing the error
    import { settingsNavigationStore } from '../stores/settingsNavigationStore';

    // Create event dispatcher for forwarding events to parent components
    const dispatch = createEventDispatcher();

    // Variable to store language change event handler
    let languageChangeHandler: () => void;

    // Props using Svelte 5 runes
    let { isLoggedIn = false }: { isLoggedIn?: boolean } = $props();
    
    // State for toggles and menu visibility
    let isMenuVisible = $state(false);
    let isTeamEnabled = $state(true);
    let isIncognitoEnabled = $state(false);
    let isGuestEnabled = $state(false);
    let isOfflineEnabled = $state(false);
    let showSubmenuInfo = $state(false); // New variable to control submenu info visibility
    let navButtonLeft = $state(false);
    let hideNavButton = $state(false); // New variable to control nav button visibility

    // Add reference to settings content element
    let settingsContentElement: HTMLElement | undefined = $state();
    let profileContainer: HTMLElement | undefined = $state();
    let profileContainerWrapper: HTMLElement | undefined = $state(); // Add reference for the wrapper

    // Get help link from routes
    const baseHelpLink = getWebsiteUrl(routes.docs.userGuide_settings || '/docs/userguide/settings');
    
    // Create a reactive help link that updates based on the active view
    let currentHelpLink = baseHelpLink;

    // Import account and security settings components
    import SettingsAccount from './settings/SettingsAccount.svelte';
    import SettingsSecurity from './settings/SettingsSecurity.svelte';
    import SettingsPasskeys from './settings/SettingsPasskeys.svelte';
    
    // Define base settingsViews map for component mapping
    const baseSettingsViews: Record<string, any> = {
        // TODO: Uncomment and implement these components when available
        // 'privacy': SettingsPrivacy,
        // 'user': SettingsUser,
        // 'usage': SettingsUsage,
        'billing': SettingsBilling,
        'billing/buy-credits': SettingsBuyCredits,
        'billing/buy-credits/payment': SettingsBuyCreditsPayment,
        'billing/buy-credits/confirmation': SettingsBuyCreditsConfirmation,
        'billing/auto-topup': SettingsAutoTopUp,
        'billing/auto-topup/low-balance': SettingsLowBalanceAutotopup,
        'billing/auto-topup/monthly': SettingsMonthlyAutotopup,
        'app_store': SettingsAppStore,
        'app_store/all': SettingsAllApps,
        // 'mates': SettingsMates,
        // 'shared': SettingsShared,
        // 'messengers': SettingsMessengers,
        // 'developers': SettingsDevelopers,
        'interface': SettingsInterface,
        // 'server': SettingsServer,
        'interface/language': SettingsLanguage,
        'account': SettingsAccount,
        'account/security': SettingsSecurity,
        'account/security/passkeys': SettingsPasskeys,
        // 'server/software-update': SettingsSoftwareUpdate
    };
    
    /**
     * Dynamically build settingsViews including app detail routes and nested sub-routes.
     * This creates:
     * - app_store/{app_id} routes for each available app
     * - app_store/{app_id}/skill/{skill_id} routes for each skill
     * - app_store/{app_id}/focus/{focus_mode_id} routes for each focus mode
     * - app_store/{app_id}/settings_memories routes for apps with settings/memories
     */
    function buildSettingsViews(): Record<string, any> {
        const views = { ...baseSettingsViews };
        
        // Add app detail routes dynamically
        const apps = appSkillsStore.getState().apps;
        for (const appId of Object.keys(apps)) {
            const app = apps[appId];
            
            // Main app details route
            const appRoute = `app_store/${appId}`;
            views[appRoute] = AppDetailsWrapper;
            
            // Add skill detail routes
            if (app.skills && app.skills.length > 0) {
                for (const skill of app.skills) {
                    const skillRoute = `app_store/${appId}/skill/${skill.id}`;
                    views[skillRoute] = AppDetailsWrapper;
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
                }
            }
        }
        
        return views;
    }
    
    // Reactive settingsViews that includes dynamic app routes
    let allSettingsViews = $derived(buildSettingsViews());

    // Reactive settingsViews that filters out server options for non-admins
    // For non-authenticated users, show interface settings (and nested language settings) and app store
    // This allows them to explore available features like mates and apps
    let settingsViews = $derived.by(() => {
        const isAuthenticated = $authStore.isAuthenticated;
        return Object.entries(allSettingsViews).reduce((filtered, [key, component]) => {
            // For non-authenticated users, include interface settings (top-level and nested) and app store (including app details)
            // App store is read-only for non-authenticated users (browse only, no modifications)
            if (!isAuthenticated) {
                if (key === 'interface' || key === 'interface/language' || key === 'app_store' || key.startsWith('app_store/')) {
                    filtered[key] = component;
                }
            } else {
                // For authenticated users, include all non-server settings, or include server settings if user is admin
                if (!key.startsWith('server') || $userProfile.is_admin) {
                    filtered[key] = component;
                }
            }
            return filtered;
        }, {} as Record<string, any>);
    });

    // Track navigation path parts for breadcrumb-style navigation
    let navigationPath: string[] = $state([]);
    let breadcrumbLabel = $state($text('settings.settings.text'));
    let fullBreadcrumbLabel = $state('');
    let shortBreadcrumbLabel = $state('');
    let navButtonElement: HTMLElement | undefined = $state();
    let currentPageInstance: CurrentSettingsPage | null = $state(null); // Reference to child component instance

    // Maximum width for breadcrumb text (in pixels)
    const MAX_BREADCRUMB_WIDTH = 220; // Adjusted to leave space for the back icon

    // Function to calculate the width of text with the correct font
    function getTextWidth(text, font = '14px "Lexend Deca Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif') {
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
            } catch (e) {
                console.warn('Could not get computed style, using default font weight');
            }
        }
        
        const metrics = context.measureText(text);
        return metrics.width;
    }
    
    // Function to create optimal breadcrumb text that fits available space
    function createOptimalBreadcrumb(pathLabels) {
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
        
        // Store the shortened version for tooltip
        shortBreadcrumbLabel = shortened;
        return shortened;
    }

    // Function to update breadcrumb label based on navigation path
    function updateBreadcrumbLabel() {
        if (navigationPath.length <= 0) {
            breadcrumbLabel = $text('settings.settings.text');
            fullBreadcrumbLabel = breadcrumbLabel;
            return;
        }
        
        // Create breadcrumb label with all path segments
        const pathLabels = [];
        
        // Always start with "Settings"
        pathLabels.push($text('settings.settings.text'));
        
        // Add each path segment's translated name (except the last one which is current view)
        for (let i = 0; i < navigationPath.length - 1; i++) {
            // Build the full path up to this segment
            const pathUpToSegment = navigationPath.slice(0, i + 1);
            const pathString = pathUpToSegment.join('/');
            
            // Handle app_store routes specially - use actual app/skill names from metadata
            if (pathString.startsWith('app_store/') && pathString !== 'app_store' && pathString !== 'app_store/all') {
                const pathParts = pathString.replace('app_store/', '').split('/');
                const appId = pathParts[0];
                const app = appSkillsStore.getState().apps[appId];
                
                if (app) {
                    // Use translated app name
                    const appName = app.name_translation_key ? $text(app.name_translation_key) : appId;
                    pathLabels.push(appName);
                } else {
                    // Fallback to translation key
                    const translationKeyParts = pathUpToSegment.map(segment => segment.replace(/-/g, '_'));
                    const translationKey = `settings.${translationKeyParts.join('.')}.text`;
                    pathLabels.push($text(translationKey));
                }
            } else {
                // For other routes, use translation keys
                const translationKeyParts = pathUpToSegment.map(segment => segment.replace(/-/g, '_'));
                const translationKey = `settings.${translationKeyParts.join('.')}.text`;
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
    let profile_image_url = $derived($userProfile.profile_image_url);
    let isInSignupMode = $derived($isInSignupProcess);

    // State to track active submenu view
    let activeSettingsView = $state('main');
    let direction = $state('forward');
    let activeSubMenuIcon = $state('');
    let activeSubMenuTitleKey = $state(''); // Store the translation key
    
    // Reactive translation of the submenu title
    let activeSubMenuTitle = $derived(activeSubMenuTitleKey ? $text(activeSubMenuTitleKey) : '');
    
    // Add reference for content height calculation
    let menuItemsCount = $state(0);
    
    // Calculate the content height based on the number of menu items
    let calculatedContentHeight = $derived(() => {
        const baseHeight = 200; // Base height for user info and padding
        const itemHeight = 50; // Average height per menu item
        return baseHeight + (menuItemsCount * itemHeight);
    });

    // Function to set active settings view with transitions
    function handleOpenSettings(event) {
        const { settingsPath, direction: newDirection, icon, title } = event.detail;
        direction = newDirection;

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
                    // Handle special case: email.svg -> mail
                    if (iconName === 'email') {
                        iconName = 'mail';
                    }
                    activeSubMenuIcon = iconName;
                } else {
                    activeSubMenuIcon = appId;
                }
                
                // Check if this is a skill route (app_store/{appId}/skill/{skillId})
                if (pathParts.length === 3 && pathParts[1] === 'skill') {
                    const skillId = pathParts[2];
                    const skill = app.skills?.find(s => s.id === skillId);
                    if (skill && skill.name_translation_key) {
                        // Use skill name translation key directly (not a placeholder)
                        activeSubMenuTitleKey = skill.name_translation_key;
                    } else {
                        // Fallback to app name if skill not found
                        activeSubMenuTitleKey = `apps.${appId}.text`;
                    }
                } else if (pathParts.length === 3 && pathParts[1] === 'focus') {
                    // Focus mode route
                    const focusModeId = pathParts[2];
                    const focusMode = app.focus_modes?.find(f => f.id === focusModeId);
                    if (focusMode && focusMode.name_translation_key) {
                        activeSubMenuTitleKey = focusMode.name_translation_key;
                    } else {
                        activeSubMenuTitleKey = `apps.${appId}.text`;
                    }
                } else if (pathParts.length === 3 && pathParts[1] === 'settings_memories') {
                    // Settings/memories category route
                    const categoryId = pathParts[2];
                    const category = app.settings_and_memories?.find(c => c.id === categoryId);
                    if (category && category.name_translation_key) {
                        activeSubMenuTitleKey = category.name_translation_key;
                    } else {
                        activeSubMenuTitleKey = `apps.${appId}.text`;
                    }
                } else {
                    // Regular app details route
                    activeSubMenuTitleKey = `apps.${appId}.text`;
                }
            } else {
                // Fallback if app not found
                activeSubMenuIcon = icon || appId;
                activeSubMenuTitleKey = `apps.${appId}.text`;
            }
        } else {
            // For other routes, use the provided icon and build translation key from path
            activeSubMenuIcon = icon || '';
            // Store the translation key instead of the translated text
            // Special handling for passkeys - skip "security" segment in translation key
            if (settingsPath === 'account/security/passkeys') {
                activeSubMenuTitleKey = 'settings.account.passkeys.text';
            } else {
                // Build the translation key from the path
                const translationKeyParts = settingsPath.split('/').map(segment => segment.replace(/-/g, '_'));
                activeSubMenuTitleKey = `settings.${translationKeyParts.join('.')}.text`;
            }
        }

        // Split the view path for breadcrumb navigation
        if (settingsPath !== 'main') {
            navigationPath = settingsPath.split('/');
            updateBreadcrumbLabel();
        } else {
            navigationPath = [];
            breadcrumbLabel = $text('settings.settings.text');
        }

        // Reset submenu info visibility
        showSubmenuInfo = false;
        navButtonLeft = false;

        // Update help link based on the active settings view
        if (settingsPath !== 'main') {
            // Handle nested paths in help links (replace / with -)
            const helpPath = settingsPath.replace('/', '-');
            currentHelpLink = `${baseHelpLink}/${helpPath}`;
            navButtonLeft = true;

            // Show left navigation and submenu info immediately for smooth transition
            showSubmenuInfo = true;
        } else {
            // Reset to base help link when returning to main view
            currentHelpLink = baseHelpLink;
        }
        
        if (profileContainer) {
            profileContainer.classList.add('submenu-active');
        }
        
        // Scroll to the top of the settings content
        if (settingsContentElement) {
            settingsContentElement.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        }
    }

    // Enhanced back navigation - handle both main and nested views
    function backToMainView(event) {
        // Prevent event bubbling to avoid closing the menu
        if (event) {
            event.stopPropagation();
        }
        
        if (navigationPath.length > 1) {
            // If we're in a nested view, go back one level
            const previousPath = navigationPath.slice(0, -1).join('/');
            
            // Build the correct icon and title for the previous view
            const previousPathSegments = navigationPath.slice(0, -1);
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
                        if (iconName === 'email') {
                            iconName = 'mail';
                        }
                        icon = iconName;
                    } else {
                        icon = appId;
                    }
                    
                    // Use translated app name
                    title = app.name_translation_key ? $text(app.name_translation_key) : appId;
                } else {
                    icon = appId;
                    title = $text(`apps.${appId}.text`);
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
                } else if (previousPath === 'app_store') {
                    icon = 'app_store';
                }
                // For other nested paths (like account/security), icon is already set to last segment above
                
                // Build the translation key for the previous view's title
                const translationKeyParts = previousPathSegments.map(segment => segment.replace(/-/g, '_'));
                const titleKey = `settings.${translationKeyParts.join('.')}.text`;
                title = $text(titleKey);
            }
            
            direction = 'backward';
            handleOpenSettings({
                detail: {
                    settingsPath: previousPath,
                    direction: 'backward',
                    icon: icon,
                    title: title
                }
            });
        } else {
            // If we're at the first level, go back to main
            direction = 'backward';
            activeSettingsView = 'main';
            showSubmenuInfo = false;
            navButtonLeft = false;
            navigationPath = [];
            breadcrumbLabel = $text('settings.settings.text');
            
            // Reset help link to base when returning to main view
            currentHelpLink = baseHelpLink;
            
            if (profileContainer) {
                profileContainer.classList.remove('submenu-active');
            }
            
            // Scroll to top when going back to main view
            if (settingsContentElement) {
                settingsContentElement.scrollTo({
                    top: 0,
                    behavior: 'smooth'
                });
            }
        }
    }

    // No more docking/undocking - we use two separate containers instead
   
    // Track when profile container should be hidden (after transform animation completes)
    let hideOriginalProfile = $state(false);
    let hideProfileTimeout: ReturnType<typeof setTimeout> | null = null;
   
    // Handler for profile click to show menu
    function toggleMenu() {
        isMenuVisible = !isMenuVisible;
        settingsMenuVisible.set(isMenuVisible);
        
        // Clear any existing timeout
        if (hideProfileTimeout) {
            clearTimeout(hideProfileTimeout);
            hideProfileTimeout = null;
        }
        
        if (isMenuVisible) {
            // Delay hiding the original profile until after transform animation (400ms)
            // This allows it to move to its position first, then hide
            hideProfileTimeout = setTimeout(() => {
                hideOriginalProfile = true;
            }, 400);
        } else {
            // Show immediately when menu closes
            hideOriginalProfile = false;
        }

        // If menu is being closed, reset scroll position and view state
        if (!isMenuVisible && settingsContentElement) {
        	// Reset profile visibility immediately when closing via toggleMenu
        	hideOriginalProfile = false;
        	if (hideProfileTimeout) {
        		clearTimeout(hideProfileTimeout);
        		hideProfileTimeout = null;
        	}
        	
        	// Reset the active view to main when closing the menu
        	activeSettingsView = 'main';
        	navigationPath = [];
        	breadcrumbLabel = $text('settings.settings.text');
        	showSubmenuInfo = false;
        	navButtonLeft = false;
        	hideNavButton = false; // Reset hide nav button flag

        	// Reset help link to base
        	currentHelpLink = baseHelpLink;

        	// Remove submenu-active class from profile container
        	if (profileContainer) {
        		profileContainer.classList.remove('submenu-active');
        	}

        	// Reset scroll position
        	setTimeout(() => {
        		settingsContentElement.scrollTop = 0;
        	}, 300);
        } else if (isMenuVisible) {
        	// Menu is opening - original profile container will animate to its position
        	// The duplicate profile container in settings will fade in
        }
    }

    // Handler for quicksettings menu item clicks
    function handleQuickSettingClick(event) {
        const { toggleName } = event.detail;
        
        switch(toggleName) {
            case 'team':
                isTeamEnabled = !isTeamEnabled;
                teamEnabled.set(isTeamEnabled);
                break;
            case 'incognito':
                isIncognitoEnabled = !isIncognitoEnabled;
                break;
            case 'guest':
                isGuestEnabled = !isGuestEnabled;
                break;
            case 'offline':
                isOfflineEnabled = !isOfflineEnabled;
                break;
        }
    }

    // Handle window resize
    function updateMobileState() {
        const isMobile = window.innerWidth <= 1100;
        isMobileView.set(isMobile);
    }

    // Click outside handler
    function handleClickOutside(event) {
    	if ($isMobileView) {
    		const settingsMenu = document.querySelector('.settings-menu');
    		const profileWrapper = document.querySelector('.profile-container-wrapper');
    		const closeButton = document.querySelector('.close-icon-container');
   
    		// Only close the menu if the click is truly outside all menu-related elements
    		// This prevents the menu from closing when clicking anywhere within the settings menu
    		const isClickInsideMenu = settingsMenu && settingsMenu.contains(event.target as Node);
    		const isClickInsideProfile = profileWrapper && profileWrapper.contains(event.target as Node);
    		const isClickInsideCloseButton = closeButton && closeButton.contains(event.target as Node);
    		
    		// Only close if the click is outside all menu-related elements
    		if (!isClickInsideMenu && !isClickInsideProfile && !isClickInsideCloseButton) {
    			isMenuVisible = false;
    			settingsMenuVisible.set(false);
    			// Reset profile visibility so it shows again
    			hideOriginalProfile = false;
    			if (hideProfileTimeout) {
    				clearTimeout(hideProfileTimeout);
    				hideProfileTimeout = null;
    			}
    		}
    	}
    }

    // Setup listeners
    onMount(() => {
        updateMobileState();
        window.addEventListener('resize', handleResize);
        document.addEventListener('click', handleClickOutside);
        
        // Add listener for language changes
        languageChangeHandler = () => {
            // Update breadcrumbs when language changes
            updateBreadcrumbLabel();
        };
        window.addEventListener('language-changed', languageChangeHandler);

        const handleCreditUpdate = (payload: { credits: number }) => {
            const newCredits = payload.credits;
            if (typeof newCredits === 'number') {
                updateProfile({ credits: newCredits });
            }
        };

        webSocketService.on('user_credits_updated', handleCreditUpdate);
        
        return () => {
            window.removeEventListener('resize', handleResize);
            document.removeEventListener('click', handleClickOutside);
            window.removeEventListener('language-changed', languageChangeHandler);
            webSocketService.off('user_credits_updated', handleCreditUpdate);
        };
    });

    // Update DOM elements opacity and classes based on menu state
    $effect(() => {
        if (typeof window !== 'undefined') {
            const activeChatContainer = document.querySelector('.active-chat-container');
            if (activeChatContainer) {
                if (window.innerWidth <= 1100 && isMenuVisible) {
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
                    console.debug('[Settings] Dispatching userLoggingOut event to clear chats and load demo');
                    window.dispatchEvent(new CustomEvent('userLoggingOut'));
                    
                    // Reset scroll position
                 	if (settingsContentElement) {
                 		settingsContentElement.scrollTop = 0;
                 	}
                    // Close the settings menu visually
                 	isMenuVisible = false;
                 	settingsMenuVisible.set(false);
                 	// Reset profile visibility so it shows again
                 	hideOriginalProfile = false;
                 	if (hideProfileTimeout) {
                 		clearTimeout(hideProfileTimeout);
                 		hideProfileTimeout = null;
                 	}
                    // Small delay to allow settings menu to close visually and state to clear
                 	await new Promise(resolve => setTimeout(resolve, 200)); // Slightly longer to ensure state is cleared
                },
                afterServerCleanup: async () => {
                    // Actions after server logout and DB cleanup are complete (runs async)
                    // CRITICAL: Keep chats panel open during logout - don't close it
                    // The panel should remain open to show demo chats after logout
                    // Only close settings menu
                 	isMenuOpen.set(false);
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
    let breadcrumbs = $derived($settingsNavigationStore.breadcrumbs.map(crumb => ({
        ...crumb,
        // Apply translations to breadcrumb titles
        title: crumb.translationKey ? $text(crumb.translationKey + '.text') : crumb.title
    })));

    // Make breadcrumbLabel reactive to text store changes
    $effect(() => {
        if ($text) {
            updateBreadcrumbLabel();
        }
    });

    // Handle deep link requests from other components (only for authenticated users)
    $effect(() => {
        if ($settingsDeepLink && $authStore.isAuthenticated) {
            const settingsPath = $settingsDeepLink;

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
                // Determine the icon and title based on the path
                const icon = settingsPath.split('/')[0];
                const title = $text(`settings.${icon}.text`);

                handleOpenSettings({
                    detail: {
                        settingsPath,
                        direction: 'forward',
                        icon,
                        title
                    }
                });
            }, 300);
        } else if ($settingsDeepLink && !$authStore.isAuthenticated) {
            // Clear the deep link if user is not authenticated (can't navigate to settings while not logged in)
            settingsDeepLink.set(null);
        }
    });

    // Watch settingsMenuVisible store to handle external close requests
    $effect(() => {
    	// If store value changes from true to false and our local state is still true
    	if (!$settingsMenuVisible && isMenuVisible) {
    		isMenuVisible = false;
    		// Reset profile visibility so it shows again
    		hideOriginalProfile = false;
    		if (hideProfileTimeout) {
    			clearTimeout(hideProfileTimeout);
    			hideProfileTimeout = null;
    		}
   
    		// Remove mobile overlay class when closing
    		const menuElement = document.querySelector('.settings-menu');
    		if (menuElement) {
    			menuElement.classList.remove('mobile-overlay');
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
    		class="profile-container"
    		class:menu-open={isMenuVisible}
    		class:hidden={hideOriginalProfile}
    		onclick={toggleMenu}
    		onkeydown={e => e.key === 'Enter' && toggleMenu()}
    		role="button"
    		tabindex="0"
    		aria-label={$text('settings.open_settings_menu.text')}
    		bind:this={profileContainer}
    	>
            <!-- Show language icon when not logged in and menu is closed, user icon when menu is open -->
            <!-- Show profile picture when user is logged in -->
            {#if !$authStore.isAuthenticated}
                <div class="profile-picture language-icon-container">
                    <div class="clickable-icon" class:icon_language={!isMenuVisible} class:icon_user={isMenuVisible}></div>
                </div>
            {:else}
                <div
                    class="profile-picture"
                    style={profile_image_url ? `background-image: url(${profile_image_url})` : ''}
                >
                    {#if !profile_image_url}
                        <div class="default-user-icon"></div>
                    {/if}
                </div>
            {/if}
    	</div>
    </div>

        <div class="close-icon-container" class:visible={isMenuVisible}>
            <button 
                class="icon-button"
                aria-label={$text('settings.close_settings_menu.text')}
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
    class:visible={isMenuVisible}
    class:overlay={isMenuVisible}
    class:mobile={$isMobileView}
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
    role="presentation"
>
    <div class="settings-header" class:submenu-active={activeSettingsView !== 'main' && showSubmenuInfo} onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()} role="presentation">
        <div class="header-content">
            {#if !hideNavButton}
                <button
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
                aria-label={$text('documentation.open_documentation.text')}
            >
                <div class="help-button"></div>
            </a> -->
        </div>
        
        {#if activeSettingsView !== 'main' && showSubmenuInfo}
            <div
                class="submenu-info"
                class:reduced-padding={hideNavButton}
                transition:slide={{ duration: 300, easing: cubicOut }}
            >
                <!-- Replace this with SettingsItem component -->
                <SettingsItem
                    type="heading"
                    icon={activeSubMenuIcon}
                    title={activeSubMenuTitle}
                />
            </div>
        {/if}
    </div>
    
    <div class="settings-content-wrapper" bind:this={settingsContentElement} onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()} role="presentation">
        <!-- Show settings menu for both authenticated and non-authenticated users -->
        <!-- For non-authenticated users, only language settings are available -->
        <CurrentSettingsPage
        	bind:this={currentPageInstance}
        	{activeSettingsView}
        	{direction}
        	{username}
            {isInSignupMode}
            {settingsViews}
            {isMenuVisible}
            bind:isIncognitoEnabled
            bind:isGuestEnabled
            bind:isOfflineEnabled
            bind:menuItemsCount
            on:openSettings={handleOpenSettings}
            on:quickSettingClick={handleQuickSettingClick}
            on:logout={handleLogout}
        />

        <!-- Show footer for both authenticated and non-authenticated users -->
        <!-- This displays social links and legal information -->
        <SettingsFooter
            on:chatSelected={(e) => {
                // Forward chatSelected event to parent (+page.svelte)
                dispatch('chatSelected', e.detail);
            }}
            on:closeSettings={() => {
                // Close settings menu when a legal chat is opened
                isMenuVisible = false;
                settingsMenuVisible.set(false);
                // Reset profile visibility so it shows again
                hideOriginalProfile = false;
                if (hideProfileTimeout) {
                    clearTimeout(hideProfileTimeout);
                    hideProfileTimeout = null;
                }
            }}
        />
    </div>
</div>

<style>
    .profile-container-wrapper {
        position: fixed;
        top: 8px;
        right: 10px;
        width: 50px;
        height: 50px;
        z-index: 1005;
        transition: opacity 0.3s ease, top 0.3s ease, position 0.3s ease;
    }

    .profile-container-wrapper.signup-footer-mode {
        position: absolute;
        top: 8px;
        /* Use calc to ensure it doesn't extend beyond viewport */
        left: calc(100% - 67px); /* 57px width + 10px margin */
        right: auto;
    }

    .profile-container {
        position: absolute;
        top: 0;
        right: 0;
        width: 50px;
        height: 50px;
        border-radius: 50%;
        cursor: pointer;
        transition: transform 0.4s cubic-bezier(0.215, 0.61, 0.355, 1);
        opacity: 1;
    }

    .profile-container.hidden {
        opacity: 0;
        pointer-events: none;
        /* No transition - hide instantly to match docked profile appearance */
        transition: transform 0.4s cubic-bezier(0.215, 0.61, 0.355, 1);
    }

    .profile-container.menu-open {
    	transform: translate(-265px, 110px);
    }

    @media (max-width: 730px) {
        .profile-container.menu-open {
            transform: translate(-255px, 110px);
        }
    }
   
    .close-icon-container {
        position: absolute;
        top: 0;
        right: 0;
        width: 50px;
        height: 50px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        visibility: hidden;
        transition: all 0.3s ease;
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
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .language-icon-container {
        background-color: var(--color-primary);
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
        transition: width 0.3s ease;
        z-index: 1001;
    }

    @media (max-width: 1100px) {
        .settings-menu {
            position: fixed;
            right: 20px;
            top: 65px;
            bottom: 18px;
            height: auto;
            z-index: 1000;
            visibility: hidden; /* Hide by default on mobile */
        }

        .settings-menu.visible {
            visibility: visible;
        }

        .settings-menu.overlay {
            box-shadow: -4px 0 12px rgba(0, 0, 0, 0.15);
        }
        
        /* Add mobile overlay style for higher z-index */
        /* This class is added dynamically via JavaScript - see lines 636, 669, 682 */
        /* svelte-ignore css_unused_selector */
        .settings-menu.mobile-overlay {
            z-index: 1006 !important; /* Higher than profile-container-wrapper */
        }
    }

    @media (max-width: 730px) {
        .settings-menu {
            right: 10px;
            bottom: 10px;
        }
    }

    .settings-menu.visible {
        width: 323px;
        visibility: visible;
    }

    .settings-header,
    .settings-content-wrapper {
        opacity: 0;
        transition: opacity 0.3s ease 0s;
    }

    .settings-menu.visible .settings-header,
    .settings-menu.visible .settings-content-wrapper {
        opacity: 1;
        transition: opacity 0.3s ease 0.15s;
    }

    .settings-header {
        background-color: var(--color-grey-20);
        padding-bottom: 12px;
        position: sticky;
        top: 0;
        z-index: 10;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        display: flex;
        flex-direction: column;
        border-bottom: 1px solid var(--color-grey-30);
        position: relative;
        min-height: 30px;
    }

    .header-content {
        width: 100%;
        position: relative;
        transition: all 0.3s ease;
    }

    .settings-header.submenu-active {
        padding-bottom: 20px; /* Space for submenu info */
        transition: padding-bottom 0.3s ease; /* Smooth padding transition */
    }

    .nav-button {
        all: unset;
        font-size: 14px;
        color: var(--color-grey-60);
        cursor: default;
        display: flex;
        align-items: center;
        position: absolute;
        left: 110px;
        top: 10px;
        padding: 4px 0;
        transition: all 0.3s ease;
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
        padding-top: 40px;
        margin-bottom: -10px;
        overflow: hidden;
    }
    
    .submenu-info.reduced-padding {
        padding-top: 10px;
    }


    .settings-content-wrapper {
        display: flex;
        flex-direction: column;
        flex: 1;
        overflow-y: auto;
        padding-bottom: 16px;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
        position: relative; /* Ensure positioned context for absolutely positioned children */
    }
    
    .settings-content-wrapper:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }
    
    .settings-content-wrapper::-webkit-scrollbar {
        width: 8px;
    }
    
    .settings-content-wrapper::-webkit-scrollbar-track {
        background: transparent;
    }
    
    .settings-content-wrapper::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid var(--color-grey-20);
        transition: background-color 0.2s ease;
    }
    
    .settings-content-wrapper:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }
    
    .settings-content-wrapper::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
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
        transition: opacity 0.3s ease;
    }

    :global(.active-chat-container.dimmed) {
        opacity: 0.3;
    }

    /* Hide icon grids from Login/Signup components when embedded in settings menu */
    .settings-content-wrapper :global(.login-container) {
        display: flex;
        flex-direction: column;
    }


</style>

