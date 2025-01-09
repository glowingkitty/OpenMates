<script>
    import Toggle from './Toggle.svelte';
    
    // Props for user and team information
    export let teamSelected = 'xhain';  // slug of the team selected
    
    // State for toggles
    let isTeamEnabled = true;
    let isIncognitoEnabled = false;
    let isGuestEnabled = false;
    let isOfflineEnabled = false;
</script>

<div class="profile-container">
    <div 
        class="profile-picture"
    ></div>
    
    {#if teamSelected}
        <div 
            class="team-picture"
        ></div>
    {/if}
</div>

<div class="settings-menu">
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size quicksetting_icon quicksetting_icon_team"></div>
            <span class="menu-title"><mark>Team</mark></span>
        </div>
        <Toggle 
            bind:checked={isTeamEnabled}
            name="team"
            ariaLabel="Toggle team mode"
        />
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size quicksetting_icon quicksetting_icon_incognito"></div>
            <span class="menu-title"><mark>Incognito</mark></span>
        </div>
        <Toggle 
            bind:checked={isIncognitoEnabled}
            name="incognito"
            ariaLabel="Toggle incognito mode"
        />
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size quicksetting_icon quicksetting_icon_guest"></div>
            <span class="menu-title"><mark>Guest</mark></span>
        </div>
        <Toggle 
            bind:checked={isGuestEnabled}
            name="guest"
            ariaLabel="Toggle guest mode"
        />
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size quicksetting_icon quicksetting_icon_offline"></div>
            <span class="menu-title"><mark>Offline</mark></span>
        </div>
        <Toggle 
            bind:checked={isOfflineEnabled}
            name="offline"
            ariaLabel="Toggle offline mode"
        />
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size team"></div>
            <span class="menu-title"><mark>Team</mark></span>
        </div>
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size user"></div>
            <span class="menu-title"><mark>User</mark></span>
        </div>
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size task"></div>
            <span class="menu-title"><mark>Usage</mark></span>
        </div>
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size billing"></div>
            <span class="menu-title"><mark>Billing</mark></span>
        </div>
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size app"></div>
            <span class="menu-title"><mark>Apps</mark></span>
        </div>
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size mate"></div>
            <span class="menu-title"><mark>Mates</mark></span>
        </div>
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size messenger"></div>
            <span class="menu-title"><mark>Messengers</mark></span>
        </div>
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size developer"></div>
            <span class="menu-title"><mark>Developers</mark></span>
        </div>
    </div>
    <div class="menu-item">
        <div class="menu-item-left">
            <div class="icon settings_size interface"></div>
            <span class="menu-title"><mark>Interface</mark></span>
        </div>
    </div>

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
        overflow: hidden;
        height: 100%;
        width: 323px;
        background-color: var(--color-grey-20);
        border-radius: 17px;
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
    }

    .menu-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 16px;
    }

    .menu-item-left {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .menu-title {
        text-align: left;
    }

    .submenu-section {
        padding: 0 16px 16px;
    }

    .submenu-group {
        margin-bottom: 24px;
    }

    .submenu-group h3 {
        color: var(--color-grey-60);
        font-size: 14px;
        font-weight: 600;
        margin: 8px 0;
    }

    .submenu-link {
        display: block;
        color: var(--color-grey-50);
        text-decoration: none;
        padding: 8px 0;
        font-size: 14px;
        transition: color 0.2s ease;
    }

    .submenu-link:hover {
        color: var(--color-primary);
    }
</style>