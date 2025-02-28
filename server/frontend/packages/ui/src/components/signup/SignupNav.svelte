<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { _ } from 'svelte-i18n';
    import { processedImageUrl } from '../../stores/profileImage';
    
    const dispatch = createEventDispatcher();

    export let showSkip = false;
    export let currentStep = 1;

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
        } else {
            dispatch('skip');
        }
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

    $: skipButtonText = $processedImageUrl 
        ? $_('signup.next.text') 
        : $_('signup.skip.text');
</script>

<div class="nav-area">
    <button class="nav-button" on:click={handleBackClick}>
        <div class="clickable-icon icon_back"></div>
        {getNavText(currentStep)}
    </button>
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
</style>
