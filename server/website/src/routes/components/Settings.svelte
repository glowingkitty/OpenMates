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
        <span>Team</span>
        <Toggle 
            bind:checked={isTeamEnabled}
            name="team"
            ariaLabel="Toggle team mode"
        />
    </div>
    <div class="menu-item">
        <span>Incognito</span>
        <Toggle 
            bind:checked={isIncognitoEnabled}
            name="incognito"
            ariaLabel="Toggle incognito mode"
        />
    </div>
    <div class="menu-item">
        <span>Guest</span>
        <Toggle 
            bind:checked={isGuestEnabled}
            name="guest"
            ariaLabel="Toggle guest mode"
        />
    </div>
    <div class="menu-item">
        <span>Offline</span>
        <Toggle 
            bind:checked={isOfflineEnabled}
            name="offline"
            ariaLabel="Toggle offline mode"
        />
    </div>
    <div class="menu-item">Logout</div>
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
</style>