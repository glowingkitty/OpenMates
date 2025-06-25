<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { _ } from 'svelte-i18n';
    import { userProfile } from '../../stores/userProfile'; // Import userProfile store
    import { getWebsiteUrl, routes } from '../../config/links';
    // Import current step store and gift check stores
    import { currentSignupStep, isLoadingGiftCheck, hasGiftForSignup } from '../../stores/signupState'; 
    
    const dispatch = createEventDispatcher();

    export let showSkip = false;
    export let currentStep = 1;
    export let selectedAppName: string | null = null;
    export let showAdminButton = false;

    function handleBackClick() {
        if (currentStep === 1) {
            dispatch('back');
        } else if (currentStep === 3) {
            dispatch('logout');
        } else if (currentStep === 6) {
            // Special case: Go back from Step 6 to Step 4
            dispatch('step', { step: 4 });
        } else {
            dispatch('step', { step: currentStep - 1 });
        }
    }

    function handleSkipClick() {
        // Use userProfile.profile_image_url to check if image exists for step 3
        if (currentStep === 3 && $userProfile.profile_image_url) { // Next from step 3 (profile pic)
            dispatch('step', { step: 4 });
        } else if (currentStep === 4 && $userProfile.tfa_enabled) { // Next from step 4 (if TFA already enabled)
            dispatch('step', { step: 6 });
        } else if (currentStep === 6 && selectedAppName) { // Next from step 6 (verify code)
             // This case seems handled by Step4BottomContent dispatching step 5 on success
             // Let's assume the 'skip' button here means proceeding after verification
             // which is handled internally in Step 4 bottom. If verification fails, user stays.
             // If successful, Step4Bottom dispatches step 5.
             // Let's keep the original skip logic for now, might need adjustment based on testing.
             dispatch('skip'); // Or should this go to step 5? Let's stick to original 'skip' for now.
        } else if (currentStep === 7 && $userProfile.consent_privacy_and_apps_default_settings) { // Use consent_privacy_and_apps_default_settings
            dispatch('step', { step: 8 });
        } else if (currentStep === 8 && $userProfile.consent_mates_default_settings) { // Use consent_mates_default_settings
            dispatch('step', { step: 9 });
        } else if (currentStep === 9) { // Skip demo
            console.debug('Skip and show demo first');
            // Custom action for step 9 - will be replaced later with real action
        } else { // Default skip action (or steps 7/8 if not consented)
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
        if (step === 6) return $_('signup.connect_2fa_app.text'); // Changed text to match step 4
        if (step === 7) return $_('signup.2fa_app_reminder.text');
        if (step === 8) return $_('signup.settings.text');
        if (step === 9) return $_('signup.mates_settings.text');
        if (step === 10) return $_('signup.select_credits.text');
        return $_('signup.sign_up.text');
    }

    // Update the reactive skipButtonText for different steps and states
    $: skipButtonText = 
        // Use userProfile.profile_image_url for step 3 logic
        (currentStep === 3 && $userProfile.profile_image_url) ? $_('signup.next.text') : // Step 3 -> 4
        (currentStep === 4 && $userProfile.tfa_enabled) ? $_('signup.next.text') : // Step 4 (if TFA enabled) -> 6
        (currentStep === 6 && selectedAppName) ? $_('signup.next.text') : // Step 6 -> 7 (after verification) - This might need review
        (currentStep === 7 && $userProfile.consent_privacy_and_apps_default_settings) ? $_('signup.next.text') : // Use consent_privacy_and_apps_default_settings
        (currentStep === 8 && $userProfile.consent_mates_default_settings) ? $_('signup.next.text') : // Use consent_mates_default_settings
        // (currentStep === 9) ? $_('signup.skip_and_show_demo_first.text') : // Step 9 skip demo # TODO implement this later
        $_('signup.skip.text'); // Default skip text (or steps 7/8 if not consented)

    // Determine if the skip/next button should be shown
    // Show if:
    // - Step 4 AND TFA is already enabled OR
    // - Step 7 AND consent_privacy_and_apps_default_settings is true OR
    // - Step 8 AND consent_mates_default_settings is true OR
    // - Step 9 AND gift check is done AND NO gift is available OR
    // - showSkip prop is true AND it's not Step 4, 7, 8, or 9 (original skip logic)
    $: showActualSkipButton = 
        (currentStep === 4 && $userProfile.tfa_enabled) ||
        (currentStep === 7 && $userProfile.consent_privacy_and_apps_default_settings) || // Use consent_privacy_and_apps_default_settings
        (currentStep === 8 && $userProfile.consent_mates_default_settings) || // Use consent_mates_default_settings
        // (currentStep === 9 && !$isLoadingGiftCheck && !$hasGiftForSignup) || // Show skip/demo only if NO gift available # TODO implement this later
        (showSkip && ![4, 7, 8, 9].includes(currentStep)); // Prevent showing default skip if other conditions met

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
    
    {#if showActualSkipButton}
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
