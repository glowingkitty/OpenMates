<script lang="ts" context="module">
    import { writable } from 'svelte/store';
    export const teamEnabled = writable(true);
    export const settingsMenuVisible = writable(false);
    export const isMobileView = writable(false);
</script>

<script lang="ts">
    import SettingsItem from './SettingsItem.svelte';
    import { onMount } from 'svelte';
    
    // Props for user and team information
    export let teamSelected = 'xhain';
    
    // State for toggles and menu visibility
    let isMenuVisible = false;
    let isTeamEnabled = true;
    let isIncognitoEnabled = false;
    let isGuestEnabled = false;
    let isOfflineEnabled = false;

    // Handler for profile click to show menu
    function toggleMenu(): void {
        isMenuVisible = !isMenuVisible;
        settingsMenuVisible.set(isMenuVisible);
    }

    // Handler for quicksettings menu item clicks
    function handleQuickSettingClick(toggleName: 'team' | 'incognito' | 'guest' | 'offline'): void {
        switch(toggleName) {
            case 'team':
                isTeamEnabled = !isTeamEnabled;
                teamEnabled.set(isTeamEnabled); // Update the store
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

    // Sync the local state with the store on initialization
    $: {
        teamEnabled.set(isTeamEnabled);
    }

    // Handle window resize
    function updateMobileState(): void {
        isMobileView.set(window.innerWidth <= 1100);
    }

    // Setup listeners
    onMount(() => {
        updateMobileState(); // Initial check
        window.addEventListener('resize', updateMobileState);
        document.addEventListener('click', handleClickOutside);
        
        return () => {
            window.removeEventListener('resize', updateMobileState);
            document.removeEventListener('click', handleClickOutside);
        };
    });

    // Simplified click outside handler using store value
    function handleClickOutside(event: MouseEvent): void {
        if ($isMobileView) {
            const settingsMenu = document.querySelector('.settings-menu');
            const profileContainer = document.querySelector('.profile-container');
            
            if (settingsMenu && 
                profileContainer && 
                !settingsMenu.contains(event.target as Node) && 
                !profileContainer.contains(event.target as Node)) {
                isMenuVisible = false;
                settingsMenuVisible.set(false);
            }
        }
    }

    // Add reactive statement to handle active-chat opacity
    $: if (typeof window !== 'undefined') {
        const activeChatContainer = document.querySelector('.active-chat-container');
        if (activeChatContainer) {
            if (window.innerWidth <= 1100 && isMenuVisible) {
                activeChatContainer.classList.add('dimmed');
            } else {
                activeChatContainer.classList.remove('dimmed');
            }
        }
    }
</script>

<div class="profile-container-wrapper">
    <div 
        class="profile-container" 
        class:menu-open={isMenuVisible}
        on:click={toggleMenu}
        on:keydown={e => e.key === 'Enter' && toggleMenu()}
        role="button"
        tabindex="0"
        aria-label="Open settings menu"
    >
        <div class="profile-picture"></div>
        
        {#if teamSelected}
            <div class="team-picture" class:disabled={!isTeamEnabled}></div>
        {/if}
    </div>

    <!-- Close icon in wrapper -->
    <div class="close-icon-container" class:visible={isMenuVisible}>
        <button 
            class="clickable-icon icon_close" 
            aria-label="Close"
            on:click={toggleMenu}
        ></button>
    </div>
</div>

<div 
    class="settings-menu" 
    class:visible={isMenuVisible}
    class:overlay={isMenuVisible}
>
    <div class="settings-header">
        <div class="header-container">
            <div class="header-top">
                <div class="header-left">
                    <button 
                        class="clickable-icon icon_search" 
                        aria-label="Search"
                    ></button>
                </div>
                <div class="header-center">
                    <h4>Settings</h4>
                </div>
                <div class="header-left"></div>
            </div>
            <div class="header-bottom">
                <div class="user-info-container">
                    <div class="username">Kitty</div>
                    <div class="credits-container">
                        <span class="credits-icon">💰</span>
                        <div class="credits-text">
                            <span class="credits-amount"><mark>4800 credits</mark> </span>
                            <!-- <span class="add-credits-button" aria-label="Add credits">+</span> -->
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <div class="settings-content">
        <!-- Quick Settings -->
        <SettingsItem 
            icon="quicksetting_icon quicksetting_icon_team"
            title="Team"
            hasToggle={true}
            bind:checked={isTeamEnabled}
            onClick={() => handleQuickSettingClick('team')}
        />
        <SettingsItem 
            icon="quicksetting_icon quicksetting_icon_incognito"
            title="Incognito"
            hasToggle={true}
            bind:checked={isIncognitoEnabled}
            onClick={() => handleQuickSettingClick('incognito')}
        />
        <SettingsItem 
            icon="quicksetting_icon quicksetting_icon_guest"
            title="Guest"
            hasToggle={true}
            bind:checked={isGuestEnabled}
            onClick={() => handleQuickSettingClick('guest')}
        />
        <SettingsItem 
            icon="quicksetting_icon quicksetting_icon_offline"
            title="Offline"
            hasToggle={true}
            bind:checked={isOfflineEnabled}
            onClick={() => handleQuickSettingClick('offline')}
        />

        <!-- Regular Settings -->
        <SettingsItem icon="team" title="Team" onClick={() => {}} />
        <SettingsItem icon="user" title="User" onClick={() => {}} />
        <SettingsItem icon="task" title="Usage" onClick={() => {}} />
        <SettingsItem icon="billing" title="Billing" onClick={() => {}} />
        <SettingsItem icon="app" title="Apps" onClick={() => {}} />
        <SettingsItem icon="mate" title="Mates" onClick={() => {}} />
        <SettingsItem icon="messenger" title="Messengers" onClick={() => {}} />
        <SettingsItem icon="developer" title="Developers" onClick={() => {}} />
        <SettingsItem icon="interface" title="Interface" onClick={() => {}} />
        <SettingsItem icon="quicksetting_icon quicksetting_icon_logout" title="Logout" onClick={() => {}} />

        <!-- Documentation links section -->
        <div class="submenu-section">
            <div class="submenu-group">
                <h3>Docs</h3>
                <a href="/user-guide" class="submenu-link">User guide</a>
                <a href="/api-docs" class="submenu-link">API docs</a>
            </div>

            <div class="submenu-group">
                <h3>Contact</h3>
                <a href="/discord" class="submenu-link">Discord</a>
                <a href="/email" class="submenu-link">Email</a>
            </div>

            <div class="submenu-group">
                <h3>Legal</h3>
                <a href="/imprint" class="submenu-link">Imprint</a>
                <a href="/privacy" class="submenu-link">Privacy</a>
                <a href="/terms" class="submenu-link">Terms and conditions</a>
            </div>
        </div>
    </div>
</div>

<style>
    /* Add wrapper to maintain position */
    .profile-container-wrapper {
        position: fixed;
        top: 10px;
        right: 10px;
        width: 57px;
        height: 57px;
        z-index: 1005;
    }

    .profile-container {
        position: absolute;
        top: 0;
        right: 0;
        width: 57px;
        height: 57px;
        border-radius: 50%;
        cursor: pointer;
        transition: transform 0.3s ease;
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

    .profile-picture {
        border-radius: 50%;
        width: 100%;
        height: 100%;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-color: var(--color-grey-20);
        background-image: url('/images/placeholders/userprofileimage.jpeg');
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    .team-picture {
        position: absolute;
        bottom: -2px;
        left: -2px;
        width: 30px;
        height: 30px;
        border-radius: 50%;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-color: var(--color-grey-20);
        background-image: url('/images/placeholders/teamprofileimage.png');
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
    .settings-content {
        opacity: 0;
        /* Quick fade out when closing */
        transition: opacity 0.3s ease 0s;
    }

    .settings-menu.visible .settings-header,
    .settings-menu.visible .settings-content {
        opacity: 1;
        /* Delayed fade in when opening */
        transition: opacity 0.3s ease 0.15s;
    }

    .settings-header {
        background-color: var(--color-grey-20);
        padding: 16px;
        position: sticky;
        top: 0;
        z-index: 10;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }

    .header-container {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .header-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
    }

    .header-bottom {
        display: flex;
        align-items: flex-start;
        padding-top: 8px;
        border-top: 1px solid var(--color-grey-30);
    }

    .user-info-container {
        margin-left: 72px;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .username {
        font-size: 22px;
        font-weight: 500;
        color: var(--color-grey-100);
    }

    .credits-container {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .credits-text {
        color: var(--color-grey-100);
        font-size: 16px;
        background: none;
        padding: 0;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .credits-icon {
        font-size: 16px;
    }

    .header-center {
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
    }

    .header-left {
        width: 24px;
    }

    .settings-content {
        flex: 1;
        overflow-y: auto;
        padding-bottom: 16px;
        scrollbar-width: thin;
        scrollbar-color: var(--color-grey-40) transparent;
    }

    .settings-content::-webkit-scrollbar {
        width: 8px;
    }

    .settings-content::-webkit-scrollbar-track {
        background: transparent;
    }

    .settings-content::-webkit-scrollbar-thumb {
        background-color: var(--color-grey-40);
        border-radius: 4px;
        border: 2px solid var(--color-grey-20);
    }

    .submenu-section {
        padding: 0 16px 16px;
    }

    .submenu-group {
        margin-bottom: 16px;
    }

    .submenu-group h3 {
        color: var(--color-grey-60);
        font-size: 14px;
        font-weight: 600;
        margin: 6px 0;
        user-select: none;
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
    }

    .submenu-link {
        display: block;
        color: var(--color-grey-50);
        text-decoration: none;
        padding: 6px 0;
        font-size: 14px;
        transition: color 0.2s ease;
        user-select: none;
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
    }

    .submenu-link:hover {
        color: var(--color-primary);
    }

    .team-picture.disabled {
        opacity: 0;
        filter: grayscale(100%);
        transition: all 0.3s ease;
    }

    :global(.active-chat-container) {
        transition: opacity 0.3s ease;
    }

    :global(.active-chat-container.dimmed) {
        opacity: 0.3;
    }
</style>