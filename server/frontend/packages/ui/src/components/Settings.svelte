<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml

-->
<script lang="ts" context="module">
    import { writable } from 'svelte/store';
    import { text } from '@repo/ui';
    export const teamEnabled = writable(true);
    export const settingsMenuVisible = writable(false);
    export const isMobileView = writable(false);
</script>

<script lang="ts">
    import { onMount } from 'svelte';
    import { fly, fade, slide } from 'svelte/transition'; // Add slide transition import
    import { cubicOut } from 'svelte/easing';
    import { isAuthenticated, currentUser, logout } from '../stores/authState';
    import { isMenuOpen } from '../stores/menuState';
    import { isCheckingAuth } from '../stores/authCheckState';
    import { getApiEndpoint, apiEndpoints } from '../config/api';
    import { externalLinks, getWebsiteUrl, routes } from '../config/links';
    import { tooltip } from '../actions/tooltip';
    import { isSignupSettingsStep, isInSignupProcess } from '../stores/signupState';
    import { userProfile } from '../stores/userProfile';
    import { AuthService } from '../services/authService';
    
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
    import SettingsItem from './SettingsItem.svelte'; // Add this import
    
    // Props for user and team information
    export let isLoggedIn = false;
    
    // State for toggles and menu visibility
    let isMenuVisible = false;
    let isTeamEnabled = true;
    let isIncognitoEnabled = false;
    let isGuestEnabled = false;
    let isOfflineEnabled = false;
    let showSubmenuInfo = false; // New variable to control submenu info visibility
    let navButtonLeft = false;

    // Add reference to settings content element
    let settingsContentElement;
    let profileContainer;

    // Get help link from routes
    const baseHelpLink = getWebsiteUrl(routes.docs.userGuide_settings || '/docs/userguide/settings');
    
    // Create a reactive help link that updates based on the active view
    let currentHelpLink = baseHelpLink;

    // Define settingsViews map for component mapping
    const settingsViews: Record<string, any> = {
        'privacy': SettingsPrivacy,
        'user': SettingsUser,
        'usage': SettingsUsage,
        'billing': SettingsBilling,
        'apps': SettingsApps,
        'mates': SettingsMates,
        'shared': SettingsShared,
        'messengers': SettingsMessengers,
        'developers': SettingsDevelopers,
        'interface': SettingsInterface
    };

    // Reactive variables
    $: showSettingsIcon = isLoggedIn || $isSignupSettingsStep;
    $: isInSignup = $isInSignupProcess;
    $: username = $userProfile.username || 'Guest';
    $: profileImageUrl = $userProfile.profileImageUrl;
    $: isInSignupMode = $isInSignupProcess;

    // State to track active submenu view
    let activeSettingsView = 'main';
    let direction = 'forward';
    let activeSubMenuIcon = '';
    let activeSubMenuTitle = '';
    
    // Function to set active settings view with transitions
    function handleViewChange(event) {
        const { viewName, direction: newDirection, icon, title } = event.detail;
        direction = newDirection;
        activeSettingsView = viewName;
        activeSubMenuIcon = icon || '';
        activeSubMenuTitle = title || '';
        
        // Reset submenu info visibility
        showSubmenuInfo = false;
        navButtonLeft = false;
        
        // Update help link based on the active settings view
        if (viewName !== 'main') {
            currentHelpLink = `${baseHelpLink}/${viewName}`;
            navButtonLeft = true;
            showSubmenuInfo = true;

            setTimeout(() => {
                showSubmenuInfo = true;
            }, 300); // Match this with your transition duration
        } else {
            // Reset to base help link when returning to main view
            currentHelpLink = baseHelpLink;
        }
        
        if (profileContainer) {
            profileContainer.classList.add('submenu-active');
        }
        
        // Delay showing submenu info to allow animation to complete
        if (viewName !== 'main') {
            navButtonLeft = true;
            showSubmenuInfo = true;

            setTimeout(() => {
                showSubmenuInfo = true;
            }, 300); // Match this with your transition duration
        }
    }
    
    // Function to return to main view with transitions
    function backToMainView() {
        direction = 'backward';
        activeSettingsView = 'main';
        showSubmenuInfo = false; // Hide submenu info immediately when going back
        navButtonLeft = false;
        
        // Reset help link to base when returning to main view
        currentHelpLink = baseHelpLink;
        
        if (profileContainer) {
            profileContainer.classList.remove('submenu-active');
        }
    }

    // Handler for profile click to show menu
    function toggleMenu() {
        isMenuVisible = !isMenuVisible;
        settingsMenuVisible.set(isMenuVisible);
        
        // If menu is being closed, reset scroll position
        if (!isMenuVisible && settingsContentElement) {
            setTimeout(() => {
                settingsContentElement.scrollTop = 0;
            }, 300);
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
        isMobileView.set(window.innerWidth <= 1100);
    }

    // Click outside handler
    function handleClickOutside(event) {
        if ($isMobileView) {
            const settingsMenu = document.querySelector('.settings-menu');
            const profileContainer = document.querySelector('.profile-container');
            
            if (settingsMenu && 
                profileContainer && 
                !settingsMenu.contains(event.target) && 
                !profileContainer.contains(event.target)) {
                isMenuVisible = false;
                settingsMenuVisible.set(false);
            }
        }
    }

    // Setup listeners
    onMount(() => {
        updateMobileState();
        window.addEventListener('resize', updateMobileState);
        document.addEventListener('click', handleClickOutside);
        
        return () => {
            window.removeEventListener('resize', updateMobileState);
            document.removeEventListener('click', handleClickOutside);
        };
    });

    // Update DOM elements opacity and classes based on menu state
    $: if (typeof window !== 'undefined') {
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

    async function handleLogout() {
        try {
            // If in signup process, just close the menu without actual logout
            if (isInSignup) {
                isMenuVisible = false;
                settingsMenuVisible.set(false);
                return;
            }

            await AuthService.logout({
                beforeServerLogout: () => {
                    // Reset the checking auth state immediately
                    isCheckingAuth.set(false);
                },

                afterServerLogout: async () => {
                    // Reset scroll position
                    if (settingsContentElement) {
                        settingsContentElement.scrollTop = 0;
                    }

                    // Close the settings menu
                    isMenuVisible = false;
                    settingsMenuVisible.set(false);

                    // Small delay to allow settings menu to close
                    await new Promise(resolve => setTimeout(resolve, 300));

                    // Close the sidebar menu
                    isMenuOpen.set(false);

                    // Small delay to allow sidebar animation
                    await new Promise(resolve => setTimeout(resolve, 300));
                },

                finalLogout: () => {
                    // Finally perform the client-side logout
                    logout();
                }
            });
        } catch (error) {
            console.error('Error during logout:', error);
            logout();
        }
    }
</script>

{#if showSettingsIcon}
    <div 
        class="profile-container-wrapper"
        in:fly={{ y: -window.innerHeight/2 + 60, x: 0, duration: 800, easing: cubicOut }}
        out:fade
    >
        <div 
            class="profile-container" 
            class:menu-open={isMenuVisible}
            class:hidden={activeSettingsView !== 'main'}
            on:click={toggleMenu}
            on:keydown={e => e.key === 'Enter' && toggleMenu()}
            role="button"
            tabindex="0"
            aria-label={$text('settings.open_settings_menu.text')}
            bind:this={profileContainer}
        >
            <div class="profile-picture" style={profileImageUrl ? `background-image: url(${profileImageUrl})` : ''}></div>
        </div>

        <div class="close-icon-container" class:visible={isMenuVisible}>
            <button 
                class="icon-button"
                aria-label={$text('settings.close_settings_menu.text')}
                on:click={toggleMenu}
            >
                <div class="clickable-icon icon_close"></div>
            </button>
        </div>
    </div>
{/if}

<div 
    class="settings-menu" 
    class:visible={isMenuVisible}
    class:overlay={isMenuVisible}
>
    <div class="settings-header" class:submenu-active={activeSettingsView !== 'main' && showSubmenuInfo}>
        <div class="header-content">
            <button 
                class="nav-button"
                class:left={navButtonLeft}
                class:left-aligned={activeSettingsView !== 'main'}
                on:click={activeSettingsView !== 'main' ? backToMainView : null}
                aria-disabled={activeSettingsView === 'main'}
            >
                <div class="clickable-icon icon_back" class:visible={activeSettingsView !== 'main'}></div>
                {@html $text('settings.settings.text')}
            </button>
            
            <a 
                href={currentHelpLink} 
                target="_blank" 
                use:tooltip
                rel="noopener noreferrer" 
                class="help-button-container" 
                aria-label={$text('documentation.open_documentation.text')}
            >
                <div class="help-button"></div>
            </a>
        </div>
        
        {#if activeSettingsView !== 'main' && showSubmenuInfo}
            <div 
                class="submenu-info" 
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
    
    <div class="settings-content-wrapper" bind:this={settingsContentElement}>
        <CurrentSettingsPage 
            {activeSettingsView}
            {direction}
            {username}
            {isInSignupMode}
            {settingsViews}
            bind:isIncognitoEnabled
            bind:isGuestEnabled
            bind:isOfflineEnabled
            on:viewChange={handleViewChange}
            on:quickSettingClick={handleQuickSettingClick}
            on:logout={handleLogout}
        />
        
        <SettingsFooter />
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
        transition: opacity 0.3s ease;
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
        transform: translate(-260px, 130px);
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
        background-image: url('@openmates/ui/static/images/placeholders/userprofileimage.jpeg');
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
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
        }

        .settings-menu.overlay {
            box-shadow: -4px 0 12px rgba(0, 0, 0, 0.15);
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
        padding: 16px;
        padding-bottom: 12px;
        position: sticky;
        top: 0;
        z-index: 10;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        display: flex;
        flex-direction: column;
        border-bottom: 1px solid var(--color-grey-30);
        position: relative;
        min-height: 24px;
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
        align-items: center;
        position: absolute;
        left: 110px;
        padding: 4px 0;
        transition: all 0.3s ease;
        pointer-events: none; /* Disable click interactions by default */
    }

    .nav-button.left {
        cursor: pointer;
        left: 0px;
        pointer-events: all; /* Enable click interactions when in submenu */
    }

    .nav-button[aria-disabled="true"]:hover {
        cursor: default;
    }
    
    .nav-button[aria-disabled="false"]:hover {
        cursor: pointer;
    }

    .submenu-info {
        padding-top: 35px;
        margin-bottom: -10px;
        overflow: hidden;
    }

    .help-button-container {
        all: unset;
        position: absolute;
        right: 0;
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
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
</style>