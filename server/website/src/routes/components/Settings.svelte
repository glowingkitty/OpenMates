<script lang="ts" context="module">
    import { writable } from 'svelte/store';
    export const teamEnabled = writable(true);
</script>

<script lang="ts">
    import SettingsItem from './SettingsItem.svelte';
    
    // Props for user and team information
    export let teamSelected = 'xhain';
    
    // State for toggles
    let isTeamEnabled = true;
    let isIncognitoEnabled = false;
    let isGuestEnabled = false;
    let isOfflineEnabled = false;

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
</script>

<div class="profile-container">
    <div class="profile-picture"></div>
    
    {#if teamSelected}
        <div class="team-picture" class:disabled={!isTeamEnabled}></div>
    {/if}
</div>

<div class="settings-menu">
    <div class="settings-header">
        <div class="header-left">
            <button 
                class="clickable-icon icon_close" 
                aria-label="Close"
            ></button>
            <h4>Settings</h4>
        </div>
        <div class="header-center">
            <button 
                class="clickable-icon icon_search" 
                aria-label="Search"
            ></button>
        </div>
        <div class="header-right">
            <button 
                class="clickable-icon icon_logout" 
                aria-label="Logout"
            ></button>
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
    .profile-container {
        position: fixed;
        top: 10px;
        right: 10px;
        display: inline-block;
        width: 57px;
        height: 57px;
        border-radius: 50%;
        margin: 0;
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
        width: 323px;
        border-radius: 17px;
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    .settings-header {
        background-color: var(--color-grey-20);
        padding: 16px;
        position: sticky;
        top: 0;
        z-index: 10;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        display: flex;
        justify-content: space-between;
        align-items: center;
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

    .header-left {
        display: flex;
        align-items: center;
        gap: 12px;
        flex: 1;
    }

    .header-left h4 {
        margin: 0;
        font-size: 14px;
        font-weight: bold;
        color: var(--color-grey-60);
    }

    .header-center {
        position: static;
        transform: none;
        display: flex;
        align-items: center;
        justify-content: center;
        width: auto;
        z-index: 1;
        flex: 1;
        display: flex;
        justify-content: center;
    }

    .header-right {
        flex: 1;
        display: flex;
        justify-content: flex-end;
    }
</style>