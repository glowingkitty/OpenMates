<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { _ } from 'svelte-i18n';
    import { processedImageUrl } from '../../stores/profileImage';
    import { getWebsiteUrl, routes } from '../../config/links';
    
    const dispatch = createEventDispatcher();

    export let showSkip = false;
    export let currentStep = 1;
    export let selectedAppName: string | null = null;
    export let isAdmin = false;
    export let showAdminButton = false;

    function handleBackClick() {
        if (currentStep === 1) {
            dispatch('back');
        } else if (currentStep === 3) {
            dispatch('logout');
        } else {
            dispatch('step', { step: currentStep - 1 });
        }
    }

    function handleSkipClick() {
        if (currentStep === 3) {
            dispatch('step', { step: 4 });
        } else if (currentStep === 9) {
            console.log('Skip and show demo first');
            // Custom action for step 9 - will be replaced later with real action
        } else {
            dispatch('skip');
        }
    }

    function openSelfHostedDocs() {
        const docsUrl = getWebsiteUrl(routes.docs.selfhosted);
        window.open(docsUrl, '_blank');
    }

    function getNavText(step: number) {
        if (step === 1) return $_('login.login_button.text');
        if (step === 3) return $_('settings.logout.text');
        if (step === 4) return $_('signup.profile_image.text');
        if (step === 5) return $_('signup.connect_2fa_app.text');
        if (step === 6) return $_('signup.2fa_backup_codes.text');
        if (step === 7) return $_('signup.2fa_app_reminder.text');
        if (step === 8) return $_('signup.settings.text');
        if (step === 9) return $_('signup.mates_settings.text');
        if (step === 10) return $_('signup.select_credits.text');
        return $_('signup.sign_up.text');
    }

    // Update the reactive skipButtonText to include the case for step 9
    $: skipButtonText = (currentStep === 3 && $processedImageUrl) || 
                         (currentStep === 6 && selectedAppName)
        ? $_('signup.next.text')
        : currentStep === 9
            ? $_('signup.skip_and_show_demo_first.text')
            : $_('signup.skip.text');
</script>

<div class="nav-area">
    <button class="nav-button" on:click={handleBackClick}>
        <div class="clickable-icon icon_back"></div>
        {getNavText(currentStep)}
    </button>
    
    {#if showAdminButton}
        <button class="admin-button" on:click={openSelfHostedDocs}>
            <div class="clickable-icon icon_server admin-icon"></div>
            <span class="admin-text">{$_('signup.server_admin.text')}</span>
            <div class="clickable-icon icon_question question-icon"></div>
        </button>
    {/if}
    
    {#if showSkip}
        <button class="nav-button" on:click={handleSkipClick}>
            {skipButtonText}
            <div class="clickable-icon icon_back icon-mirrored"></div>
        </button>
    {/if}
</div>

<style>
    .nav-area {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 48px;
        z-index: 1;
        display: flex;
        justify-content: space-between;
    }

    .nav-button {
        all: unset;
        position: relative;
        font-size: 14px;
        color: var(--color-grey-60);
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .nav-button:hover {
        background: none;
        cursor: pointer;
    }

    .icon-mirrored {
        transform: scaleX(-1);
    }

    .admin-button {
        position: absolute;
        left: 50%;
        top: 0;
        transform: translateX(-50%);
        display: flex;
        align-items: center;
        gap: 8px;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 19px;
        padding: 6px 12px;
        font-size: 16px;
        cursor: pointer;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    }
    
    .admin-text {
        white-space: nowrap;
        font-weight: medium;
        color: white;
    }
    
    .admin-icon {
        width: 17px;
        height: 17px;
        background: white;
    }
    
    .question-icon {
        width: 17px;
        height: 17px;
        background: white;
        opacity: 0.5;
    }
</style>
