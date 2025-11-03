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
    import { onMount } from 'svelte';
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
    import SettingsApps from './settings/SettingsApps.svelte';
    import SettingsMates from './settings/SettingsMates.svelte';
    import SettingsShared from './settings/SettingsShared.svelte';
    import SettingsMessengers from './settings/SettingsMessengers.svelte';
    import SettingsDevelopers from './settings/SettingsDevelopers.svelte';
    import SettingsServer from './settings/SettingsServer.svelte';
    import SettingsItem from './SettingsItem.svelte';
    import SettingsLanguage from './settings/interface/SettingsLanguage.svelte';
    import SettingsSoftwareUpdate from './settings/server/SettingsSoftwareUpdate.svelte';
    
    // Import billing sub-components
    import SettingsBuyCredits from './settings/billing/SettingsBuyCredits.svelte';
    import SettingsBuyCreditsPayment from './settings/billing/SettingsBuyCreditsPayment.svelte';
    import SettingsBuyCreditsConfirmation from './settings/billing/SettingsBuyCreditsConfirmation.svelte';
    import SettingsAutoTopUp from './settings/billing/SettingsAutoTopUp.svelte';
    import SettingsLowBalanceAutotopup from './settings/billing/autotopup/SettingsLowBalanceAutotopup.svelte';
    import SettingsMonthlyAutotopup from './settings/billing/autotopup/SettingsMonthlyAutotopup.svelte';
    
    // Import the normal store instead of the derived one that was causing the error
    import { settingsNavigationStore } from '../stores/settingsNavigationStore';


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

    // Define base settingsViews map for component mapping
    const allSettingsViews: Record<string, any> = {
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
        // 'apps': SettingsApps,
        // 'mates': SettingsMates,
        // 'shared': SettingsShared,
        // 'messengers': SettingsMessengers,
        // 'developers': SettingsDevelopers,
        'interface': SettingsInterface,
        // 'server': SettingsServer,
        'interface/language': SettingsLanguage,
        // 'server/software-update': SettingsSoftwareUpdate
    };

    // Reactive settingsViews that filters out server options for non-admins
    let settingsViews = $derived(Object.entries(allSettingsViews).reduce((filtered, [key, component]) => {
        // Include all non-server settings, or include server settings if user is admin
        if (!key.startsWith('server') || $userProfile.is_admin) {
            filtered[key] = component;
        }
        return filtered;
    }, {} as Record<string, any>));

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
            // Build the full path up to this segment (for nested translations)
            const pathUpToSegment = navigationPath.slice(0, i + 1);
            
            // Convert path segments to translation key format (replace hyphens with underscores)
            const translationKeyParts = pathUpToSegment.map(segment => segment.replace(/-/g, '_'));
            const translationKey = `settings.${translationKeyParts.join('.')}.text`;
            
            pathLabels.push($text(translationKey));
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
    
    let username = $derived($userProfile.username || 'Guest');
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

        // Normal behavior for authenticated users
        if ($authStore.isAuthenticated) {
            activeSettingsView = settingsPath;
            activeSubMenuIcon = icon || '';
            // Store the translation key instead of the translated text
            // Build the translation key from the path
            const translationKeyParts = settingsPath.split('/').map(segment => segment.replace(/-/g, '_'));
            activeSubMenuTitleKey = `settings.${translationKeyParts.join('.')}.text`;

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
            let icon = previousPathSegments[0]; // Default to first segment

            // For nested billing paths, determine the correct icon
            if (previousPath === 'billing/buy-credits') {
                icon = 'coins';
            } else if (previousPath === 'billing/auto-topup') {
                icon = 'reload';
            } else if (previousPath === 'billing/auto-topup/low-balance') {
                icon = 'reload';
            } else if (previousPath === 'billing/auto-topup/monthly') {
                icon = 'calendar';
            }
            
            // Build the translation key for the previous view's title
            const translationKeyParts = previousPathSegments.map(segment => segment.replace(/-/g, '_'));
            const titleKey = `settings.${translationKeyParts.join('.')}.text`;
            
            direction = 'backward';
            handleOpenSettings({
                detail: {
                    settingsPath: previousPath,
                    direction: 'backward',
                    icon: icon,
                    title: $text(titleKey)
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

    // Helper function to move profile container into the child's slider element
    function dockProfileContainer() {
    	const targetSliderElement = currentPageInstance?.sliderElement;
    	if (!profileContainer || !targetSliderElement || !profileContainer.parentNode) return;
   
    	// Check if already docked to prevent errors
    	if (profileContainer.parentNode === targetSliderElement) {
    		return;
    	}
   
    	// Prepend to the child's slider element
    	targetSliderElement.prepend(profileContainer);
   
    	// Apply docked styles (absolute position, final transform)
    	profileContainer.style.transform = 'translate(-245px, 10px)';
    }
   
    // Helper function to move profile container back to its original wrapper
    function undockProfileContainer() {
    	if (!profileContainer || !profileContainerWrapper || !profileContainer.parentNode) return;
   
    	// Check if it's currently docked inside the child's slider
    	const targetSliderElement = currentPageInstance?.sliderElement;
    	if (!targetSliderElement || profileContainer.parentNode !== targetSliderElement) {
    		return;
    	}
   
    	// Remove docked styles
    	profileContainer.style.transform = '';

    	// Move back to the original wrapper
    	profileContainerWrapper.appendChild(profileContainer);
    }
   
    // Handler for the profile container's transition end
    function onProfileTransitionEnd(event: TransitionEvent) {
    	// Only act when the 'transform' property finishes transitioning and menu is open
    	if (event.propertyName === 'transform' && isMenuVisible) {
    		dockProfileContainer();
    	}
    }
   
   
    // Handler for profile click to show menu
    function toggleMenu() {
        isMenuVisible = !isMenuVisible;
        settingsMenuVisible.set(isMenuVisible);

        // If menu is being closed, reset scroll position and view state
        if (!isMenuVisible && settingsContentElement) {
        	// Undock the profile container *before* starting the close animation
        	// This ensures it animates back from the correct parent
        	undockProfileContainer();

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
        	// Menu is opening. The docking will happen on transition end.
        	// Ensure initial state is correct (absolute positioning)
        	profileContainer.style.position = 'absolute';

            // For non-authenticated users, automatically open language settings submenu
            if (!$authStore.isAuthenticated) {
                // Wait a bit for menu to open, then navigate to language settings
                setTimeout(() => {
                    handleOpenSettings({
                        detail: {
                            settingsPath: 'interface/language',
                            direction: 'forward',
                            icon: 'language',
                            title: $text('settings.interface.language.text')
                        }
                    });
                }, 100);
            }
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
                    // Ensure profile container is undocked before closing menu visually
                 	undockProfileContainer();
                },
                afterLocalLogout: async () => {
                    // Actions after local state is reset but before server cleanup starts
                    // Reset scroll position
                 	if (settingsContentElement) {
                 		settingsContentElement.scrollTop = 0;
                 	}
                    // Close the settings menu visually
                 	isMenuVisible = false;
                 	settingsMenuVisible.set(false);
                    // Small delay to allow settings menu to close visually
                 	await new Promise(resolve => setTimeout(resolve, 100)); // Shorter delay might suffice now
                },
                afterServerCleanup: async () => {
                    // Actions after server logout and DB cleanup are complete (runs async)
                    // Close the sidebar menu (can happen after local state reset)
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
    		undockProfileContainer(); // Undock when closed externally
   
    		// Remove mobile overlay class when closing
    		const menuElement = document.querySelector('.settings-menu');
    		if (menuElement) {
    			menuElement.classList.remove('mobile-overlay');
    		}
   
    		// Don't call toggleMenu again, just update state
    	} else if ($settingsMenuVisible && !isMenuVisible) {
    		// If store value changes from false to true and our local state is still false
    		isMenuVisible = true;
    		// Docking will happen via transitionend triggered by toggleMenu or deep link
   
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
    		class:hidden={isMenuVisible && activeSettingsView !== 'main'}
    		onclick={toggleMenu}
    		onkeydown={e => e.key === 'Enter' && toggleMenu()}
    		role="button"
    		tabindex="0"
    		aria-label={$text('settings.open_settings_menu.text')}
    		bind:this={profileContainer}
    		ontransitionend={onProfileTransitionEnd}
    	>
            <!-- Show language icon instead of profile picture when user is not logged in or hasn't gone beyond profile picture step -->
            {#if !$authStore.isAuthenticated}
                <div class="profile-picture language-icon-container">
                    <div class="clickable-icon icon_language"></div>
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
        {#if $authStore.isAuthenticated}
            <!-- Show settings menu for authenticated users -->
            <CurrentSettingsPage
            	bind:this={currentPageInstance}
            	{activeSettingsView}
            	{direction}
            	{username}
                {isInSignupMode}
                {settingsViews}
                bind:isIncognitoEnabled
                bind:isGuestEnabled
                bind:isOfflineEnabled
                bind:menuItemsCount
                on:openSettings={handleOpenSettings}
                on:quickSettingClick={handleQuickSettingClick}
                on:logout={handleLogout}
            />
        {/if}

        {#if $authStore.isAuthenticated}
            <SettingsFooter/>
        {/if}
    </div>
</div>

<style>
    .profile-container-wrapper {
        position: fixed;
        top: 10px;
        right: 10px;
        width: 57px;
        height: 57px;
        z-index: 1005;
        transition: opacity 0.3s ease, top 0.3s ease, position 0.3s ease;
    }

    .profile-container-wrapper.signup-footer-mode {
        position: absolute;
        top: 10px;
        /* Use calc to ensure it doesn't extend beyond viewport */
        left: calc(100% - 67px); /* 57px width + 10px margin */
        right: auto;
    }

    .profile-container {
        position: absolute;
        top: 0;
        right: 0;
        width: 57px;
        height: 57px;
        border-radius: 50%;
        cursor: pointer;
        transition: transform 0.4s cubic-bezier(0.215, 0.61, 0.355, 1), opacity 0.3s ease;
        opacity: 1;
    }

    .profile-container.hidden {
        opacity: 0;
        pointer-events: none;
    }

    .profile-container.menu-open {
    	transform: translate(-265px, 120px);
    }
   
    .close-icon-container {
        position: absolute;
        top: 0;
        right: 0;
        width: 57px;
        height: 57px;
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
            top: 80px;
            bottom: 25px;
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

